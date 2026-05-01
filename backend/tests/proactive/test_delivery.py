"""Tests for delivery.deliver_drafts."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.web.proactive.delivery import deliver_drafts
from backend.web.proactive.judge import JudgeVerdict
from backend.web.proactive.types import ProactiveMove, ProactiveResult
from db.models import ChatMessage, User
from db.session import async_session


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest_asyncio.fixture
async def fresh_user() -> str:
    """Insert a throwaway user for delivery tests; clean up after.

    Mirrors the engine-rebind pattern from test_store / test_subscriptions:
    the module-level engine was created on a different event loop, so we
    dispose it here so the asyncpg pool binds to the current test loop.
    """
    import db.session as _session_mod

    await _session_mod._engine.dispose()

    suffix = uuid.uuid4().hex[:8]
    user_id = f"u_test_delivery_{suffix}"
    phone = f"+1999{suffix[:7]}"

    async with async_session() as session:
        u = User(
            id=user_id,
            phone=phone,
            name="delivery test",
            timezone="UTC",
            living_profile={},
            created_at=_utcnow_naive(),
        )
        session.add(u)
        await session.commit()
    yield user_id
    async with async_session() as session:
        await session.execute(
            ChatMessage.__table__.delete().where(ChatMessage.user_id == user_id)
        )
        await session.execute(
            User.__table__.delete().where(User.id == user_id)
        )
        await session.commit()


def _send_verdict(draft: str) -> tuple[ProactiveResult, JudgeVerdict]:
    move = ProactiveMove(
        rationale="r",
        tool="search",
        query="q",
        dedup_key="dk",
    )
    result = ProactiveResult(move=move, status="ok", payload={"results": [{}]})
    verdict = JudgeVerdict(decision="send", draft=draft)
    return (result, verdict)


@pytest.mark.asyncio
async def test_shadow_mode_writes_chat_message_with_is_shadow_true(fresh_user):
    pair = _send_verdict("draft text")
    sent = await deliver_drafts(
        user_id=fresh_user,
        verdicts=[pair],
        mode="shadow",
    )
    assert sent == 1

    async with async_session() as session:
        rows = (
            await session.execute(
                select(ChatMessage).where(ChatMessage.user_id == fresh_user)
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].is_shadow is True
    assert rows[0].is_proactive is True
    assert rows[0].role == "assistant"
    assert rows[0].content == "draft text"


@pytest.mark.asyncio
async def test_silence_verdicts_are_not_delivered(fresh_user):
    move = ProactiveMove(
        rationale="r", tool="search", query="q", dedup_key="dk"
    )
    result = ProactiveResult(move=move, status="ok", payload={"results": [{}]})
    silenced = (result, JudgeVerdict(decision="silence", reason="meh"))
    sent = await deliver_drafts(
        user_id=fresh_user, verdicts=[silenced], mode="shadow"
    )
    assert sent == 0


@pytest.mark.asyncio
async def test_live_mode_writes_chat_message_with_is_shadow_false(
    fresh_user, monkeypatch
):
    """Live mode also dispatches WhatsApp; we mock the channel."""
    from backend.web.proactive import delivery as d

    sent_to: list[tuple[str, list[str]]] = []

    class FakeChannel:
        async def send_many(self, phone, messages):
            sent_to.append((phone, list(messages)))

    monkeypatch.setattr(d, "_get_whatsapp_channel", lambda: FakeChannel())

    pair = _send_verdict("live draft")
    sent = await deliver_drafts(
        user_id=fresh_user, verdicts=[pair], mode="live"
    )
    assert sent == 1
    assert sent_to and sent_to[0][1] == ["live draft"]

    async with async_session() as session:
        rows = (
            await session.execute(
                select(ChatMessage).where(ChatMessage.user_id == fresh_user)
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].is_shadow is False
