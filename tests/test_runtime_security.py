"""The public fetcher never follows redirects to private hosts or proxies."""
import socket

import httpx
import pytest

from engine import runtime


def _dns(host, port):
    ips = {"public.example": "93.184.215.14", "internal.example": "127.0.0.1"}
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ips[host], port))]


def test_private_host_rejected_before_network(monkeypatch):
    monkeypatch.setattr(runtime.socket, "getaddrinfo", _dns)
    with pytest.raises(ValueError, match="private"):
        runtime.bounded_fetch("http://internal.example/")


def test_redirect_to_private_host_is_rejected(monkeypatch):
    monkeypatch.setattr(runtime.socket, "getaddrinfo", _dns)
    hits = []
    transport = httpx.MockTransport(
        lambda request: (hits.append(str(request.url)) or
                         httpx.Response(302, headers={"Location": "http://internal.example/admin"}))
    )
    client_type = httpx.Client
    monkeypatch.setattr(runtime.httpx, "Client",
                        lambda **kwargs: client_type(transport=transport, **kwargs))
    with pytest.raises(ValueError, match="private"):
        runtime.bounded_fetch("https://public.example")
    assert len(hits) == 1


def test_oversized_page_rejected(monkeypatch):
    monkeypatch.setattr(runtime.socket, "getaddrinfo", _dns)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"x" * (runtime._MAX_BYTES + 1))
    )
    client_type = httpx.Client
    monkeypatch.setattr(runtime.httpx, "Client",
                        lambda **kwargs: client_type(transport=transport, **kwargs))
    with pytest.raises(ValueError, match="size limit"):
        runtime.bounded_fetch("https://public.example")


def test_non_http_and_embedded_credentials_rejected():
    with pytest.raises(ValueError, match="http"):
        runtime._check_public_url("file:///etc/passwd")
    with pytest.raises(ValueError, match="credentials"):
        runtime._check_public_url("https://a:b@public.example")
