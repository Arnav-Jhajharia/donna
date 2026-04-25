"""Pure-function tests for inbound gmail importance scoring."""
from __future__ import annotations

from datetime import datetime

import pytest

from backend.integrations.composio_client import NormalizedGmailMessage
from backend.integrations.email_importance import ScoringContext, score_email


def _msg(**kwargs) -> NormalizedGmailMessage:
    base = dict(
        gmail_message_id="m1",
        thread_id="t1",
        from_address="x@y.com",
        from_name=None,
        to_addresses=[],
        cc_addresses=[],
        subject="hi",
        snippet="hi",
        body_text=None,
        labels=["INBOX", "PRIMARY"],
        is_important=False,
        is_starred=False,
        is_sent=False,
        internal_date=datetime(2026, 4, 25),
    )
    base.update(kwargs)
    return NormalizedGmailMessage(**base)


def _ctx(**kwargs) -> ScoringContext:
    base = dict(
        biography_relationships=[],
        open_loop_keywords=[],
        recent_sent_thread_ids=set(),
    )
    base.update(kwargs)
    return ScoringContext(**base)


def test_unmarked_message_is_low():
    s = score_email(_msg(), _ctx())
    assert s.score < 0.5
    assert s.signals == []


def test_important_label_above_threshold():
    s = score_email(_msg(is_important=True), _ctx())
    assert s.score >= 0.5
    assert "important_label" in s.signals


def test_starred_above_threshold():
    s = score_email(_msg(is_starred=True), _ctx())
    assert s.score >= 0.5
    assert "starred" in s.signals


def test_known_relationship_weekly_above_threshold():
    s = score_email(
        _msg(from_address="sarah@acme.com"),
        _ctx(
            biography_relationships=[
                {
                    "name": "Sarah",
                    "frequency": "weekly",
                    "kind": "colleague",
                    "_email": "sarah@acme.com",
                }
            ]
        ),
    )
    assert s.score >= 0.5
    assert "biography_relationship" in s.signals


def test_open_loop_keyword_match():
    s = score_email(
        _msg(subject="re: term sheet draft"),
        _ctx(open_loop_keywords=["term sheet"]),
    )
    assert s.score >= 0.5
    assert "open_loop_match" in s.signals


def test_reply_on_recent_thread():
    s = score_email(
        _msg(thread_id="t-recent"),
        _ctx(recent_sent_thread_ids={"t-recent"}),
    )
    # by itself recent-thread is weaker than threshold; combining lifts
    assert "recent_sent_thread" in s.signals


def test_signals_compose():
    s = score_email(
        _msg(is_important=True, thread_id="t-recent"),
        _ctx(recent_sent_thread_ids={"t-recent"}),
    )
    assert s.score >= 0.6
    assert "important_label" in s.signals
    assert "recent_sent_thread" in s.signals
