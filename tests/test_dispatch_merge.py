"""Tests for the per-phone cancel-and-restart dispatcher in api.main.

Locks in the merge behaviour for rapid-fire messages: two messages that
arrive within the settle window must reach the brain as a single merged
payload, not as two separate turns.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from api import main as api_main
from ingress.payload import IngressPayload


def _text_payload(phone: str, body: str, wa_id: str) -> IngressPayload:
    return IngressPayload(
        user_id="",
        phone=phone,
        message=body,
        message_type="text",
        source="whatsapp",
        platform_message_id=wa_id,
    )


@pytest.fixture(autouse=True)
def _reset_dispatcher_state() -> None:
    api_main._active_tasks.clear()
    api_main._pending_items.clear()
    api_main._sending_phase.clear()
    api_main._phone_locks.clear()


@pytest.mark.asyncio
async def test_two_rapid_messages_reach_brain_merged(monkeypatch: pytest.MonkeyPatch) -> None:
    """M1 and M2 arriving 50 ms apart must hit the brain as one merged turn.

    Without the settle window, a fast-completing pipeline can race past the
    cancel point and run M2 as a fresh turn. The test installs a brain stub
    that records each invocation's raw_input and asserts the merged form ran
    exactly once.
    """
    seen_inputs: list[str] = []

    async def _fake_user_lookup(state: dict[str, Any]) -> dict[str, Any]:
        return {**state, "user_id": "u-test"}

    async def _fake_enrich(state: dict[str, Any]) -> dict[str, Any]:
        return state

    async def _fake_brain(state: dict[str, Any]) -> dict[str, Any]:
        seen_inputs.append(state.get("raw_input") or "")
        return {**state, "_outbound": []}

    async def _noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def _noop_send_many(*_args: Any, **_kwargs: Any) -> list[str]:
        return []

    monkeypatch.setattr(api_main, "user_lookup", _fake_user_lookup)
    monkeypatch.setattr(api_main, "enrich_state", _fake_enrich)
    monkeypatch.setattr(api_main, "donna_turn", _fake_brain)
    monkeypatch.setattr(api_main, "_save_user_message", _noop)
    monkeypatch.setattr(api_main, "_save_assistant_message", _noop)
    monkeypatch.setattr(api_main, "_backfill_assistant_wamid", _noop)
    monkeypatch.setattr(api_main, "mark_processed", _noop)
    monkeypatch.setattr(api_main, "mark_failed", _noop)
    monkeypatch.setattr(api_main._wa, "send_many", _noop_send_many)

    phone = "+15550001"
    await api_main._dispatch(_text_payload(phone, "hi", "wa-1"), None)
    await asyncio.sleep(0.05)
    await api_main._dispatch(_text_payload(phone, "did you see my note?", "wa-2"), None)

    task = api_main._active_tasks.get(phone)
    assert task is not None
    await task

    assert seen_inputs == ["hi\ndid you see my note?"], seen_inputs


@pytest.mark.asyncio
async def test_message_after_send_phase_starts_new_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Once a turn is in send phase, a new message starts a fresh turn —
    we do not cancel mid-send. This is the boundary the settle window
    deliberately does NOT cross."""
    seen_inputs: list[str] = []

    async def _fake_user_lookup(state: dict[str, Any]) -> dict[str, Any]:
        return {**state, "user_id": "u-test"}

    async def _fake_enrich(state: dict[str, Any]) -> dict[str, Any]:
        return state

    async def _fake_brain(state: dict[str, Any]) -> dict[str, Any]:
        seen_inputs.append(state.get("raw_input") or "")
        return {**state, "_outbound": []}

    async def _noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def _noop_send_many(*_args: Any, **_kwargs: Any) -> list[str]:
        return []

    monkeypatch.setattr(api_main, "user_lookup", _fake_user_lookup)
    monkeypatch.setattr(api_main, "enrich_state", _fake_enrich)
    monkeypatch.setattr(api_main, "donna_turn", _fake_brain)
    monkeypatch.setattr(api_main, "_save_user_message", _noop)
    monkeypatch.setattr(api_main, "_save_assistant_message", _noop)
    monkeypatch.setattr(api_main, "_backfill_assistant_wamid", _noop)
    monkeypatch.setattr(api_main, "mark_processed", _noop)
    monkeypatch.setattr(api_main, "mark_failed", _noop)
    monkeypatch.setattr(api_main._wa, "send_many", _noop_send_many)

    phone = "+15550002"
    await api_main._dispatch(_text_payload(phone, "first", "wa-3"), None)
    first = api_main._active_tasks.get(phone)
    assert first is not None
    await first

    await api_main._dispatch(_text_payload(phone, "second", "wa-4"), None)
    second = api_main._active_tasks.get(phone)
    assert second is not None
    await second

    assert seen_inputs == ["first", "second"], seen_inputs
