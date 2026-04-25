"""Score → rate-limit → brain orchestration for inbound gmail."""
from __future__ import annotations

from datetime import datetime

import pytest

from backend.integrations.composio_client import NormalizedGmailMessage


def _msg(**kw):
    base = dict(
        gmail_message_id="m1",
        thread_id="t1",
        from_address="sarah@acme.com",
        from_name="Sarah",
        to_addresses=[],
        cc_addresses=[],
        subject="re: term sheet",
        snippet="...",
        body_text="body",
        labels=["INBOX", "PRIMARY", "IMPORTANT"],
        is_important=True,
        is_starred=False,
        is_sent=False,
        internal_date=datetime(2026, 4, 25),
    )
    base.update(kw)
    return NormalizedGmailMessage(**base)


def _make_decision(allowed: bool, reason: str = "ok"):
    from backend.integrations.proactive_rate_limit import FireDecision

    async def _f(user_id, source, now=None):  # noqa: ANN001
        return FireDecision(allowed=allowed, reason=reason)

    return _f


async def _async_noop(*a, **kw):
    return None


@pytest.mark.asyncio
async def test_low_score_does_not_invoke_brain(db, monkeypatch):
    from backend.integrations import proactive_email_trigger as trg

    invoked = {"count": 0}

    async def fake_brain(state, config=None):
        invoked["count"] += 1
        return state

    monkeypatch.setattr(trg, "_invoke_brain", fake_brain)
    monkeypatch.setattr(trg, "can_fire_proactive", _make_decision(allowed=True))

    await trg.maybe_surface_email("u1", _msg(is_important=False, is_starred=False))
    assert invoked["count"] == 0


@pytest.mark.asyncio
async def test_high_score_invokes_brain_in_proactive_mode(db, monkeypatch):
    from backend.integrations import proactive_email_trigger as trg

    invoked = {}

    async def fake_brain(state, config=None):
        invoked["state"] = state
        invoked["mode"] = config.mode if config else None
        return state

    monkeypatch.setattr(trg, "_invoke_brain", fake_brain)
    monkeypatch.setattr(trg, "can_fire_proactive", _make_decision(allowed=True))
    monkeypatch.setattr(trg, "record_ping", _async_noop)

    await trg.maybe_surface_email("u1", _msg())
    assert invoked["mode"] == "proactive"
    assert "term sheet" in invoked["state"]["user_message"].lower()


@pytest.mark.asyncio
async def test_rate_limited_records_suppression(db, monkeypatch):
    from backend.integrations import proactive_email_trigger as trg

    monkeypatch.setattr(trg, "_invoke_brain", _async_noop)
    monkeypatch.setattr(
        trg, "can_fire_proactive", _make_decision(allowed=False, reason="cooldown:120s")
    )

    captured = {}

    async def fake_record(user_id, source, message_ref, at=None, suppressed_reason=None):
        captured["suppressed_reason"] = suppressed_reason

    monkeypatch.setattr(trg, "record_ping", fake_record)

    await trg.maybe_surface_email("u1", _msg())
    assert captured["suppressed_reason"] == "cooldown:120s"
