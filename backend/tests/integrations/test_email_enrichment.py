from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.integrations import email_enrichment
from backend.integrations.email_enrichment import (
    _EmailIntel,
    _build_user_message,
    _load_thread_context,
    _should_enrich,
    enrich_email,
)
from db.models import EmailIntelligence, EmailMessage, User


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _seed_email(
    db,
    *,
    user_id: str,
    msg_id: str,
    hours_ago: float = 1,
    important: bool = True,
    is_sent: bool = False,
    thread_id: str | None = None,
    body: str = "hey, can you confirm pricing tier 2 by Friday?",
    subject: str = "pricing v3 thoughts",
    from_name: str | None = "Sarah Chen",
    from_address: str = "sarah@acme.com",
) -> str:
    row_id: str
    async with db() as s:
        row = EmailMessage(
            user_id=user_id,
            gmail_message_id=msg_id,
            thread_id=thread_id or f"t-{msg_id}",
            from_address=from_address,
            from_name=from_name,
            to_addresses=[],
            cc_addresses=[],
            subject=subject,
            snippet=body[:200],
            body_text=body,
            body_stored=True,
            ingest_depth="full",
            is_important=important,
            is_starred=False,
            is_sent=is_sent,
            internal_date=_now() - timedelta(hours=hours_ago),
            labels=["INBOX", "IMPORTANT"] if important else ["INBOX"],
        )
        s.add(row)
        await s.commit()
        row_id = row.id
    return row_id


async def _intel_for(db, *, user_id: str) -> EmailIntelligence | None:
    from sqlalchemy import select

    async with db() as s:
        result = await s.execute(
            select(EmailIntelligence).where(
                EmailIntelligence.user_id == user_id
            )
        )
        return result.scalar_one_or_none()


def _patch_llm(monkeypatch, *, intel: _EmailIntel | None) -> dict:
    """Replace call_structured with a recorder that returns ``intel``."""
    calls: dict = {"count": 0, "last_user_message": None}

    async def _fake_call(**kwargs):
        calls["count"] += 1
        calls["last_user_message"] = kwargs.get("user_message")
        return intel

    monkeypatch.setattr(email_enrichment, "call_structured", _fake_call)
    return calls


@pytest.mark.asyncio
async def test_should_enrich_filters_outbound_and_unimportant():
    base_kwargs = dict(
        user_id="u1",
        gmail_message_id="m1",
        thread_id="t1",
        from_address="a@b.com",
        from_name=None,
        to_addresses=[],
        cc_addresses=[],
        subject="x",
        snippet="x",
        body_text="x",
        body_stored=True,
        ingest_depth="full",
        is_starred=False,
        internal_date=_now(),
        labels=["INBOX"],
    )
    important = EmailMessage(is_important=True, is_sent=False, **base_kwargs)
    outbound = EmailMessage(is_important=True, is_sent=True, **base_kwargs)
    boring = EmailMessage(is_important=False, is_sent=False, **base_kwargs)
    assert _should_enrich(important) is True
    assert _should_enrich(outbound) is False
    assert _should_enrich(boring) is False


@pytest.mark.asyncio
async def test_enrich_skips_unimportant_email(db, monkeypatch):
    calls = _patch_llm(monkeypatch, intel=None)
    row_id = await _seed_email(db, user_id="u1", msg_id="m1", important=False)

    result = await enrich_email("u1", row_id)

    assert result is False
    assert calls["count"] == 0
    assert await _intel_for(db, user_id="u1") is None


@pytest.mark.asyncio
async def test_enrich_skips_outbound_email(db, monkeypatch):
    calls = _patch_llm(monkeypatch, intel=None)
    row_id = await _seed_email(db, user_id="u1", msg_id="m1", is_sent=True)

    result = await enrich_email("u1", row_id)

    assert result is False
    assert calls["count"] == 0


@pytest.mark.asyncio
async def test_enrich_persists_reply_needed_with_draft(db, monkeypatch):
    intel = _EmailIntel(
        classification="reply_needed",
        urgency=0.85,
        key_points=[
            "Sarah wants tier 2 dropped",
            "Friday is the deadline",
            "renewal at risk if unanswered",
        ],
        draft_text="hey sarah, looking now. friday's tight but doable.",
        draft_confidence=0.7,
        recommended_action="reply with timeline before Friday",
    )
    _patch_llm(monkeypatch, intel=intel)
    row_id = await _seed_email(db, user_id="u1", msg_id="m1")

    result = await enrich_email("u1", row_id)

    assert result is True
    row = await _intel_for(db, user_id="u1")
    assert row is not None
    assert row.classification == "reply_needed"
    assert row.urgency == pytest.approx(0.85)
    assert row.draft_text == "hey sarah, looking now. friday's tight but doable."
    assert row.draft_confidence == pytest.approx(0.7)
    assert "renewal" in " ".join(row.key_points).lower()
    assert row.sent_draft_at is None
    assert row.user_action is None


@pytest.mark.asyncio
async def test_enrich_drops_draft_for_fyi(db, monkeypatch):
    intel = _EmailIntel(
        classification="fyi",
        urgency=0.2,
        key_points=["build deploy succeeded"],
        draft_text="thanks!",
        draft_confidence=0.9,
        recommended_action=None,
    )
    _patch_llm(monkeypatch, intel=intel)
    row_id = await _seed_email(db, user_id="u1", msg_id="m1")

    assert await enrich_email("u1", row_id) is True
    row = await _intel_for(db, user_id="u1")
    assert row is not None
    assert row.classification == "fyi"
    assert row.draft_text is None
    assert row.draft_confidence is None


