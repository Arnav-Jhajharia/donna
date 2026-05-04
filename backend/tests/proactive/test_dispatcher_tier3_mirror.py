"""Dispatcher counterfactual logging — mirror-mode Phase 1.

Tests that _escalate_to_brain writes a proactive_dispatch_telemetry
row after each legacy escalation, capturing what Tier 3's input
contract WOULD have looked like.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

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
        source_ref="msg_x",
        topic_key="thread_x",
        speech_act="heads_up",
        payload={
            "from_address": "x@y.com",
            "subject": "hi",
            "body_excerpt": "...",
            "phone": "+1",
        },
        signals={"score": 0.7, "event_age_minutes": 30},
    )


def _judge() -> JudgeResult:
    return JudgeResult(
        action="ping",
        register="alert",
        draft="x replied",
        tie_in=(),
        needs_tools=True,
        reasoning="thread state may have moved",
        raw_response="{}",
    )


@pytest.mark.asyncio
async def test_counterfactual_logs_telemetry_after_legacy_escalation(db):
    """The legacy path runs unchanged. After it completes, the counterfactual
    builds the Tier 3 input contract and writes a telemetry row."""

    # Stub donna_turn so the legacy path produces a mock outbound list
    # (mirror mode behavior). The counterfactual does NOT call donna_turn
    # in Phase 1 — it only builds the input contract.
    async def fake_donna_turn(state, cfg):
        return {"_outbound": [{"type": "text", "body": "legacy draft"}]}

    # Patch record_ping so we don't need the rate-limit infra
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

    assert outcome.action in {"escalated", "shipped", "errored"}

    # Telemetry row written
    async with db() as session:
        rows = (
            await session.execute(
                select(ProactiveDispatchTelemetry).where(
                    ProactiveDispatchTelemetry.topic_key == "thread_x"
                )
            )
        ).scalars().all()

    assert len(rows) == 1, f"expected one telemetry row, got {len(rows)}"
    row = rows[0]
    assert row.user_id == "u1"
    assert row.source == "email"
    assert row.speech_act == "heads_up"
    assert row.tier3_invoked is True
    # Phase 1: outcome is one of input_built / input_failed
    assert row.counterfactual_fat_contract_outcome in {
        "input_built", "input_failed"
    }
    assert row.counterfactual_fat_contract_elapsed_ms is not None
    assert row.counterfactual_fat_contract_elapsed_ms >= 0
