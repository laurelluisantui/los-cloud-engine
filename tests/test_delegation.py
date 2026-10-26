"""End-to-end task delegation: API -> queue -> worker -> skill -> DB records."""
import time
import json

from engine.db import SessionLocal
from engine.models import Task
from engine.worker import process_one
from tests.conftest import fake_fetch


def test_delegate_and_execute_sales_research(client, owner_headers, seeded):
    r = client.post("/v1/tasks", headers=owner_headers, json={
        "agent_slug": "sales-research",
        "input": {"business_name": "Bluebonnet Dental",
                  "website": "https://bluebonnetdental.example"},
    })
    assert r.status_code == 201, r.text
    task_id = r.json()["task_id"]

    # Worker picks it up and runs the skill with a stubbed fetch.
    session = SessionLocal()
    task = session.query(Task).filter_by(id=task_id).one()
    process_one(session, task, fetch=fake_fetch())
    session.close()

    r = client.get(f"/v1/tasks/{task_id}", headers=owner_headers)
    body = r.json()
    assert body["status"] == "succeeded"
    assert len(body["runs"]) == 1
    assert body["runs"][0]["status"] == "succeeded"
    assert body["runs"][0]["skill_version"] == "pipeline-v1"

    r = client.get("/v1/runs", headers=owner_headers)
    assert any(run["task_id"] == task_id for run in r.json()["runs"])


def test_output_is_evidence_based(client, owner_headers, seeded):
    r = client.post("/v1/tasks", headers=owner_headers, json={
        "agent_slug": "sales-research",
        "input": {"business_name": "Bluebonnet Dental",
                  "website": "https://bluebonnetdental.example"},
    })
    task_id = r.json()["task_id"]
    session = SessionLocal()
    process_one(session, session.query(Task).filter_by(id=task_id).one(),
                fetch=fake_fetch())
    from engine.models import TaskRun
    run = session.query(TaskRun).filter_by(task_id=task_id).one()
    session.close()
    findings = run.output["research"]["findings"]
    assert findings, "expected findings"
    assert run.output["website_audit"]["checks"]
    assert "DRAFT" in run.output["proposal"]["proposal_markdown"]
    assert run.output["proposal"]["based_on_findings"] >= 1
    assert run.output["human_review_required"] is True
    assert set(run.output["skill_versions"]) == {
        "prospect-research", "prospect-website-audit", "proposal-drafting"
    }
    for f in findings:
        assert f["claim"] and f["source_excerpt"] and f["evidence_url"]
        # provenance: excerpt must come from the page we fetched
        assert "Bluebonnet" in f["source_excerpt"] or "dent" in f["source_excerpt"].lower()


def test_machine_can_submit_and_read_status(client, machine_headers, seeded):
    r = client.post("/v1/tasks", headers=machine_headers, json={
        "agent_slug": "sales-research",
        "input": {"business_name": "Bluebonnet Dental", "website": "https://x.example"},
    })
    assert r.status_code == 201
    task_id = r.json()["task_id"]
    session = SessionLocal()
    process_one(session, session.query(Task).filter_by(id=task_id).one(),
                fetch=fake_fetch())
    session.close()
    assert client.get(f"/v1/tasks/{task_id}", headers=machine_headers).json()["status"] == "succeeded"


def test_explicit_skill_executes_only_that_skill(client, owner_headers, seeded):
    r = client.post("/v1/tasks", headers=owner_headers, json={
        "agent_slug": "sales-research",
        "skill_slug": "prospect-website-audit",
        "input": {"website": "https://bluebonnetdental.example"},
    })
    assert r.status_code == 201
    session = SessionLocal()
    from engine.models import TaskRun
    process_one(session, session.query(Task).filter_by(id=r.json()["task_id"]).one(),
                fetch=fake_fetch())
    run = session.query(TaskRun).filter_by(task_id=r.json()["task_id"]).one()
    assert run.skill_version == "0.1.0"
    assert "checks" in run.output
    session.close()


def test_sales_pipeline_records_model_usage(client, owner_headers, seeded, monkeypatch):
    from engine import providers
    from engine.models import TaskRun, UsageCost

    class FakeProvider:
        name = "openai"

        def complete(self, instructions, input_text, **kwargs):
            if "evidence-based findings" in instructions:
                result = {"findings": [
                    {"claim": "Business name appears", "excerpt": "Bluebonnet Dental"}
                ], "notes": []}
            else:
                result = {"proposal_markdown": (
                    "# Draft\nBluebonnet Dental appears on the site [finding 1]. "
                    "Price: [PRICE TBD]."
                )}
            return providers.ProviderResult(
                text=json.dumps(result), tokens_in=120, tokens_out=40,
                model="gpt-5.4-mini", provider="openai",
            )

    monkeypatch.setattr(providers, "get_provider", lambda: FakeProvider())
    response = client.post("/v1/tasks", headers=owner_headers, json={
        "agent_slug": "sales-research", "input": {
            "business_name": "Bluebonnet Dental",
            "website": "https://bluebonnetdental.example",
        }
    })
    session = SessionLocal()
    task_id = response.json()["task_id"]
    process_one(session, session.query(Task).filter_by(id=task_id).one(),
                fetch=fake_fetch())
    run = session.query(TaskRun).filter_by(task_id=task_id).one()
    costs = session.query(UsageCost).filter_by(task_run_id=run.id).all()
    assert run.status == "succeeded"
    assert run.tokens_in == 240 and run.tokens_out == 80
    assert run.cost_usd > 0
    assert len(costs) == 2
    session.close()


def test_agent_cannot_use_unlisted_skill(client, owner_headers, seeded):
    r = client.post("/v1/tasks", headers=owner_headers, json={
        "agent_slug": "sales-research", "skill_slug": "nonexistent-skill",
        "input": {"business_name": "x", "website": "https://x.example"}})
    assert r.status_code in (400, 403)


def test_unknown_agent_404(client, owner_headers, seeded):
    r = client.post("/v1/tasks", headers=owner_headers,
                    json={"agent_slug": "ghost", "input": {}})
    assert r.status_code == 404
