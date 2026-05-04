"""Tests for the timestamped RECENT CHAT formatter.

The model uses these timestamps for rhythm and affect inference at turn
time. Format must be stable, fall back gracefully when timezone is
absent, and flag proactive Donna messages distinctly.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from donna_runtime.context_builder import _format_recent_chat_line


def _row(*, role: str, content: str, when: datetime, is_proactive: bool = False):
    return SimpleNamespace(
        role=role,
        content=content,
        created_at=when,
        is_proactive=is_proactive,
    )


def test_format_includes_local_timestamp_when_tz_set():
    when = datetime(2026, 4, 26, 8, 30, tzinfo=timezone.utc)
    row = _row(role="user", content="hey donna", when=when)
    line = _format_recent_chat_line(row, "Asia/Singapore")
    # Asia/Singapore is UTC+8 → 16:30 local
    assert line.startswith("- [")
    assert "16:30" in line
    assert "user: hey donna" in line


def test_format_handles_missing_timezone_gracefully():
    when = datetime(2026, 4, 26, 8, 30, tzinfo=timezone.utc)
    row = _row(role="assistant", content="on it", when=when)
    line = _format_recent_chat_line(row, None)
    # Falls back without raising; content still rendered.
    assert "assistant: on it" in line


def test_format_marks_proactive_assistant_messages():
    when = datetime(2026, 4, 26, 7, 45, tzinfo=timezone.utc)
    row = _row(
        role="assistant",
        content="morning. design review at 14:00.",
        when=when,
        is_proactive=True,
    )
    line = _format_recent_chat_line(row, "UTC")
    # `*` suffix on the role lets the model see this was a Donna nudge,
    # not a reply to the user — useful when reading rhythm.
    assert "assistant*:" in line


def test_format_truncates_long_content():
    when = datetime(2026, 4, 26, 7, 45, tzinfo=timezone.utc)
    row = _row(role="user", content="x" * 1000, when=when)
    line = _format_recent_chat_line(row, "UTC")
    # Fix 3 bumped _MAX_CHAT_CHARS from 180 → 240 (and added a
    # 800-char fulltext window for the most recent two messages,
    # protected separately). Total line stays bounded under 320.
    assert len(line) < 320


def test_format_handles_missing_created_at():
    row = _row(role="user", content="ping", when=None)
    line = _format_recent_chat_line(row, "UTC")
    # Falls back to "?" placeholder rather than raising.
    assert "[?]" in line
    assert "user: ping" in line
