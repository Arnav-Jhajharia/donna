from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.integrations.signals import (
    gmail_signal_line,
    render_integrations_signals_block,
)
from db.models import EmailMessage


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _seed_email(
    db,
    *,
    user_id: str,
    msg_id: str,
    hours_ago: float,
    important: bool,
    is_sent: bool = False,
    from_address: str = "sarah@acme.com",
    from_name: str | None = "Sarah Chen",
    subject: str | None = "pricing v3 thoughts",
) -> None:
    async with db() as s:
        s.add(
            EmailMessage(
                user_id=user_id,
                gmail_message_id=msg_id,
                thread_id=f"t-{msg_id}",
                from_address=from_address,
                from_name=from_name,
                to_addresses=[],
                cc_addresses=[],
                subject=subject,
                snippet="snippet",
                ingest_depth="full",
                is_important=important,
                is_starred=False,
                is_sent=is_sent,
                body_stored=False,
                internal_date=_now() - timedelta(hours=hours_ago),
                labels=["INBOX", "IMPORTANT"] if important else ["INBOX"],
            )
        )
        await s.commit()


@pytest.mark.asyncio
async def test_gmail_signal_line_returns_none_when_no_important_mail(db):
    await _seed_email(db, user_id="u1", msg_id="m1", hours_ago=2, important=False)
    assert await gmail_signal_line("u1") is None


@pytest.mark.asyncio
async def test_gmail_signal_line_summarizes_important_mail(db):
    await _seed_email(db, user_id="u1", msg_id="m1", hours_ago=2, important=True)
    await _seed_email(
        db,
        user_id="u1",
        msg_id="m2",
        hours_ago=10,
        important=True,
        from_name=None,
        from_address="andrew@beta.io",
        subject="follow up",
    )
    line = await gmail_signal_line("u1")
    assert line is not None
    assert line.startswith("gmail: 2 important unread (24h)")
    # Newest message wins as the "top".
    assert "Sarah Chen" in line
    assert '"pricing v3 thoughts"' in line
    assert "2h ago" in line


@pytest.mark.asyncio
async def test_gmail_signal_line_excludes_outside_window(db):
    await _seed_email(db, user_id="u1", msg_id="m1", hours_ago=48, important=True)
    assert await gmail_signal_line("u1") is None


@pytest.mark.asyncio
async def test_gmail_signal_line_excludes_sent_mail(db):
    await _seed_email(
        db, user_id="u1", msg_id="m1", hours_ago=2, important=True, is_sent=True
    )
    assert await gmail_signal_line("u1") is None


@pytest.mark.asyncio
async def test_gmail_signal_line_isolates_per_user(db):
    await _seed_email(db, user_id="u1", msg_id="m1", hours_ago=2, important=True)
    assert await gmail_signal_line("u2") is None


@pytest.mark.asyncio
async def test_gmail_signal_line_falls_back_to_sender_local_part(db):
    await _seed_email(
        db,
        user_id="u1",
        msg_id="m1",
        hours_ago=1,
        important=True,
        from_name=None,
        from_address="ops@vendor.io",
        subject="invoice ready",
    )
    line = await gmail_signal_line("u1")
    assert line is not None
    assert "top: ops " in line or 'top: ops "' in line


@pytest.mark.asyncio
async def test_render_block_empty_when_no_signals(db):
    assert await render_integrations_signals_block("u1") == ""


@pytest.mark.asyncio
async def test_render_block_prefixes_signals(db):
    await _seed_email(db, user_id="u1", msg_id="m1", hours_ago=1, important=True)
    block = await render_integrations_signals_block("u1")
    assert block.startswith("[INTEGRATIONS SIGNALS]\n  gmail: 1 important unread")


@pytest.mark.asyncio
async def test_render_block_returns_empty_for_blank_user_id():
    assert await render_integrations_signals_block("") == ""
