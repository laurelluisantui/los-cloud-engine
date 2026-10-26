"""Failed tasks: errors are logged, retried, and end in an explicit failed state."""
import datetime

from engine.db import SessionLocal
from engine.models import AuditLog, Task
from engine.worker import process_one


def failing_fetch(url, timeout=15.0):
    raise RuntimeError("simulated network outage")


def test_failed_task_logged_and_retried_then_failed(client, owner_headers, seeded):
    r = client.post("/v1/tasks", headers=owner_headers, json={
        "agent_slug": "sales-research",
        "input": {"business_name": "B", "website": "https://down.example"},
        "max_retries": 2,
    })
    task_id = r.json()["task_id"]
    session = SessionLocal()
    task = session.query(Task).filter_by(id=task_id).one()

    process_one(session, task, fetch=failing_fetch)
    session.refresh(task)
    assert task.status == "queued"  # retry scheduled
    assert task.scheduled_at is not None

    task.scheduled_at = datetime.datetime.utcnow()  # make the retry due
    session.commit()
    process_one(session, task, fetch=failing_fetch)
    session.refresh(task)
    assert task.status == "failed"
    session.close()

    # Status API reports the real failure, from recorded runs.
    body = client.get(f"/v1/tasks/{task_id}", headers=owner_headers).json()
    assert body["status"] == "failed"
    assert any("simulated network outage" in (run["error"] or "")
               for run in body["runs"])

    # Audit trail captured retry + final failure.
    session = SessionLocal()
    actions = [a.action for a in session.query(AuditLog)
               .filter_by(entity="task", entity_id=task_id).all()]
    session.close()
    assert "task.retry" in actions
    assert "task.failed" in actions


def test_timeout_marks_task_failed(client, owner_headers, seeded, tmp_path, monkeypatch):
    import engine.config as config
    from engine import skills_lib

    # Build a slow skill on disk in a tmp skills dir.
    slug = "slow-skill"
    root = tmp_path / slug
    root.mkdir()
    (root / "SKILL.md").write_text(
        "---\nname: slow-skill\nversion: 0.1.0\ndescription: t\n---\nbody\n")
    (root / "schema.json").write_text(
        '{"input": {"type": "object"}, "output": {"type": "object"}}')
    (root / "impl.py").write_text(
        "import time\n"
        "def run(context, input):\n"
        "    time.sleep(5)\n"
        "    return {}\n")
    monkeypatch.setattr(config, "SKILLS_DIR", str(tmp_path))
    monkeypatch.setattr(config, "REPO_ROOT", str(tmp_path))
    skills_lib.sync_library(SessionLocal(), _org_id(seeded))

    from engine.models import Agent, Skill
    session = SessionLocal()
    skill = session.query(Skill).filter_by(slug=slug).one()
    agent = session.query(Agent).filter_by(slug="sales-research").one()
    agent.skills = agent.skills + [slug]
    session.commit()

    r = client.post("/v1/tasks", headers=owner_headers, json={
        "agent_slug": "sales-research", "skill_slug": slug,
        "input": {}, "timeout_seconds": 1, "max_retries": 1})
    assert r.status_code == 201, r.text
    task_id = r.json()["task_id"]
    process_one(session, session.query(Task).filter_by(id=task_id).one(),
                fetch=lambda u, timeout=15.0: "")
    session.refresh(session.query(Task).filter_by(id=task_id).one())
    task = session.query(Task).filter_by(id=task_id).one()
    assert task.status == "failed"
    session.close()
    body = client.get(f"/v1/tasks/{task_id}", headers=owner_headers).json()
    assert any("timeout" in (run["error"] or "") for run in body["runs"])


def test_timed_out_process_cannot_finish_after_failure(
    client, owner_headers, seeded, tmp_path, monkeypatch
):
    import time
    import engine.config as config
    from engine.skills_lib import sync_library
    from engine.models import Agent

    marker = tmp_path / "late-result"
    slug = "late-writer"
    root = tmp_path / slug
    root.mkdir()
    (root / "SKILL.md").write_text(
        "---\nname: late-writer\nversion: 0.1.0\ndescription: test\n---\nbody\n"
    )
    (root / "schema.json").write_text('{"input":{"type":"object"},"output":{"type":"object"}}')
    (root / "impl.py").write_text(
        "import time\nfrom pathlib import Path\n"
        f"def run(context, input):\n    time.sleep(2)\n"
        f"    Path({str(marker)!r}).write_text('ran')\n    return {{}}\n"
    )
    monkeypatch.setattr(config, "SKILLS_DIR", str(tmp_path))
    monkeypatch.setattr(config, "REPO_ROOT", str(tmp_path))
    session = SessionLocal()
    sync_library(session, _org_id(seeded))
    agent = session.query(Agent).filter_by(slug="sales-research").one()
    agent.skills = agent.skills + [slug]
    session.commit()
    r = client.post("/v1/tasks", headers=owner_headers, json={
        "agent_slug": "sales-research", "skill_slug": slug,
        "input": {}, "timeout_seconds": 1, "max_retries": 1
    })
    task_id = r.json()["task_id"]
    process_one(session, session.query(Task).filter_by(id=task_id).one())
    time.sleep(2.2)
    assert not marker.exists()
    assert client.get(f"/v1/tasks/{task_id}", headers=owner_headers).json()["status"] == "failed"
    session.close()


def _org_id(seeded_flag):
    from engine.auth import get_org_id
    s = SessionLocal()
    org = get_org_id(s)
    s.close()
    return org
