"""Tests for the compatibility auth-status endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient


@pytest.fixture()
def client(tmp_db, monkeypatch):
    from worker_backend import main

    monkeypatch.setattr(main.browser_mgr, "cleanup_stale", AsyncMock())
    monkeypatch.setattr(main.browser_mgr, "cleanup_all", AsyncMock())
    monkeypatch.setattr(main.browser_mgr.vnc, "cleanup_stale", AsyncMock())

    with TestClient(main.app) as client:
        yield client


def test_profiles_accessible_without_token(client: TestClient):
    resp = client.get("/api/profiles")
    assert resp.status_code == 200


def test_auth_status_reports_open_api(client: TestClient):
    resp = client.get("/api/auth/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["auth_required"] is False
    assert data["authenticated"] is True


def test_healthcheck_accessible(client: TestClient):
    resp = client.get("/api/status")
    assert resp.status_code == 200


def test_login_endpoint_removed(client: TestClient):
    assert client.post("/api/auth/login", json={"token": "anything"}).status_code in {404, 405}
    assert client.post("/api/auth/logout").status_code in {404, 405}
