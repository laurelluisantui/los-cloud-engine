"""Content skill proposal changes real output only after owner approval."""
from engine.db import SessionLocal
from engine.models import Task, TaskRun
from engine.worker import process_one


def test_content_skill_edit_review_publish_and_delegate(client, owner_headers, seeded):
    current = client.get("/v1/skills/content-brief-drafting", headers=owner_headers).json()
    assert current["version"] == "0.1.0"
    assert "format: paragraph" in current["body"]
    changed = current["body"].replace(
        "version: 0.1.0", "version: 0.2.0"
    ).replace("format: paragraph", "format: bullets")

    response = client.post(
        "/v1/skills/content-brief-drafting/propose", headers=owner_headers,
        json={"new_version": "0.2.0", "body": changed, "reason": "scannable briefs"}
    )
    assert response.status_code == 202, response.text
    proposal = response.json()
    assert proposal["sample_output"]["draft"].startswith("Content brief")
    assert proposal["proposed_sample_output"]["draft"].startswith("- Content brief")
    assert client.get("/v1/skills/content-brief-drafting", headers=owner_headers).json()["version"] == "0.1.0"

    approval = proposal["approval_id"]
    response = client.post(
        f"/v1/approvals/{approval}/decide",
        headers=owner_headers, json={"approve": True},
    )
    assert response.status_code == 200, response.text
    assert client.get("/v1/skills/content-brief-drafting", headers=owner_headers).json()["version"] == "0.2.0"

    response = client.post("/v1/tasks", headers=owner_headers, json={
        "agent_slug": "content-agent", "input": {
            "business_name": "Example Studio", "website": "https://example.com",
            "topic": "A new service"
        }
    })
    assert response.status_code == 201, response.text
    task_id = response.json()["task_id"]
    session = SessionLocal()
    process_one(session, session.query(Task).filter_by(id=task_id).one())
    run = session.query(TaskRun).filter_by(task_id=task_id).one()
    assert run.status == "succeeded"
    assert run.skill_version == "0.2.0"
    assert run.output["draft"].startswith("- Content brief")
    session.close()


def test_cannot_publish_mismatched_skill_metadata(client, owner_headers, seeded):
    current = client.get("/v1/skills/content-brief-drafting", headers=owner_headers).json()
    response = client.post("/v1/skills/content-brief-drafting/propose", headers=owner_headers,
                           json={"new_version": "0.2.0", "body": current["body"]})
    assert response.status_code == 400
