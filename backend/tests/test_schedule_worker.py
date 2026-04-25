"""Unit tests for the reminder schedule worker.

These tests cover the pure helpers that decide what gets persisted to
``chat_messages`` after a reminder fires. The full ``run_once`` polling loop
is integration-tested elsewhere — here we only verify the seam that turns
sent OutboundMessage objects into ChatMessage rows.
"""
from __future__ import annotations

from backend.memory.jobs.schedule_worker import fired_reminder_chat_rows
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
