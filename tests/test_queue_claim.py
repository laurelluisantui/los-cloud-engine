import datetime

from engine.auth import get_org_id
from engine.db import SessionLocal
from engine.models import Agent, Schedule, Task, utcnow
from engine.worker import claim_next, tick_schedules


def test_task_is_claimed_once(seeded):
    one, two = SessionLocal(), SessionLocal()
    org_id = get_org_id(one)
    agent = one.query(Agent).filter_by(organization_id=org_id, slug="sales-research").one()
    task = Task(organization_id=org_id, agent_id=agent.id, status="queued",
                skill_slug="prospect-research", input={})
    one.add(task)
    one.commit()
    claimed = claim_next(one)
    assert claimed is not None
    assert claimed.attempts == 1
    assert claimed.status == "running"
    assert claim_next(two) is None
    one.close()
    two.close()


def test_due_schedule_enqueues_only_one_job(seeded):
    session = SessionLocal()
    org_id = get_org_id(session)
    session.add(Schedule(
        organization_id=org_id, name="test", status="active",
        interval_seconds=60, agent_slug="sales-research",
        skill_slug="prospect-research", input={},
        next_run_at=utcnow() - datetime.timedelta(seconds=1)
    ))
    session.commit()
    assert tick_schedules(session) == 1
    assert tick_schedules(session) == 0
    assert session.query(Task).count() == 1
    session.close()
