"""Unit tests for the reminder schedule worker.

These tests cover the pure helpers that decide what gets persisted to
``chat_messages`` after a reminder fires. The full ``run_once`` polling loop
is integration-tested elsewhere — here we only verify the seam that turns
sent OutboundMessage objects into ChatMessage rows, plus the Fix 9
fallback helper that floors user-requested fires when the brain returns
empty outbound.
"""
from __future__ import annotations

from backend.memory.jobs.schedule_worker import (
    _build_fallback_outbound,
    fired_reminder_chat_rows,
)
from delivery.messages import (
    Button,
    CTAMessage,
    Delay,
    TextMessage,
)


def test_fired_reminder_persists_text_message() -> None:
    rows = fired_reminder_chat_rows(
        user_id="u-1",
        sent_messages=[TextMessage(body="time for vitamins")],
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == "u-1"
    assert row.role == "assistant"
    assert row.content == "time for vitamins"
    assert row.is_proactive is True


def test_fired_reminder_renders_cta_with_button_labels() -> None:
    msg = CTAMessage(
        body="ready to start?",
        buttons=[Button(id="yes", title="yes"), Button(id="no", title="not yet")],
    )

    rows = fired_reminder_chat_rows(user_id="u-2", sent_messages=[msg])

    assert len(rows) == 1
    assert rows[0].content == "ready to start?\n[buttons: yes | not yet]"
    assert rows[0].is_proactive is True


def test_fired_reminder_skips_delays_and_unrenderable() -> None:
    rows = fired_reminder_chat_rows(
        user_id="u-3",
        sent_messages=[Delay(seconds=1.0), TextMessage(body="hey")],
    )

    assert len(rows) == 1
    assert rows[0].content == "hey"


def test_fired_reminder_handles_empty_input() -> None:
    assert fired_reminder_chat_rows(user_id="u-4", sent_messages=[]) == []


def test_fired_reminder_skips_empty_text_body() -> None:
    rows = fired_reminder_chat_rows(
        user_id="u-5",
        sent_messages=[TextMessage(body="")],
    )

    assert rows == []


# Fix 9 — silent-drop floor. When the brain returns empty outbound for a
# user-requested fire, the worker falls back to the deterministic context
# body so the user always receives the reminder they asked for. CLAUDE.md:
# "a reminder that doesn't fire is not a bug, it's a betrayal."


def test_fallback_builds_text_message_from_context() -> None:
    """A schedule row's context.messages array becomes OutboundMessages."""
    context = {"messages": [{"type": "text", "body": "drink water"}]}
    out = _build_fallback_outbound(context)

    assert len(out) == 1
    assert isinstance(out[0], TextMessage)
    assert out[0].body == "drink water"


def test_fallback_handles_multiple_messages() -> None:
    context = {
        "messages": [
            {"type": "text", "body": "first ping"},
            {"type": "text", "body": "second ping"},
        ]
    }
    out = _build_fallback_outbound(context)

    assert [m.body for m in out] == ["first ping", "second ping"]


def test_fallback_returns_empty_when_no_context() -> None:
    """No context — caller must treat as silent-drop alert class, not fall
    through with a generic 'reminder' string. Better honest empty than
    misleading filler."""
    assert _build_fallback_outbound(None) == []
    assert _build_fallback_outbound({}) == []
    assert _build_fallback_outbound({"messages": None}) == []
    assert _build_fallback_outbound({"messages": []}) == []


def test_fallback_returns_empty_when_messages_unrenderable() -> None:
    """If every message in context fails to render (e.g. empty bodies),
    return empty so the caller can flag the silent-drop class. The
    underlying ``_build_outbound`` filters empty text — we want that
    filtering to surface here, not be papered over with placeholder
    content. Better honest empty than misleading filler."""
    context = {"messages": [{"type": "text", "body": ""}]}
    out = _build_fallback_outbound(context)

    assert out == []


def test_fallback_ignores_non_dict_context() -> None:
    """Defensive — context column on DonnaSchedule is JSONB but defensive
    callers should not crash if it's anything weird."""
    assert _build_fallback_outbound([]) == []  # type: ignore[arg-type]
    assert _build_fallback_outbound("oops") == []  # type: ignore[arg-type]
