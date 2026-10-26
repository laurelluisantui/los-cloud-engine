import base64
import json

import httpx

from engine import config, skills_lib


def _candidate(body):
    return body.replace("version: 0.1.0", "version: 0.2.0").replace(
        "format: paragraph", "format: bullets"
    )


def test_live_skill_commit_requires_approval_and_matches_github(
    client, owner_headers, seeded, monkeypatch
):
    current = client.get("/v1/skills/content-brief-drafting", headers=owner_headers).json()
    events = []

    def response(req):
        if req.method == "PUT":
            events.append("PUT")
            payload = json.loads(req.content)
            assert payload["sha"] == "oldsha"
            assert "format: bullets" in base64.b64decode(payload["content"]).decode()
            assert req.headers["authorization"] == "Bearer test-token"
            return httpx.Response(200, json={"commit": {"sha": "newcommit"}})
        events.append("GET")
        return httpx.Response(200, json={
            "sha": "oldsha",
            "content": base64.b64encode(current["body"].encode()).decode(),
        })

    client_type = httpx.Client
    monkeypatch.setattr(skills_lib.httpx, "Client",
                        lambda **kw: client_type(transport=httpx.MockTransport(response), **kw))
    monkeypatch.setattr(config, "REQUIRE_GITHUB_SYNC", True)
    monkeypatch.setattr(config, "GITHUB_TOKEN", "test-token")
    proposed = client.post(
        "/v1/skills/content-brief-drafting/propose", headers=owner_headers,
        json={"new_version": "0.2.0", "body": _candidate(current["body"])}
    ).json()
    assert events == []  # no GitHub write before approval
    decided = client.post(
        f"/v1/approvals/{proposed['approval_id']}/decide", headers=owner_headers,
        json={"approve": True}
    )
    assert decided.status_code == 200, decided.text
    assert events == ["GET", "PUT"]
    assert client.get("/v1/skills/content-brief-drafting",
                      headers=owner_headers).json()["version"] == "0.2.0"


def test_live_skill_rejects_remote_conflict(client, owner_headers, seeded, monkeypatch):
    current = client.get("/v1/skills/content-brief-drafting", headers=owner_headers).json()
    client_type = httpx.Client
    monkeypatch.setattr(skills_lib.httpx, "Client",
                        lambda **kw: client_type(
                            transport=httpx.MockTransport(
                                lambda req: httpx.Response(200, json={
                                    "sha": "other-edit",
                                    "content": base64.b64encode(b"Someone else's edit").decode(),
                                })
                            ), **kw))
    monkeypatch.setattr(config, "REQUIRE_GITHUB_SYNC", True)
    monkeypatch.setattr(config, "GITHUB_TOKEN", "test-token")
    proposed = client.post(
        "/v1/skills/content-brief-drafting/propose", headers=owner_headers,
        json={"new_version": "0.2.0", "body": _candidate(current["body"])}
    ).json()
    decided = client.post(
        f"/v1/approvals/{proposed['approval_id']}/decide", headers=owner_headers,
        json={"approve": True}
    )
    assert decided.status_code == 500
    assert client.get("/v1/skills/content-brief-drafting",
                      headers=owner_headers).json()["version"] == "0.1.0"
