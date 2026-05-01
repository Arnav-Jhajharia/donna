"""Unit tests for the open_loops → attentions dual-write helpers.

Phase 1a of the open_loops → attentions consolidation. The mirror
helpers must be best-effort (never raise) and must produce a payload
that downstream readers (Phase 1c) can match back to the legacy
``open_loops`` row via ``mirror_open_loop_id``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.memory.tools._open_loop_mirror import (
    _build_payload,
    mirror_close_open_loop,
    mirror_create_open_loop,
)


def test_build_payload_basic_shape():
    payload = _build_payload(
        open_loop_id="ol-1",
        content="call mom about thanksgiving",
        source_message="msg-abc",
        due_at=None,
    )
    assert payload["spec"]["card"] == "open_loop"
    assert payload["spec"]["subject"]["name"] == "call mom about thanksgiving"
    assert payload["spec"]["subject"]["type"] == "open_loop_thread"
    assert payload["spec"]["rationale"] == "call mom about thanksgiving"
    assert payload["spec"]["due_at"] is None
    assert payload["mirror_source"] == "open_loops"
    assert payload["mirror_open_loop_id"] == "ol-1"
    assert payload["source_message"] == "msg-abc"


def test_build_payload_truncates_long_content_for_title_only():
    long = "a" * 200
    payload = _build_payload(
        open_loop_id="ol-2", content=long, source_message=None, due_at=None,
    )
    # title (subject.name) caps at 80 chars; rationale keeps the full body.
    assert len(payload["spec"]["subject"]["name"]) == 80
    assert payload["spec"]["rationale"] == long


def test_build_payload_serialises_due_at():
    due = datetime(2026, 6, 1, 14, 30, tzinfo=timezone.utc)
    payload = _build_payload(
        open_loop_id="ol-3", content="ship deck", source_message=None, due_at=due,
    )
    assert payload["spec"]["due_at"] == due.isoformat()


@pytest.mark.asyncio
async def test_mirror_create_returns_attention_id_on_success(monkeypatch):
    captured: dict = {}

    class _StubAttentionRow:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.id = "attn-mirror-1"

    monkeypatch.setattr(
        "backend.db.models.AttentionRow", _StubAttentionRow
    )

    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    aid = await mirror_create_open_loop(
        session,
        user_id="u1",
        open_loop_id="ol-1",
        content="ship deck by friday",
        source_message="msg-1",
        due_at=None,
    )

    assert aid == "attn-mirror-1"
    assert captured["user_id"] == "u1"
    assert captured["card"] == "open_loop"
    assert captured["status"] == "live"
    assert captured["origin"] == "user_explicit"
    assert captured["payload"]["mirror_open_loop_id"] == "ol-1"
    session.add.assert_called_once()
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_mirror_create_swallows_exceptions(monkeypatch):
    """Best-effort contract: never raise, return None on failure."""
    def _raise(*_a, **_kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "backend.db.models.AttentionRow", _raise
    )

    session = MagicMock()
    session.add = MagicMock()

    aid = await mirror_create_open_loop(
        session,
        user_id="u1",
        open_loop_id="ol-1",
        content="x",
        source_message=None,
        due_at=None,
    )
    assert aid is None


@pytest.mark.asyncio
async def test_mirror_close_returns_false_when_no_match(monkeypatch):
    """No matching mirror row returns False, doesn't raise."""
    class _NoMatchResult:
        def scalar_one_or_none(self):
            return None

    session = MagicMock()
    session.execute = AsyncMock(return_value=_NoMatchResult())

    ok = await mirror_close_open_loop(
        session, user_id="u1", open_loop_id="ol-missing"
    )
    assert ok is False


@pytest.mark.asyncio
async def test_mirror_close_swallows_exceptions():
    """Best-effort contract: never raise, return False on failure."""
    session = MagicMock()
    session.execute = AsyncMock(side_effect=RuntimeError("boom"))

    ok = await mirror_close_open_loop(
        session, user_id="u1", open_loop_id="ol-1"
    )
    assert ok is False
