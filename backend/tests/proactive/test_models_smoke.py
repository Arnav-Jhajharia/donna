"""Smoke test that the new SQLAlchemy models can be instantiated and
satisfy their type-level constraints. Does not hit a real DB.
"""
from __future__ import annotations

from datetime import datetime, timezone

from db.models import (
    ProactiveDailyCount,
    ProactiveLedger,
    ProactiveSignal,
    ProactiveSubscription,
)


def test_proactive_subscription_has_expected_columns() -> None:
    cols = {c.name for c in ProactiveSubscription.__table__.columns}
    assert {
        "id",
        "user_id",
        "intent_key",
        "description",
        "webset_id",
        "monitor_id",
        "cadence",
        "created_at",
        "last_refreshed_at",
        "last_hit_at",
        "active",
    } <= cols


def test_proactive_signal_has_expected_columns() -> None:
    cols = {c.name for c in ProactiveSignal.__table__.columns}
    assert {
        "id",
        "user_id",
        "subscription_id",
        "intent_key",
        "payload",
        "arrived_at",
        "consumed_at",
    } <= cols


def test_proactive_ledger_pkey_is_user_id_plus_dedup_key() -> None:
    pk = {c.name for c in ProactiveLedger.__table__.primary_key.columns}
    assert pk == {"user_id", "dedup_key"}


def test_proactive_daily_count_pkey_is_user_id_plus_local_date() -> None:
    pk = {c.name for c in ProactiveDailyCount.__table__.primary_key.columns}
    assert pk == {"user_id", "local_date"}


def test_proactive_subscription_unique_constraint_on_user_intent() -> None:
    constraints = {
        c.name for c in ProactiveSubscription.__table__.constraints if c.name
    }
    assert "uq_proactive_subs_user_intent" in constraints
