import httpx
import pytest
from fastapi import HTTPException

from engine import auth, config


def test_supabase_jwt_requires_owner_role(monkeypatch):
    monkeypatch.setattr(config, "SUPABASE_URL", "https://auth.example")
    monkeypatch.setattr(config, "SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")
    monkeypatch.setattr(config, "SUPABASE_SERVICE_ROLE_KEY", "sb_secret_test")
    seen = []

    def respond(request):
        seen.append(request)
        if request.url.path == "/auth/v1/user":
            assert request.headers["authorization"] == "Bearer jwt-owner"
            return httpx.Response(200, json={"id": "owner-1", "email": "owner@example.com"})
        assert request.headers["apikey"] == "sb_secret_test"
        assert "authorization" not in request.headers
        return httpx.Response(200, json=[{"role": "owner"}])

    client_type = httpx.Client
    monkeypatch.setattr(auth.httpx, "Client",
                        lambda **kwargs: client_type(
                            transport=httpx.MockTransport(respond), **kwargs))
    assert auth.verify_supabase_token("jwt-owner")["id"] == "owner-1"
    assert len(seen) == 2


def test_supabase_non_owner_denied(monkeypatch):
    monkeypatch.setattr(config, "SUPABASE_URL", "https://auth.example")
    monkeypatch.setattr(config, "SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")
    monkeypatch.setattr(config, "SUPABASE_SERVICE_ROLE_KEY", "sb_secret_test")

    def respond(request):
        if request.url.path == "/auth/v1/user":
            return httpx.Response(200, json={"id": "client-1"})
        return httpx.Response(200, json=[])

    client_type = httpx.Client
    monkeypatch.setattr(auth.httpx, "Client",
                        lambda **kwargs: client_type(
                            transport=httpx.MockTransport(respond), **kwargs))
    with pytest.raises(HTTPException) as error:
        auth.verify_supabase_token("jwt-client")
    assert error.value.status_code == 403
