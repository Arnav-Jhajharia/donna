"""Tests for the /api/exa/monitor_callback endpoint."""
from __future__ import annotations

import hashlib
import hmac
import json
import os

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture(autouse=True)
def _enable_secret(monkeypatch):
    monkeypatch.setenv("EXA_WEBHOOK_SECRET", "test_secret_xyz")


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_webhook_rejects_missing_signature():
    client = TestClient(app)
    res = client.post(
        "/api/exa/monitor_callback",
        json={"monitorId": "mon_x"},
    )
    assert res.status_code == 401


def test_webhook_rejects_bad_signature():
    client = TestClient(app)
    body = json.dumps({"monitorId": "mon_x"}).encode()
    res = client.post(
        "/api/exa/monitor_callback",
        content=body,
        headers={
            "x-exa-signature": "deadbeef",
            "content-type": "application/json",
        },
    )
    assert res.status_code == 401


def test_webhook_accepts_valid_signature(monkeypatch):
    body = json.dumps({"monitorId": "mon_unknown", "items": []}).encode()
    sig = _sign(body, "test_secret_xyz")

    async def fake_record(payload):
        assert payload.get("monitorId") == "mon_unknown"
        return 0

    from api import exa_webhook as ew
    monkeypatch.setattr(ew, "record_monitor_hit", fake_record)

    client = TestClient(app)
    res = client.post(
        "/api/exa/monitor_callback",
        content=body,
        headers={
            "x-exa-signature": sig,
            "content-type": "application/json",
        },
    )
    assert res.status_code == 200
    assert res.json() == {"recorded": 0}
