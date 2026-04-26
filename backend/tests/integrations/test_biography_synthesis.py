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


# --- fence-stripping ------------------------------------------------------


def test_strip_json_fences_handles_markdown_block():
    """Sonnet 4.6 sometimes wraps responses in ```json ... ```. The
    parser must tolerate that — otherwise every biography pass returns
    {} and synthesis never lands."""
    from backend.integrations.biography_synthesis import _strip_json_fences

    raw = '```json\n{"name": "Sarah"}\n```'
    assert _strip_json_fences(raw) == '{"name": "Sarah"}'


def test_strip_json_fences_handles_bare_fences():
    from backend.integrations.biography_synthesis import _strip_json_fences

    raw = '```\n[1, 2, 3]\n```'
    assert _strip_json_fences(raw) == "[1, 2, 3]"


def test_strip_json_fences_isolates_json_from_prose():
    """Even when the model adds 'Here is the JSON:' before/after, the
    stripper extracts the first balanced object."""
    from backend.integrations.biography_synthesis import _strip_json_fences

    raw = 'Sure! Here is the JSON:\n{"key": "value"}\nLet me know if you need more.'
    assert _strip_json_fences(raw) == '{"key": "value"}'


def test_strip_json_fences_passes_clean_json_through():
    from backend.integrations.biography_synthesis import _strip_json_fences

    raw = '{"clean": true}'
    assert _strip_json_fences(raw) == '{"clean": true}'


def test_strip_json_fences_handles_empty_string():
    from backend.integrations.biography_synthesis import _strip_json_fences
    assert _strip_json_fences("") == ""
    assert _strip_json_fences("   \n  ") == ""
