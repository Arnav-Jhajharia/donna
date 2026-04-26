"""POST /api/dashboard/{user_id}/action endpoint tests.

Direct calls into ``execute_action`` so we don't need a TestClient or
the full FastAPI app boot. Handler logic is monkey-patched — the
endpoint contract is what we're verifying here, not the underlying
attention pipeline.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from api import dashboard_routes as routes
from backend.dashboard.actions import AcceptResult


@pytest.mark.asyncio
async def test_accept_attention_invokes_handler_and_returns_payload(monkeypatch):
    captured: dict[str, str] = {}

    async def fake_accept(*, user_id, attention_id):
        captured["user_id"] = user_id
        captured["attention_id"] = attention_id
        return AcceptResult(
            ok=True,
            attention_id=attention_id,
            status="live",
            instance_id="inst-7",
            instance_created=True,
            recomposed="scheduled",
        )

    monkeypatch.setattr(routes, "accept_offered_attention", fake_accept)

    request = routes.ActionRequest(
        action={"v": "accept_attention", "attentionId": "attn-1"}
    )
    response = await routes.execute_action(user_id="user-1", request=request)

    import json
    body = json.loads(response.body)
    assert response.status_code == 200
    assert body["ok"] is True
    assert body["attention_id"] == "attn-1"
    assert body["status"] == "live"
    assert body["instance_id"] == "inst-7"
    assert body["instance_created"] is True
    assert body["recomposed"] == "scheduled"
    assert captured == {"user_id": "user-1", "attention_id": "attn-1"}


@pytest.mark.asyncio
async def test_accept_attention_failure_returns_409(monkeypatch):
    async def fake_accept(*, user_id, attention_id):
        return AcceptResult(
            ok=False,
            attention_id=attention_id,
            error="attention is not OFFERED",
        )

    monkeypatch.setattr(routes, "accept_offered_attention", fake_accept)
    request = routes.ActionRequest(
        action={"v": "accept_attention", "attentionId": "attn-2"}
    )
    response = await routes.execute_action(user_id="user-1", request=request)
    import json
    body = json.loads(response.body)
    assert response.status_code == 409
    assert body["ok"] is False
    assert body["error"] == "attention is not OFFERED"


@pytest.mark.asyncio
async def test_dismiss_attention_invokes_handler(monkeypatch):
    captured: dict[str, str] = {}

    async def fake_dismiss(*, user_id, attention_id):
        captured["user_id"] = user_id
        captured["attention_id"] = attention_id
        return True

    monkeypatch.setattr(routes, "dismiss_offered_attention", fake_dismiss)
    request = routes.ActionRequest(
        action={"v": "dismiss_attention", "attentionId": "attn-3"}
    )
    response = await routes.execute_action(user_id="user-1", request=request)

    import json
    body = json.loads(response.body)
    assert response.status_code == 200
    assert body["ok"] is True
    assert body["attention_id"] == "attn-3"
    assert captured == {"user_id": "user-1", "attention_id": "attn-3"}


@pytest.mark.asyncio
async def test_mark_reminder_done_invokes_handler(monkeypatch):
    captured: dict[str, str] = {}

    async def fake_mark(*, user_id, reminder_id):
        captured["user_id"] = user_id
        captured["reminder_id"] = reminder_id
        return True, None

    monkeypatch.setattr(routes, "mark_reminder_done", fake_mark)
    request = routes.ActionRequest(
        action={"v": "mark_reminder_done", "reminderId": "rem-9"}
    )
    response = await routes.execute_action(user_id="user-1", request=request)

    import json
    body = json.loads(response.body)
    assert response.status_code == 200
    assert body["ok"] is True
    assert body["reminder_id"] == "rem-9"
    assert captured == {"user_id": "user-1", "reminder_id": "rem-9"}


@pytest.mark.asyncio
async def test_mark_reminder_done_failure_returns_409(monkeypatch):
    async def fake_mark(*, user_id, reminder_id):
        return False, "reminder not found"

    monkeypatch.setattr(routes, "mark_reminder_done", fake_mark)
    request = routes.ActionRequest(
        action={"v": "mark_reminder_done", "reminderId": "rem-x"}
    )
    response = await routes.execute_action(user_id="user-1", request=request)
    import json
    body = json.loads(response.body)
    assert response.status_code == 409
    assert body["ok"] is False
    assert body["error"] == "reminder not found"


@pytest.mark.asyncio
async def test_mark_reminder_done_missing_id_returns_400():
    request = routes.ActionRequest(action={"v": "mark_reminder_done"})
    with pytest.raises(HTTPException) as exc:
        await routes.execute_action(user_id="user-1", request=request)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_unknown_verb_returns_501(monkeypatch):
    request = routes.ActionRequest(action={"v": "log_value", "tracker": "x", "value": 1})
    with pytest.raises(HTTPException) as exc:
        await routes.execute_action(user_id="user-1", request=request)
    assert exc.value.status_code == 501


@pytest.mark.asyncio
async def test_missing_v_returns_400(monkeypatch):
    request = routes.ActionRequest(action={"attentionId": "x"})
    with pytest.raises(HTTPException) as exc:
        await routes.execute_action(user_id="user-1", request=request)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_accept_without_attention_id_returns_400():
    request = routes.ActionRequest(action={"v": "accept_attention"})
    with pytest.raises(HTTPException) as exc:
        await routes.execute_action(user_id="user-1", request=request)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_accept_accepts_snake_case_attention_id_too(monkeypatch):
    """Forgiveness: the TS contract uses ``attentionId`` but we tolerate
    the snake_case spelling too so internal callers (tests, scripts)
    don't have to remember to camelCase-encode."""
    captured: dict[str, str] = {}

    async def fake_accept(*, user_id, attention_id):
        captured["attention_id"] = attention_id
        return AcceptResult(ok=True, attention_id=attention_id, status="live")

    monkeypatch.setattr(routes, "accept_offered_attention", fake_accept)
    request = routes.ActionRequest(
        action={"v": "accept_attention", "attention_id": "attn-snake"}
    )
    response = await routes.execute_action(user_id="user-1", request=request)
    assert response.status_code == 200
    assert captured["attention_id"] == "attn-snake"
