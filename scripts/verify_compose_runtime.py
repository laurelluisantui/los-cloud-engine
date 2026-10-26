"""Disposable CI smoke test, run inside the API container (not production)."""
import json
import secrets
import time
from urllib.request import Request, urlopen

from engine.auth import get_org_id, hash_key
from engine.db import SessionLocal, scope_session
from engine.models import ApiKey


def get(url, key):
    with urlopen(Request(url, headers={"X-Engine-Key": key}), timeout=10) as r:
        return json.load(r)


def main():
    s = SessionLocal()
    raw = "losk_" + secrets.token_urlsafe(24)
    try:
        org_id = get_org_id(s)
        s.rollback()
        scope_session(s, org_id)
        s.add(ApiKey(organization_id=org_id, name="ci-smoke",
                     key_hash=hash_key(raw), scopes=["task.create", "task.read"]))
        s.commit()
    finally:
        s.close()

    base = "http://localhost:8000/v1/tasks"
    payload = {
        "agent_slug": "content-agent",
        "input": {"business_name": "Example Studio", "website": "https://example.com"},
    }
    with urlopen(Request(
        base, data=json.dumps(payload).encode(),
        headers={"X-Engine-Key": raw, "Content-Type": "application/json"},
        method="POST",
    ), timeout=10) as r:
        assert r.status == 201
        task_id = json.load(r)["task_id"]

    for _ in range(60):
        status = get(f"{base}/{task_id}", raw)
        if status["status"] in ("succeeded", "failed"):
            break
        time.sleep(1)
    else:
        raise AssertionError("worker did not finish within 60 seconds")
    assert status["status"] == "succeeded", status
    assert status["runs"][0]["skill_version"] == "0.1.0"
    result = get(f"{base}/{task_id}/result", raw)
    assert result["output"]["draft"].startswith("Content brief")
    assert get("http://localhost:8000/v1/runs", raw)["runs"][0]["task_id"] == task_id
    print("Compose verified: authenticated API -> Postgres queue -> worker -> saved result/history")


if __name__ == "__main__":
    main()
