"""Background worker: polls the task queue, executes with per-task timeout,
retries with backoff, and ticks the schedule/event engines. Background jobs
continue after a chat closes — never fabricate status; read task_runs."""
import datetime
import logging
import multiprocessing
import time
from typing import Optional

from . import audit, config
from .db import SessionLocal, engine as db_engine, scope_session
from .logging import configure, log_event
from .models import EventTrigger, Organization, Schedule, Task, TaskRun, utcnow
from .runtime import execute_task
from sqlalchemy import update

log = logging.getLogger("los.worker")
def _run_fresh(task_id: str, org_id: str, fetch=None):
    """Child process: do not share the parent's DB pool across fork."""
    db_engine.dispose(close=False)
    session = SessionLocal()
    try:
        scope_session(session, org_id)
        task = session.query(Task).filter_by(id=task_id).one()
        try:
            execute_task(session, task, fetch=fetch)
        except Exception as exc:
            # execute_task saved the failed run with the original error.
            log_event(log, logging.ERROR, "task execution failed",
                      task_id=task_id, error=str(exc)[:500])
    finally:
        session.close()


def _fail_run(session, task: Task, message: str) -> None:
    run = (session.query(TaskRun).filter_by(task_id=task.id, attempt=task.attempts)
           .one_or_none())
    if run is None:
        run = TaskRun(organization_id=task.organization_id, task_id=task.id,
                      attempt=task.attempts, status="failed", error=message,
                      finished_at=utcnow())
        session.add(run)
    elif run.status == "running":
        run.status = "failed"
        run.error = message
        run.finished_at = utcnow()


def process_one(session, task: Task, fetch=None) -> None:
    if task.status == "queued":
        changed = session.execute(
            update(Task).where(Task.id == task.id, Task.status == "queued")
            .values(status="running", attempts=Task.attempts + 1)
        )
        session.commit()
        if changed.rowcount != 1:
            return
        session.refresh(task)
    elif task.status != "running":
        return

    # A thread timeout does not stop the task; a process can be terminated.
    # Container deployments run on Linux (fork); custom test fetches remain
    # isolated in the child and no parent session is shared.
    proc = multiprocessing.get_context("fork").Process(
        target=_run_fresh, args=(task.id, task.organization_id, fetch), daemon=True
    )
    try:
        proc.start()
        proc.join(task.timeout_seconds)
        if proc.is_alive():
            proc.terminate()
            proc.join(5)
            if proc.is_alive():
                proc.kill()
                proc.join()
            raise TimeoutError(f"timeout after {task.timeout_seconds}s")
        if proc.exitcode != 0:
            run = (session.query(TaskRun).filter_by(task_id=task.id, attempt=task.attempts)
                   .one_or_none())
            raise RuntimeError(
                run.error if run and run.error else
                f"worker process exited with code {proc.exitcode}"
            )
        run = (session.query(TaskRun).filter_by(task_id=task.id, attempt=task.attempts)
               .one_or_none())
        if run is None or run.status != "succeeded":
            raise RuntimeError(run.error if run and run.error else
                               "worker exited without a successful run record")
        task.status = "succeeded"
        log_event(log, logging.INFO, "task succeeded", task_id=task.id)
        audit.log(session, None, "task.succeeded", "task", task.id,
                  {"attempts": task.attempts}, org_id=task.organization_id)
    except TimeoutError as exc:
        _fail_run(session, task, str(exc))
        _retry_or_fail(session, task, str(exc))
    except Exception as exc:  # noqa: BLE001 - worker must catch all task errors
        _fail_run(session, task, str(exc))
        _retry_or_fail(session, task, str(exc))
    finally:
        task.updated_at = utcnow()
        session.commit()


