from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from backend.integrations.composio_client import NormalizedGmailMessage
from db.models import EmailMessage


@pytest.fixture(autouse=True)
def _stub_proactive(monkeypatch):
    """Default-stub the proactive trigger so bootstrap tests don't bleed
    into the brain. Mirrors test_gmail_ingest.py's autouse fixture."""

    async def _noop(*_a, **_kw):
        return None

    monkeypatch.setattr(
        "backend.integrations.gmail_ingest.maybe_surface_email",
        _noop,
        raising=False,
    )


@pytest.fixture
def fake_client(monkeypatch):
    class Fake:
        def __init__(self):
            self.messages: list[NormalizedGmailMessage] = []
            self.list_calls: list[tuple[str, str]] = []

        async def list_gmail_message_ids(
            self, user_id, query="", max_results=100, page_token=None
        ):
            self.list_calls.append((user_id, query))
            return [m.gmail_message_id for m in self.messages], None

        async def fetch_gmail_message(
            self, user_id, message_id, include_body=True
        ):
            for m in self.messages:
                if m.gmail_message_id == message_id:
                    return m
            raise KeyError(message_id)

    fake = Fake()
    monkeypatch.setattr(
        "backend.integrations.bootstrap_gmail._client",
        lambda: fake,
    )
    return fake


def _msg(
    mid: str,
    hours_ago: int,
    labels: tuple[str, ...] = ("INBOX", "PRIMARY"),
) -> NormalizedGmailMessage:
    return NormalizedGmailMessage(
        gmail_message_id=mid,
        thread_id=f"t-{mid}",
        from_address="a@b.com",
        from_name=None,
        to_addresses=[],
        cc_addresses=[],
        subject=f"s-{mid}",
        snippet="x",
        body_text="body",
        labels=list(labels),
        is_important=False,
        is_starred=False,
        is_sent="SENT" in labels,
        internal_date=(
            datetime.now(timezone.utc).replace(tzinfo=None)
            - timedelta(hours=hours_ago)
        ),
    )


@pytest.mark.asyncio
async def test_bootstrap_today_dense_ingests_today(db, fake_client):
    from backend.integrations.bootstrap_gmail import bootstrap_today_dense

    fake_client.messages = [
        _msg("m_today", hours_ago=2),
        _msg("m_yesterday", hours_ago=30),
    ]

    await bootstrap_today_dense("u1")

    async with db() as s:
        rows = (
            await s.execute(
                select(EmailMessage).where(EmailMessage.user_id == "u1")
            )
        ).scalars().all()
    ids = {r.gmail_message_id for r in rows}
    assert "m_today" in ids


@pytest.mark.asyncio
async def test_bootstrap_today_dense_classifies_with_label_router(db, fake_client):
    from backend.integrations.bootstrap_gmail import bootstrap_today_dense

    fake_client.messages = [
        _msg("m_primary", 1, labels=("INBOX", "PRIMARY")),
        _msg("m_promo", 1, labels=("INBOX", "PROMOTIONS")),
        _msg("m_spam", 1, labels=("SPAM",)),
    ]

    await bootstrap_today_dense("u1")

    async with db() as s:
        rows = (
            await s.execute(
                select(EmailMessage).where(EmailMessage.user_id == "u1")
            )
        ).scalars().all()
    ids = {r.gmail_message_id for r in rows}
    assert "m_primary" in ids
    assert "m_promo" not in ids
    assert "m_spam" not in ids


@pytest.mark.asyncio
async def test_bootstrap_today_dense_uses_newer_than_1d_query(db, fake_client):
    from backend.integrations.bootstrap_gmail import bootstrap_today_dense

    await bootstrap_today_dense("u1")

    assert fake_client.list_calls == [("u1", "newer_than:1d")]
