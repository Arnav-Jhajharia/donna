"""ProactiveDispatchTelemetry — schema + insertability."""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select

from db.models import ProactiveDispatchTelemetry, generate_uuid


@pytest.mark.asyncio
async def test_telemetry_row_can_be_inserted(db):
    async with db() as session:
        row = ProactiveDispatchTelemetry(
            id=generate_uuid(),
            user_id="u1",
            source="email",
            speech_act="heads_up",
            topic_key="thread_xyz",
            tier1_score=0.75,
            arbiter_decision="allowed",
            tier2_action="ping",
            tier2_draft="luca replied to the term sheet thread",
            tier3_invoked=True,
            tier3_outcome="ship",
            channel="whatsapp",
            counterfactual_legacy_outbound_count=1,
            counterfactual_fat_contract_outcome="ship",
            event_at=datetime.utcnow(),
        )
        session.add(row)
        await session.commit()

        fetched = (
            await session.execute(
                select(ProactiveDispatchTelemetry).where(
                    ProactiveDispatchTelemetry.id == row.id
                )
            )
        ).scalar_one()
        assert fetched.speech_act == "heads_up"
        assert fetched.counterfactual_fat_contract_outcome == "ship"


@pytest.mark.asyncio
async def test_telemetry_row_minimal_fields(db):
    """Most fields are nullable. A row with just the required fields should
    insert cleanly (no schema-level coercion of optional fields)."""
    async with db() as session:
        row = ProactiveDispatchTelemetry(
            id=generate_uuid(),
            user_id="u2",
            source="system_b_web",
            speech_act="thought_youd_want",
            topic_key="sysb:example.com:abc",
        )
        session.add(row)
        await session.commit()

        fetched = (
            await session.execute(
                select(ProactiveDispatchTelemetry).where(
                    ProactiveDispatchTelemetry.id == row.id
                )
            )
        ).scalar_one()
        assert fetched.tier3_invoked is False  # server default
        assert fetched.tier1_score is None
        assert fetched.counterfactual_fat_contract_draft is None
