"""Background worker: polls the task queue, executes with per-task timeout,
retries with backoff, and ticks the schedule/event engines. Background jobs
continue after a chat closes — never fabricate status; read task_runs."""
import concurrent.futures
import datetime
import logging
import threading
import time
from typing import Optional

from . import audit, config
from .db import SessionLocal
from .logging import configure, log_event
from .models import EventTrigger, Schedule, Task, TaskRun, utcnow
from .runtime import execute_task

log = logging.getLogger("los.worker")
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)


class TaskTimeout(Exception):
    pass


def _run_fresh(task_id: str, fetch=None):
    """Executor body: its own session (SQLAlchemy sessions are not thread-safe)."""
    session = SessionLocal()
    try:
        task = session.query(Task).filter_by(id=task_id).one()
        return execute_task(session, task, fetch=fetch)
    finally:
        session.close()


def _fail_run(session, task: Task, message: str) -> None:
    run = (session.query(TaskRun).filter_by(task_id=task.id)
           .order_by(TaskRun.started_at.desc()).first())
    if run and run.status == "running":
        run.status = "failed"
        run.error = message
        run.finished_at = utcnow()


def process_one(session, task: Task, fetch=None) -> None:
    task.status = "running"
    task.attempts += 1
    session.commit()
    try:
        future = _pool.submit(_run_fresh, task.id, fetch)
        future.result(timeout=task.timeout_seconds)
        task.status = "succeeded"
        log_event(log, logging.INFO, "task succeeded", task_id=task.id)
        audit.log(session, None, "task.succeeded", "task", task.id,
                  {"attempts": task.attempts}, org_id=task.organization_id)
    except concurrent.futures.TimeoutError:
        _fail_run(session, task, f"timeout after {task.timeout_seconds}s")
        _retry_or_fail(session, task, f"timeout after {task.timeout_seconds}s")
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
    return (session.query(Task)
            .filter(Task.status == "queued")
            .filter((Task.scheduled_at == None) | (Task.scheduled_at <= now))  # noqa: E711
            .order_by(Task.priority.asc(), Task.created_at.asc())
            .first())


def tick_schedules(session) -> int:
    """Enqueue tasks for due active schedules. Returns count enqueued."""
    now = utcnow()
    n = 0
    for s in (session.query(Schedule).filter_by(status="active")
              .filter(Schedule.next_run_at <= now).all()):
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
        s.next_run_at = now + datetime.timedelta(seconds=s.interval_seconds)
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
        session = SessionLocal()
        try:
            tick_schedules(session)
            task = claim_next(session)
            if task is not None:
                process_one(session, task, fetch=fetch)
            session.close()
            time.sleep(0 if task else config.WORKER_POLL_SECONDS)
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            session.close()
            log_event(log, logging.ERROR, "worker loop error", error=str(exc))
            time.sleep(config.WORKER_POLL_SECONDS)
        if once:
            break


if __name__ == "__main__":
    run_loop()
