from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select

from backend.integrations.composio_client import NormalizedGmailMessage
from db.models import User


def _msg(mid: str) -> NormalizedGmailMessage:
    return NormalizedGmailMessage(
        gmail_message_id=mid,
        thread_id=f"t-{mid}",
        from_address="sarah@acme.com",
        from_name="Sarah",
        to_addresses=["you@y.com"],
        cc_addresses=[],
        subject=f"re: term sheet ({mid})",
        snippet="...",
        body_text="lots of body text " * 30,
        labels=["INBOX", "PRIMARY", "IMPORTANT"],
        is_important=True,
        is_starred=False,
        is_sent=False,
        internal_date=datetime(2026, 4, 24),
    )


@pytest.mark.asyncio
async def test_synthesize_biography_writes_living_profile(db, monkeypatch):
    async with db() as s:
        u = (await s.execute(select(User).where(User.id == "u1"))).scalar_one()
        u.living_profile = {}
        await s.commit()

    fake_responses = iter([
        '{"relationships":[{"name":"Sarah","kind":"colleague","frequency":"weekly"}]}',
        '{"work":{"employer":"Acme","role":"founder"}}',
        '{"interests":["VC","fundraising"]}',
        '{"rhythms":{"work_hours":"9-7"}}',
        '{"overview":"founder fundraising at Acme; close ties to Sarah."}',
    ])

    async def fake_llm(prompt: str, model: str = "sonnet") -> str:
        return next(fake_responses)

    monkeypatch.setattr(
        "backend.integrations.biography_synthesis._call_llm", fake_llm
    )

    from backend.integrations.biography_synthesis import synthesize_biography

    biography = await synthesize_biography(
        user_id="u1",
        full_messages=[_msg("m1"), _msg("m2")],
        sender_aggregates=[
            {
                "from_address": "sarah@acme.com",
                "count": 10,
                "sample_subjects": ["term sheet"],
            },
        ],
    )

    assert biography["overview"].startswith("founder")
    assert biography["work"]["employer"] == "Acme"
    assert biography["relationships"][0]["name"] == "Sarah"

    async with db() as s:
        user = (
            await s.execute(select(User).where(User.id == "u1"))
        ).scalar_one()
    assert user.living_profile["biography"]["overview"].startswith("founder")
