"""Dispatcher Tier 3 real LLM call — Phase 2A.

After Phase 2A, every escalation runs both legacy donna_turn AND a
counterfactual donna_turn(mode='proactive_tier3'). The Tier 3 outcome
is captured to telemetry. Legacy ship reaches the user; Tier 3 is
mirror-only.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import select

from db.models import ProactiveDispatchTelemetry
from proactive.dispatcher import _escalate_to_brain
from proactive.events import ProactiveEvent
from proactive.judge import JudgeResult


def _event() -> ProactiveEvent:
    return ProactiveEvent(
        user_id="u1",
        source="email",
        source_ref="msg_real_call",
        topic_key="thread_real_call",
        speech_act="heads_up",
        payload={
            "from_address": "x@y.com",
            "subject": "phase 2a",
            "body_excerpt": "...",
            "phone": "+1",
        },
        signals={"score": 0.7, "event_age_minutes": 30},
    )


def _judge() -> JudgeResult:
    return JudgeResult(
        action="ping",
        register="alert",
        draft="luca replied to the term sheet",
        tie_in=(),
        needs_tools=True,
        reasoning="thread state may have moved",
        raw_response="{}",
    )


@pytest.mark.asyncio
async def test_tier3_real_call_telemetry_captures_skip_outcome(db):
    """When the model calls skip(), telemetry captures outcome=skip."""
    legacy_calls: list[str] = []
    counterfactual_calls: list[str] = []

    async def fake_donna_turn(state, cfg):
        if cfg.mode == "proactive":
            legacy_calls.append("legacy")
            return {"_outbound": [{"type": "text", "body": "legacy draft"}]}
        if cfg.mode == "proactive_tier3":
            counterfactual_calls.append("tier3")
            # Simulate the model calling skip()
            return {
                "_outbound": [],
                "_tier3_outcome": {
                    "action": "skip",
                    "reason": "user already replied in chat",
                },
            }
        return {"_outbound": []}

    async def fake_record_ping(*args, **kwargs):
        return None

    with patch(
        "donna_runtime.brain.donna_turn",
        side_effect=fake_donna_turn,
    ), patch(
        "backend.integrations.proactive_rate_limit.record_ping",
        side_effect=fake_record_ping,
    ):
        outcome = await _escalate_to_brain(
            event=_event(),
            judge=_judge(),
        )

    assert "legacy" in legacy_calls
    assert "tier3" in counterfactual_calls

    async with db() as session:
        rows = (
            await session.execute(
                select(ProactiveDispatchTelemetry).where(
                    ProactiveDispatchTelemetry.topic_key == "thread_real_call"
                )
            )
        ).scalars().all()

    assert len(rows) == 1
    row = rows[0]
    assert row.counterfactual_fat_contract_outcome == "skip"
    assert row.counterfactual_fat_contract_skip_reason == "user already replied in chat"
    assert row.counterfactual_legacy_outbound_count == 1


@pytest.mark.asyncio
async def test_tier3_real_call_telemetry_captures_ship_outcome(db):
    """When the model calls send_burst(), telemetry captures outcome=ship + draft."""
    async def fake_donna_turn(state, cfg):
        if cfg.mode == "proactive_tier3":
            return {
                "_outbound": [],
                "_tier3_outcome": {
                    "action": "ship",
                    "messages": [
                        {"type": "text", "body": "luca replied to the term sheet thread"}
                    ],
                    "push": True,
                    "surface_at": None,
                },
            }
        return {"_outbound": [{"type": "text", "body": "legacy"}]}

    async def fake_record_ping(*a, **kw):
        return None

    with patch(
        "donna_runtime.brain.donna_turn",
        side_effect=fake_donna_turn,
    ), patch(
        "backend.integrations.proactive_rate_limit.record_ping",
        side_effect=fake_record_ping,
    ):
        await _escalate_to_brain(event=_event(), judge=_judge())

    async with db() as session:
        rows = (
            await session.execute(
                select(ProactiveDispatchTelemetry).where(
                    ProactiveDispatchTelemetry.topic_key == "thread_real_call"
                )
            )
        ).scalars().all()

    assert len(rows) == 1
    row = rows[0]
    assert row.counterfactual_fat_contract_outcome == "ship"
    assert "luca replied" in (row.counterfactual_fat_contract_draft or "")


@pytest.mark.asyncio
async def test_tier3_real_call_legacy_unchanged_when_tier3_errors(db):
    """If the Tier 3 call raises, the legacy outcome still ships."""
    async def fake_donna_turn(state, cfg):
        if cfg.mode == "proactive_tier3":
            raise RuntimeError("simulated Tier 3 SDK failure")
        return {"_outbound": [{"type": "text", "body": "legacy"}]}

    async def fake_record_ping(*a, **kw):
        return None

    with patch(
        "donna_runtime.brain.donna_turn",
        side_effect=fake_donna_turn,
    ), patch(
        "backend.integrations.proactive_rate_limit.record_ping",
        side_effect=fake_record_ping,
    ):
        outcome = await _escalate_to_brain(event=_event(), judge=_judge())

    # Legacy outbound count > 0 → legacy reached the user
    assert outcome.action in {"escalated", "shipped"}

    async with db() as session:
        rows = (
            await session.execute(
                select(ProactiveDispatchTelemetry).where(
                    ProactiveDispatchTelemetry.topic_key == "thread_real_call"
                )
            )
        ).scalars().all()

    assert len(rows) == 1
    row = rows[0]
    assert row.counterfactual_fat_contract_outcome == "error"
    assert "RuntimeError" in (row.counterfactual_fat_contract_error or "")
