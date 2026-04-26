"""ProactiveEvent envelope + email source adapter."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from proactive.events import ProactiveEvent, make_event_from_email
from proactive.sources.email import make_event


def _msg(**kw):
    base = dict(
        gmail_message_id="m1",
        thread_id="t1",
        from_address="luca@antler.co",
        from_name="Luca",
        subject="thursday or friday?",
        snippet="want to lock in dd call",
        body_text="hey, can we lock in thursday 4pm or friday morning",
        is_important=True,
        is_starred=False,
        is_sent=False,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _score(score=0.7, signals=("biography_relationship",)):
    return SimpleNamespace(score=score, signals=list(signals))


def test_make_event_from_email_uses_thread_id_as_topic_key():
    event = make_event_from_email("u1", _msg(), _score())
    assert isinstance(event, ProactiveEvent)
    assert event.user_id == "u1"
    assert event.source == "email"
    assert event.source_ref == "m1"
    assert event.topic_key == "t1"
    assert event.payload["from_address"] == "luca@antler.co"
    assert event.payload["from_name"] == "Luca"
    assert event.payload["subject"] == "thursday or friday?"
    assert event.signals["score"] == pytest.approx(0.7)
    assert event.signals["signals"] == ["biography_relationship"]


def test_make_event_falls_back_to_message_id_when_thread_missing():
    event = make_event_from_email(
        "u1", _msg(thread_id=""), _score()
    )
    assert event.topic_key == "m1"


def test_make_event_truncates_body_excerpt():
    long_body = "x" * 5000
    event = make_event_from_email("u1", _msg(body_text=long_body), _score())
    assert len(event.payload["body_excerpt"]) == 600


def test_make_event_uses_snippet_when_body_text_absent():
    event = make_event_from_email(
        "u1", _msg(body_text=None, snippet="snippet only"), _score()
    )
    assert event.payload["body_excerpt"] == "snippet only"


def test_email_source_make_event_is_thin_shim():
    event_a = make_event("u1", _msg(), _score())
    event_b = make_event_from_email("u1", _msg(), _score())
    assert event_a == event_b


def test_event_is_frozen():
    event = make_event_from_email("u1", _msg(), _score())
    with pytest.raises(Exception):
        event.user_id = "u2"  # type: ignore[misc]


@pytest.mark.asyncio
async def test_fetch_recent_sent_thread_ids_returns_empty_when_none(db):
    from proactive.sources.email import fetch_recent_sent_thread_ids

    result = await fetch_recent_sent_thread_ids("u1")
    assert result == set()


@pytest.mark.asyncio
async def test_fetch_recent_sent_thread_ids_filters_by_user_and_sent(db):
    from db.models import EmailMessage
    from proactive.sources.email import fetch_recent_sent_thread_ids

    async with db() as s:
        s.add(
            EmailMessage(
                user_id="u1",
                gmail_message_id="m_sent",
                thread_id="t_sent",
                from_address="me@x.com",
                to_addresses=[],
                cc_addresses=[],
                labels=[],
                is_sent=True,
                ingest_depth="full",
                internal_date=datetime(2026, 4, 25),
            )
        )
        s.add(
            EmailMessage(
                user_id="u1",
                gmail_message_id="m_recv",
                thread_id="t_recv",
                from_address="them@x.com",
                to_addresses=[],
                cc_addresses=[],
                labels=[],
                is_sent=False,
                ingest_depth="full",
                internal_date=datetime(2026, 4, 25),
            )
        )
        s.add(
            EmailMessage(
                user_id="u2",
                gmail_message_id="m_other",
                thread_id="t_other",
                from_address="you@x.com",
                to_addresses=[],
                cc_addresses=[],
                labels=[],
                is_sent=True,
                ingest_depth="full",
                internal_date=datetime(2026, 4, 25),
            )
        )
        await s.commit()

    result = await fetch_recent_sent_thread_ids("u1")
    assert result == {"t_sent"}
