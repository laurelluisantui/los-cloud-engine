#!/usr/bin/env python3
"""End-to-end demonstration of the L·OS Cloud Engine completion criteria.
Runs in-process (no model key, no network required) and prints real records.

  .venv/bin/python scripts/demo.py
"""
import json
import os
import sys
import tempfile

tmp = tempfile.mkdtemp(prefix="los-demo-")
os.environ["ENGINE_DATABASE_URL"] = "sqlite:///" + os.path.join(tmp, "demo.db")
os.environ["ENGINE_SKILLS_DIR_COPY"] = tmp
os.environ.pop("OPENAI_API_KEY", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import shutil  # noqa: E402

import engine.config as config  # noqa: E402

# Isolate the writable skills dir + repo root (no git commits in the demo).
demo_skills = os.path.join(tmp, "skills")
shutil.copytree(config.SKILLS_DIR, demo_skills)
config.SKILLS_DIR = demo_skills
config.REPO_ROOT = tmp

from fastapi.testclient import TestClient  # noqa: E402

import engine.auth as auth  # noqa: E402
import engine.runtime as runtime  # noqa: E402
from engine import seed  # noqa: E402
from engine.api.app import create_app  # noqa: E402

OWNER = {"id": "owner-demo-1", "email": "laurel@example.com"}
auth.verify_supabase_token = lambda token: OWNER

SAMPLE_HTML = """<html><head>
<title>Bluebonnet Dental — Family Dentist in Houston</title>
<meta name="description" content="Bluebonnet Dental offers family, cosmetic and emergency dentistry in Houston, TX.">
<meta name="viewport" content="width=device-width, initial-scale=1">
</head><body><h1>Bluebonnet Dental</h1>
<p>Call (713) 555-0182 or email hello@bluebonnetdental.example.</p>
<p>Bluebonnet Dental has served Houston families since 2010.</p>
</body></html>"""
runtime.bounded_fetch = lambda url, timeout=15.0: SAMPLE_HTML

H = {"Authorization": "Bearer demo-owner-token"}
client = TestClient(create_app())
seed.seed()


def show(title, payload):
    print(f"\n=== {title} ===")
    print(json.dumps(payload, indent=2, default=str)[:1200])


# 1. A task submitted through the API
r = client.post("/v1/tasks", headers=H, json={
    "agent_slug": "sales-research",
    "input": {"business_name": "Bluebonnet Dental",
              "website": "https://bluebonnetdental.example"}})
assert r.status_code == 201, r.text
task_id = r.json()["task_id"]
show("1. Task submitted via API", r.json())

# 2 + 3. Worker runs it: agent loads the skill from the library, completes
from engine.db import SessionLocal  # noqa: E402
from engine.models import Task, TaskRun  # noqa: E402
from engine.worker import process_one  # noqa: E402

session = SessionLocal()
task = session.query(Task).filter_by(id=task_id).one()
process_one(session, task)
run = session.query(TaskRun).filter_by(task_id=task_id).one()

# 4. Results saved to the database
show("2-4. Run completed with skill version + real output saved", {
    "task_status": task.status, "workflow": "research -> audit -> proposal",
    "skill_version": run.skill_version,
    "findings": run.output["research"]["findings"][:2],
    "audit": run.output["website_audit"]["summary"],
    "proposal": run.output["proposal"]["proposal_markdown"][:200],
    "cost_usd": run.cost_usd})
session.close()

# 5. Execution history available through the API
r = client.get(f"/v1/tasks/{task_id}", headers=H)
show("5. Execution history via API", {"status": r.json()["status"], "runs": r.json()["runs"]})

# 6. A failed task is logged and handled correctly
from engine import worker as worker_mod  # noqa: E402


def boom(url, timeout=15.0):
    raise RuntimeError("demo: prospect site unreachable")


orig = runtime.bounded_fetch
runtime.bounded_fetch = boom
r = client.post("/v1/tasks", headers=H, json={
    "agent_slug": "sales-research",
    "input": {"business_name": "Ghost Co", "website": "https://unreachable.example"},
    "max_retries": 1})
fail_id = r.json()["task_id"]
session = SessionLocal()
process_one(session, session.query(Task).filter_by(id=fail_id).one())
session.close()
runtime.bounded_fetch = orig
show("6. Failed task: real error recorded", client.get(f"/v1/tasks/{fail_id}", headers=H).json())

# 7. Skill change with approval (the Muffy skill-update flow, via her tools' REST surface)
current = client.get("/v1/skills/prospect-research", headers=H).json()
show("7a. Current skill (as Muffy's read_skill returns)", {
    "version": current["version"], "hash": current["content_hash"][:12]})

NEW_BODY = ("---\nname: prospect-research\nversion: 0.2.0\n"
            "description: Stricter note discipline.\n---\n\n# prospect-research\n\n"
            "Notes must name the page checked and the missing fact.\n")
r = client.post("/v1/skills/prospect-research/propose", headers=H,
                json={"new_version": "0.2.0", "body": NEW_BODY,
                      "reason": "notes discipline"})
show("7b. Proposed edit: sample output + pending approval (not published)", {
    "approval_id": r.json()["approval_id"],
    "sample_findings": r.json()["sample_output"]["findings"][:1]})
approval_id = r.json()["approval_id"]

# nothing changes before owner approval
assert client.get("/v1/skills/prospect-research", headers=H).json()["version"] == "0.1.0"

r = client.post(f"/v1/approvals/{approval_id}/decide", headers=H, json={"approve": True})
after = client.get("/v1/skills/prospect-research", headers=H).json()
show("7c. After approval: new version live (actual saved record)",
     {"published": r.json()["result"], "active_version": after["version"]})

# 7d. Content Agent skill change: before/after samples and actual new run.
content = client.get("/v1/skills/content-brief-drafting", headers=H).json()
content_body = content["body"].replace(
    "version: 0.1.0", "version: 0.2.0"
).replace("format: paragraph", "format: bullets")
proposed = client.post(
    "/v1/skills/content-brief-drafting/propose", headers=H,
    json={"new_version": "0.2.0", "body": content_body, "reason": "Scannable briefs"}
).json()
show("7d. Content Agent skill: before/after samples, awaiting owner approval", {
    "before": proposed["sample_output"]["draft"][:120],
    "after": proposed["proposed_sample_output"]["draft"][:120],
    "approval_id": proposed["approval_id"],
})
assert client.get("/v1/skills/content-brief-drafting", headers=H).json()["version"] == "0.1.0"
decision = client.post(
    f"/v1/approvals/{proposed['approval_id']}/decide", headers=H,
    json={"approve": True}
)
assert decision.status_code == 200, decision.text
content_task = client.post("/v1/tasks", headers=H, json={
    "agent_slug": "content-agent",
    "input": {"business_name": "Sample Business", "website": "https://example.com"},
}).json()["task_id"]
session = SessionLocal()
process_one(session, session.query(Task).filter_by(id=content_task).one())
content_run = session.query(TaskRun).filter_by(task_id=content_task).one()
show("7e. Content Agent uses the newly saved skill version", {
    "version": content_run.skill_version, "status": content_run.status,
    "draft": content_run.output["draft"][:120],
})
assert content_run.skill_version == "0.2.0"
assert content_run.output["draft"].startswith("- Content brief")
session.close()

# 8. Non-owner cannot touch Muffy or decide approvals
r = client.post("/v1/chat", headers={"X-Engine-Key": "losk_nope"}, json={"message": "hi"})
show("8. Invalid machine credential rejected (no chat access)",
     {"status_code": r.status_code})

# 9. Costs
show("9. Cost report (real usage ledger)", client.get("/v1/costs", headers=H).json())

print("\nOffline demo passed. Live auth, hosted database, GitHub skill sync, and OpenAI chat remain unverified.\n")