@pytest.mark.asyncio
async def test_enrich_keeps_draft_for_scheduling(db, monkeypatch):
    intel = _EmailIntel(
        classification="scheduling",
        urgency=0.5,
        key_points=["asks about Tuesday 3pm"],
        draft_text="tuesday 3pm works.",
        draft_confidence=0.8,
        recommended_action="confirm Tuesday 3pm",
    )
    _patch_llm(monkeypatch, intel=intel)
    row_id = await _seed_email(db, user_id="u1", msg_id="m1")

    assert await enrich_email("u1", row_id) is True
    row = await _intel_for(db, user_id="u1")
    assert row is not None
    assert row.draft_text == "tuesday 3pm works."


@pytest.mark.asyncio
async def test_enrich_idempotent_skips_existing_row(db, monkeypatch):
    intel = _EmailIntel(
        classification="reply_needed",
        urgency=0.8,
        key_points=["one"],
        draft_text="ack.",
        draft_confidence=0.6,
        recommended_action=None,
    )
    calls = _patch_llm(monkeypatch, intel=intel)
    row_id = await _seed_email(db, user_id="u1", msg_id="m1")

    assert await enrich_email("u1", row_id) is True
    assert await enrich_email("u1", row_id) is False
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_enrich_returns_false_when_llm_unavailable(db, monkeypatch):
    _patch_llm(monkeypatch, intel=None)
    row_id = await _seed_email(db, user_id="u1", msg_id="m1")

    assert await enrich_email("u1", row_id) is False
    assert await _intel_for(db, user_id="u1") is None


@pytest.mark.asyncio
async def test_enrich_returns_false_for_missing_row(db, monkeypatch):
    _patch_llm(monkeypatch, intel=None)
    assert await enrich_email("u1", "nonexistent-id") is False


@pytest.mark.asyncio
async def test_enrich_returns_false_for_wrong_user(db, monkeypatch):
    _patch_llm(monkeypatch, intel=None)
    row_id = await _seed_email(db, user_id="u1", msg_id="m1")
    assert await enrich_email("u2", row_id) is False


@pytest.mark.asyncio
async def test_load_thread_context_orders_oldest_first(db):
    thread_id = "t-shared"
    await _seed_email(
        db,
        user_id="u1",
        msg_id="m-old",
        hours_ago=10,
        thread_id=thread_id,
        body="original ask",
    )
    await _seed_email(
        db,
        user_id="u1",
        msg_id="m-mid",
        hours_ago=5,
        thread_id=thread_id,
        body="middle reply",
    )
    head_id = await _seed_email(
        db,
        user_id="u1",
        msg_id="m-head",
        hours_ago=0.5,
        thread_id=thread_id,
        body="latest message",
    )

    async with db() as session:
        thread = await _load_thread_context(
            session, user_id="u1", thread_id=thread_id, exclude_id=head_id
        )

    assert [m.gmail_message_id for m in thread] == ["m-old", "m-mid"]


@pytest.mark.asyncio
async def test_build_user_message_includes_user_profile_and_thread(db):
    async with db() as session:
        user = await session.get(User, "u1")
        user.name = "Bharat"
        user.living_profile = {"narrative": "founder, ships fast, lowercase voice"}
        await session.commit()
        # Re-fetch a detached snapshot for the helper.
        user_row = await session.get(User, "u1")

    thread_id = "t-mix"
    await _seed_email(
        db,
        user_id="u1",
        msg_id="m-prior",
        hours_ago=24,
        thread_id=thread_id,
        body="initial ping from sarah",
    )
    target_id = await _seed_email(
        db,
        user_id="u1",
        msg_id="m-target",
        hours_ago=1,
        thread_id=thread_id,
        body="follow up please",
    )

    async with db() as session:
        target = await session.get(EmailMessage, target_id)
        thread = await _load_thread_context(
            session, user_id="u1", thread_id=thread_id, exclude_id=target_id
        )

    prompt = _build_user_message(target=target, thread=thread, user=user_row)
    assert "founder, ships fast" in prompt
    assert "follow up please" in prompt
    assert "initial ping from sarah" in prompt
    assert "earlier thread context" in prompt


@pytest.mark.asyncio
async def test_enrich_passes_thread_context_to_llm(db, monkeypatch):
    intel = _EmailIntel(
        classification="reply_needed",
        urgency=0.7,
        key_points=["confirm timeline"],
        draft_text="on it.",
        draft_confidence=0.8,
        recommended_action=None,
    )
    calls = _patch_llm(monkeypatch, intel=intel)

    thread_id = "t-ctx"
    await _seed_email(
        db,
        user_id="u1",
        msg_id="m-prior",
        hours_ago=4,
        thread_id=thread_id,
        body="we should sync on pricing this week",
    )
    target_id = await _seed_email(
        db,
        user_id="u1",
        msg_id="m-target",
        hours_ago=1,
        thread_id=thread_id,
        body="any update on the pricing question?",
    )

    assert await enrich_email("u1", target_id) is True
    sent = calls["last_user_message"]
    assert "any update on the pricing question?" in sent
    assert "we should sync on pricing this week" in sent