def _retry_or_fail(session, task: Task, error: str) -> None:
    if task.attempts < task.max_retries:
        task.status = "queued"
        task.scheduled_at = utcnow() + datetime.timedelta(seconds=2 ** task.attempts)
        log_event(log, logging.WARNING, "task retry scheduled", task_id=task.id,
                  attempt=task.attempts, error=error)
        audit.log(session, None, "task.retry", "task", task.id,
                  {"attempt": task.attempts, "error": error}, org_id=task.organization_id)
    else:
        task.status = "failed"
        log_event(log, logging.ERROR, "task failed permanently", task_id=task.id, error=error)
        audit.log(session, None, "task.failed", "task", task.id,
                  {"attempts": task.attempts, "error": error}, org_id=task.organization_id)


def claim_next(session) -> Optional[Task]:
    now = utcnow()
    for _ in range(10):
        candidate = (session.query(Task.id)
                     .filter(Task.status == "queued")
                     .filter((Task.scheduled_at == None) | (Task.scheduled_at <= now))  # noqa: E711
                     .order_by(Task.priority.asc(), Task.created_at.asc())
                     .first())
        if candidate is None:
            return None
        changed = session.execute(
            update(Task).where(Task.id == candidate.id, Task.status == "queued")
            .values(status="running", attempts=Task.attempts + 1)
        )
        session.commit()
        if changed.rowcount == 1:
            return session.query(Task).filter_by(id=candidate.id).one()
        session.expire_all()
    return None


def tick_schedules(session) -> int:
    """Enqueue tasks for due active schedules. Returns count enqueued."""
    now = utcnow()
    n = 0
    for s in (session.query(Schedule).filter_by(status="active")
              .filter(Schedule.next_run_at <= now).all()):
        changed = session.execute(
            update(Schedule).where(
                Schedule.id == s.id, Schedule.status == "active",
                Schedule.next_run_at <= now
            ).values(next_run_at=now + datetime.timedelta(seconds=s.interval_seconds))
        )
        if changed.rowcount != 1:
            session.rollback()
            continue
        task = Task(organization_id=s.organization_id, skill_slug=s.skill_slug,
                    input=s.input, status="queued", created_by=f"schedule:{s.name}")
        from .models import Agent
        agent = (session.query(Agent)
                 .filter_by(organization_id=s.organization_id, slug=s.agent_slug).one_or_none())
        if agent is None:
            log_event(log, logging.ERROR, "schedule references missing agent",
                      schedule_id=s.id, agent=s.agent_slug)
            s.status = "paused"
        else:
            task.agent_id = agent.id
            session.add(task)
            n += 1
        session.commit()
    return n


def fire_event(session, org_id: str, event_name: str, payload: dict) -> int:
    n = 0
    from .models import Agent
    for t in (session.query(EventTrigger)
              .filter_by(organization_id=org_id, event_name=event_name, status="active").all()):
        agent = session.query(Agent).filter_by(organization_id=org_id, slug=t.agent_slug).one_or_none()
        if agent is None:
            continue
        merged = {**t.input_template, **payload}
        session.add(Task(organization_id=org_id, agent_id=agent.id, skill_slug=t.skill_slug,
                         input=merged, status="queued", created_by=f"event:{event_name}"))
        n += 1
    session.commit()
    return n


def run_loop(once: bool = False, fetch=None) -> None:
    configure()
    log_event(log, logging.INFO, "worker started", poll=config.WORKER_POLL_SECONDS)
    while True:
        discovery = SessionLocal()
        try:
            org_ids = [row.id for row in discovery.query(Organization.id).all()]
        except Exception as exc:  # noqa: BLE001
            log_event(log, logging.ERROR, "org discovery failed", error=str(exc))
            org_ids = []
        finally:
            discovery.close()
        worked = False
        for org_id in org_ids:
            session = SessionLocal()
            scope_session(session, org_id)
            try:
                tick_schedules(session)
                task = claim_next(session)
                if task is not None:
                    process_one(session, task, fetch=fetch)
                    worked = True
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                log_event(log, logging.ERROR, "worker loop error", error=str(exc))
            finally:
                session.close()
        if not worked and not once:
            time.sleep(config.WORKER_POLL_SECONDS)
        if once:
            break


if __name__ == "__main__":
    run_loop()
