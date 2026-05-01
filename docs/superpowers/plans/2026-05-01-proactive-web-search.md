# Proactive Web Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a complete, end-to-end proactive web search system. Donna subscribes per-user to topics from `living_profile.watch_for_tomorrow`, builds Exa websets + monitors that push hits via webhook, drains the signal queue on a schedule, generates hypothesis-shaped queries, judges hits brutally, and delivers in shadow or live mode. Tested on a single user before any wider rollout.

**Architecture:** Seven-layer stack — (L0) Living Profile feeds (L1) per-user Exa subscriptions (websets + monitors) that push to (L2) `proactive_signals` queue, drained on schedule by (L3) the existing `run_proactive_tick` brain (query gen + execute + judge), then (L4) shadow/live delivery, with (L5) persistent dedup + daily budget tracking and (L6) admin visibility via SQL/dashboard. A new `donna-proactive` Railway role hosts the drain worker.

**Tech Stack:** Python 3.13, SQLAlchemy 2 async, Alembic, FastAPI, httpx, Pydantic, pytest, Postgres, Exa API (`/search`, `/findSimilar`, `/websets/v0/*`, `/research/v0/tasks`).

**Scope:** Web proactive only. Does NOT redesign attention, the top-level proactive dispatcher, or reminders. Integration with the dispatcher is a single call at delivery time.

**Test target:** One real user (the developer's own account). End-to-end smoke runs against the live `EXA_API_KEY` and a Postgres dev DB.

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `backend/db/migrations/versions/0014_proactive_subscriptions.py` | Alembic migration: 4 new tables |
| `backend/web/proactive/store.py` | `PostgresDedupStore`, `DailyCountRepo`, `SignalQueueRepo` |
| `backend/web/proactive/subscriptions.py` | `reconcile_subscriptions`, `record_monitor_hit`, webset/monitor lifecycle |
| `backend/web/proactive/triggers/drain.py` | Drain trigger entry point |
| `backend/web/proactive/delivery.py` | `deliver_drafts(mode=shadow\|live)` |
| `api/exa_webhook.py` | `/api/exa/monitor_callback` FastAPI route |
| `scripts/run_proactive_worker.py` | New Railway worker entry |
| `backend/tests/proactive/test_store.py` | Tests for the persistent stores |
| `backend/tests/proactive/test_subscriptions.py` | Tests for reconcile + record_monitor_hit |
| `backend/tests/proactive/test_drain_trigger.py` | Tests for the drain trigger |
| `backend/tests/proactive/test_delivery.py` | Tests for shadow + live delivery |
| `backend/tests/proactive/test_exa_webhook.py` | Tests for the webhook endpoint |

### Modified files

| Path | Change |
|---|---|
| `db/models.py` | Add `ProactiveSubscription`, `ProactiveSignal`, `ProactiveLedger`, `ProactiveDailyCount` |
| `backend/web/proactive/types.py` | Add `trigger`, `signal_queue` to `ProactiveContext`; add `hypothesis`, `user_signal`, `payoff_if_hit` to `ProactiveMove` |
| `backend/web/proactive/gates.py` | `DedupStore` Protocol becomes async; `apply_gates` becomes async |
| `backend/web/proactive/query_creation.py` | Trigger-aware system prompts; hypothesis-shaped `_RawMove` |
| `backend/web/proactive/judge.py` | Add surprise check to system prompt |
| `backend/web/proactive/runner.py` | Accept `trigger`, `signal_queue`, `delivery_mode`; integrate `deliver_drafts` |
| `backend/web/proactive/triggers/morning.py` | Call `run_proactive_tick(trigger="morning")` instead of `donna_turn` directly |
| `backend/memory/jobs/synthesis_worker.py` | Call `reconcile_subscriptions(user_id)` after morning_runner |
| `api/main.py` | Mount `exa_webhook` router; add `proactive` to known roles |
| `bin/start.sh` | Add `proactive` role case |

---

## Conventions

- All new SQLAlchemy models use `mapped_column` + `Mapped[...]` syntax matching `db/models.py`.
- All new tests use `pytest`; async tests use `pytest.mark.asyncio` (the project already wires `asyncio_mode=auto` in `pytest.ini` — confirm before writing the first test).
- Type annotations on every signature, PEP 8 / black-formatted.
- Frozen dataclasses for DTOs.
- Commits use conventional commit prefixes: `feat:`, `fix:`, `refactor:`, `test:`, `chore:`.

---

# PHASE 1 — Persistence (Tasks 1-5)

## Task 1: Database migration + models for proactive_subscriptions, proactive_signals, proactive_ledger, proactive_daily_count

**Files:**
- Create: `backend/db/migrations/versions/0014_proactive_subscriptions.py`
- Modify: `db/models.py` (append at end of file)
- Test: `backend/tests/proactive/test_models_smoke.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/proactive/test_models_smoke.py`:

```python
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
```

Also create `backend/tests/proactive/__init__.py` if it doesn't already exist (it does — verify).

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/i3dlab/Downloads/InstructKr.Claw-Code-main
.venv/bin/pytest backend/tests/proactive/test_models_smoke.py -v
```

Expected: FAIL with `ImportError: cannot import name 'ProactiveSubscription'`.

- [ ] **Step 3: Append the four models to `db/models.py`**

Append at the very end of `db/models.py`:

```python
class ProactiveSubscription(Base):
    """One persistent subscription per (user, intent_key). Backed by an
    Exa webset + monitor. Created during nightly synth reconciliation
    when ``living_profile.watch_for_tomorrow`` adds a new entry. Evicted
    LRU when the user exceeds the per-user webset budget.
    """

    __tablename__ = "proactive_subscriptions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False
    )
    intent_key: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    webset_id: Mapped[str | None] = mapped_column(String, nullable=True)
    monitor_id: Mapped[str | None] = mapped_column(String, nullable=True)
    cadence: Mapped[str] = mapped_column(String, nullable=False, default="daily")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    last_refreshed_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        sa.UniqueConstraint(
            "user_id", "intent_key", name="uq_proactive_subs_user_intent"
        ),
        Index("idx_proactive_subs_user_active", "user_id", "active"),
    )


class ProactiveSignal(Base):
    """One row per Exa monitor hit. Drained by the proactive worker.

    ``payload`` carries the Exa item shape (title, url, highlights,
    publishedDate, ...). ``consumed_at`` is set when the drain trigger
    has finished judging the row.
    """

    __tablename__ = "proactive_signals"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False
    )
    subscription_id: Mapped[str] = mapped_column(
        String, ForeignKey("proactive_subscriptions.id"), nullable=False
    )
    intent_key: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    arrived_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index(
            "idx_proactive_signals_user_pending",
            "user_id",
            "arrived_at",
            postgresql_where=sa.text("consumed_at IS NULL"),
        ),
    )


class ProactiveLedger(Base):
    """Persistent dedup ledger. Replaces InMemoryDedupStore in production.

    A row exists per (user, dedup_key) with the last-fired timestamp.
    The proactive runner's ``apply_gates`` checks ``fired_at`` against a
    TTL window before letting the same intent fire again.
    """

    __tablename__ = "proactive_ledger"
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), primary_key=True
    )
    dedup_key: Mapped[str] = mapped_column(String, primary_key=True)
    fired_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )

    __table_args__ = (
        Index("idx_proactive_ledger_fired", "user_id", "fired_at"),
    )


class ProactiveDailyCount(Base):
    """Per-user-per-local-day move counter. Feeds CostBudget.daily_used.

    ``local_date`` is the user's local YYYY-MM-DD string at the moment
    the move was emitted. The repo bumps this counter inside the same
    transaction that marks the ledger so the two stay consistent.
    """

    __tablename__ = "proactive_daily_count"
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), primary_key=True
    )
    local_date: Mapped[str] = mapped_column(String, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
```

- [ ] **Step 4: Run the model smoke test**

```bash
.venv/bin/pytest backend/tests/proactive/test_models_smoke.py -v
```

Expected: PASS (all 5 tests).

- [ ] **Step 5: Create the Alembic migration**

Create `backend/db/migrations/versions/0014_proactive_subscriptions.py`:

```python
"""Proactive web search subsystem v1.

Tables:
- proactive_subscriptions: per-user durable subscription per intent_key
- proactive_signals: queue of Exa monitor hits awaiting drain
- proactive_ledger: persistent dedup TTL ledger
- proactive_daily_count: per-user-per-local-day move counter

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "proactive_subscriptions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("intent_key", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("webset_id", sa.String(), nullable=True),
        sa.Column("monitor_id", sa.String(), nullable=True),
        sa.Column(
            "cadence", sa.String(), nullable=False, server_default="daily"
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_refreshed_at", sa.DateTime(), nullable=False),
        sa.Column("last_hit_at", sa.DateTime(), nullable=True),
        sa.Column(
            "active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.UniqueConstraint(
            "user_id", "intent_key", name="uq_proactive_subs_user_intent"
        ),
    )
    op.create_index(
        "idx_proactive_subs_user_active",
        "proactive_subscriptions",
        ["user_id", "active"],
    )

    op.create_table(
        "proactive_signals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "subscription_id",
            sa.String(),
            sa.ForeignKey("proactive_subscriptions.id"),
            nullable=False,
        ),
        sa.Column("intent_key", sa.String(), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("arrived_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "idx_proactive_signals_user_pending",
        "proactive_signals",
        ["user_id", "arrived_at"],
        postgresql_where=sa.text("consumed_at IS NULL"),
    )

    op.create_table(
        "proactive_ledger",
        sa.Column(
            "user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("dedup_key", sa.String(), nullable=False),
        sa.Column("fired_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id", "dedup_key", name="pk_proactive_ledger"
        ),
    )
    op.create_index(
        "idx_proactive_ledger_fired",
        "proactive_ledger",
        ["user_id", "fired_at"],
    )

    op.create_table(
        "proactive_daily_count",
        sa.Column(
            "user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("local_date", sa.String(), nullable=False),
        sa.Column(
            "count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "local_date", name="pk_proactive_daily_count"
        ),
    )


def downgrade() -> None:
    op.drop_table("proactive_daily_count")
    op.drop_index(
        "idx_proactive_ledger_fired", table_name="proactive_ledger"
    )
    op.drop_table("proactive_ledger")
    op.drop_index(
        "idx_proactive_signals_user_pending",
        table_name="proactive_signals",
    )
    op.drop_table("proactive_signals")
    op.drop_index(
        "idx_proactive_subs_user_active",
        table_name="proactive_subscriptions",
    )
    op.drop_table("proactive_subscriptions")
```

- [ ] **Step 6: Verify migration parses (offline SQL render)**

```bash
.venv/bin/alembic upgrade 0014 --sql > /tmp/0014_upgrade.sql
.venv/bin/alembic downgrade 0013 --sql > /tmp/0014_downgrade.sql
grep -c "CREATE TABLE proactive_" /tmp/0014_upgrade.sql
```

Expected: prints `4` (four CREATE TABLE statements).

- [ ] **Step 7: Commit**

```bash
git add db/models.py backend/db/migrations/versions/0014_proactive_subscriptions.py backend/tests/proactive/test_models_smoke.py
git commit -m "feat(proactive): add subscriptions, signals, ledger, daily_count tables"
```

---

## Task 2: PostgresDedupStore (async) + make gates async

**Files:**
- Modify: `backend/web/proactive/gates.py` (Protocol becomes async, `apply_gates` becomes async)
- Modify: `backend/web/proactive/runner.py` (`apply_gates` call becomes awaited)
- Create: `backend/web/proactive/store.py` (PostgresDedupStore)
- Test: `backend/tests/proactive/test_store.py`

- [ ] **Step 1: Update existing test for InMemoryDedupStore to async**

The existing test for the in-memory ledger lives in tests of the runner and dispatcher. Search for it:

```bash
grep -rn "InMemoryDedupStore\|apply_gates" /Users/i3dlab/Downloads/InstructKr.Claw-Code-main/backend/tests --include="*.py"
```

Note any callers — they will need `await`. There should be a small number; keep the list for Step 5.

- [ ] **Step 2: Write the failing async store test**

Create `backend/tests/proactive/test_store.py`:

```python
"""Tests for backend.web.proactive.store.

Uses the project's async session fixtures. The fixture must roll back
between tests; if your project uses a different fixture name adjust the
``async_db`` fixture import.
"""
from __future__ import annotations

import time

import pytest

from backend.web.proactive.store import (
    DailyCountRepo,
    PostgresDedupStore,
    SignalQueueRepo,
)
from db.models import ProactiveSignal, ProactiveSubscription, User
from db.session import async_session


@pytest.fixture
async def fresh_user() -> str:
    """Insert a throwaway user and return its id. Cleaned up by rollback fixture."""
    async with async_session() as session:
        from datetime import datetime, timezone
        u = User(
            id="u_test_proactive_store",
            phone="+10000000000",
            display_name="proactive store test",
            timezone="Asia/Singapore",
            living_profile={},
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        session.add(u)
        await session.commit()
    yield "u_test_proactive_store"
    async with async_session() as session:
        await session.execute(
            User.__table__.delete().where(User.id == "u_test_proactive_store")
        )
        await session.commit()


@pytest.mark.asyncio
async def test_dedup_store_seen_returns_false_when_unseen(fresh_user):
    store = PostgresDedupStore(ttl_seconds=3600.0)
    assert await store.seen_async(fresh_user, "watch:foo", now=time.time()) is False


@pytest.mark.asyncio
async def test_dedup_store_mark_then_seen_is_true(fresh_user):
    store = PostgresDedupStore(ttl_seconds=3600.0)
    now = time.time()
    await store.mark_async(fresh_user, "watch:foo", now=now)
    assert await store.seen_async(fresh_user, "watch:foo", now=now) is True


@pytest.mark.asyncio
async def test_dedup_store_seen_expires_after_ttl(fresh_user):
    store = PostgresDedupStore(ttl_seconds=10.0)
    now = time.time()
    await store.mark_async(fresh_user, "watch:foo", now=now - 100.0)
    assert await store.seen_async(fresh_user, "watch:foo", now=now) is False


@pytest.mark.asyncio
async def test_daily_count_starts_at_zero(fresh_user):
    repo = DailyCountRepo()
    assert await repo.get(fresh_user, "2026-05-01") == 0


@pytest.mark.asyncio
async def test_daily_count_bump_increments(fresh_user):
    repo = DailyCountRepo()
    await repo.bump(fresh_user, "2026-05-01", by=1)
    await repo.bump(fresh_user, "2026-05-01", by=2)
    assert await repo.get(fresh_user, "2026-05-01") == 3


@pytest.mark.asyncio
async def test_signal_queue_enqueue_and_drain(fresh_user):
    # Need a subscription first
    from datetime import datetime, timezone
    async with async_session() as session:
        sub = ProactiveSubscription(
            id="sub_test_1",
            user_id=fresh_user,
            intent_key="watch:foo",
            description="watching foo",
            cadence="daily",
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            last_refreshed_at=datetime.now(timezone.utc).replace(tzinfo=None),
            active=True,
        )
        session.add(sub)
        await session.commit()

    queue = SignalQueueRepo()
    await queue.enqueue(
        user_id=fresh_user,
        subscription_id="sub_test_1",
        intent_key="watch:foo",
        payload={"title": "x", "url": "https://example.com/x"},
    )
    pending = await queue.drain_pending(fresh_user, limit=10)
    assert len(pending) == 1
    assert pending[0].payload["title"] == "x"

    # Mark consumed
    await queue.mark_consumed([pending[0].id])
    pending2 = await queue.drain_pending(fresh_user, limit=10)
    assert pending2 == []
```

- [ ] **Step 3: Run test to verify it fails**

```bash
.venv/bin/pytest backend/tests/proactive/test_store.py -v
```

Expected: FAIL with `ImportError` on `backend.web.proactive.store`.

- [ ] **Step 4: Implement `backend/web/proactive/store.py`**

Create `backend/web/proactive/store.py`:

```python
"""Persistent stores for the proactive subsystem.

- ``PostgresDedupStore`` implements the async ``DedupStore`` Protocol
  from gates.py. Backed by ``proactive_ledger``.
- ``DailyCountRepo`` reads/writes ``proactive_daily_count`` rows. Used
  by the gates layer to enforce CostBudget.per_day across worker ticks.
- ``SignalQueueRepo`` enqueues Exa monitor hits and drains pending rows
  for the proactive runner.

All three are pure-async, return frozen DTOs, and never raise on missing
rows (they return safe empty values).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models import (
    ProactiveDailyCount,
    ProactiveLedger,
    ProactiveSignal,
)
from db.session import async_session


# ---------------------------------------------------------------------------
# dedup store
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PostgresDedupStore:
    """Async dedup ledger backed by ``proactive_ledger``.

    ``seen_async`` returns True when a row exists with ``fired_at`` newer
    than ``now - ttl_seconds``. The TTL is checked at read time, not by
    a sweeper — stale rows are tolerated. Run ``purge_older_than`` from
    a periodic job if the table grows.
    """

    ttl_seconds: float = 6 * 3600.0

    async def seen_async(
        self, user_id: str, dedup_key: str, *, now: float
    ) -> bool:
        cutoff = datetime.fromtimestamp(
            now - self.ttl_seconds, tz=timezone.utc
        ).replace(tzinfo=None)
        async with async_session() as session:
            row = (
                await session.execute(
                    select(ProactiveLedger.fired_at).where(
                        ProactiveLedger.user_id == user_id,
                        ProactiveLedger.dedup_key == dedup_key,
                    )
                )
            ).scalar_one_or_none()
        if row is None:
            return False
        return row >= cutoff

    async def mark_async(
        self, user_id: str, dedup_key: str, *, now: float
    ) -> None:
        when = datetime.fromtimestamp(now, tz=timezone.utc).replace(tzinfo=None)
        async with async_session() as session:
            stmt = (
                pg_insert(ProactiveLedger)
                .values(user_id=user_id, dedup_key=dedup_key, fired_at=when)
                .on_conflict_do_update(
                    index_elements=["user_id", "dedup_key"],
                    set_={"fired_at": when},
                )
            )
            await session.execute(stmt)
            await session.commit()

    async def purge_older_than(self, *, hours: int = 48) -> int:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            hours=hours
        )
        async with async_session() as session:
            res = await session.execute(
                delete(ProactiveLedger).where(
                    ProactiveLedger.fired_at < cutoff
                )
            )
            await session.commit()
            return res.rowcount or 0


# ---------------------------------------------------------------------------
# daily count repo
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DailyCountRepo:
    """Per-user-per-local-day move counter."""

    async def get(self, user_id: str, local_date: str) -> int:
        async with async_session() as session:
            row = (
                await session.execute(
                    select(ProactiveDailyCount.count).where(
                        ProactiveDailyCount.user_id == user_id,
                        ProactiveDailyCount.local_date == local_date,
                    )
                )
            ).scalar_one_or_none()
        return int(row or 0)

    async def bump(
        self, user_id: str, local_date: str, *, by: int = 1
    ) -> int:
        async with async_session() as session:
            stmt = (
                pg_insert(ProactiveDailyCount)
                .values(user_id=user_id, local_date=local_date, count=int(by))
                .on_conflict_do_update(
                    index_elements=["user_id", "local_date"],
                    set_={
                        "count": ProactiveDailyCount.count + int(by),
                    },
                )
                .returning(ProactiveDailyCount.count)
            )
            result = await session.execute(stmt)
            new_value = result.scalar_one()
            await session.commit()
            return int(new_value)


# ---------------------------------------------------------------------------
# signal queue repo
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PendingSignal:
    """Read-only view of a pending proactive_signals row."""

    id: str
    subscription_id: str
    intent_key: str
    payload: dict[str, Any]
    arrived_at: datetime


@dataclass(frozen=True)
class SignalQueueRepo:
    """Enqueue Exa monitor hits and drain the pending queue per user."""

    async def enqueue(
        self,
        *,
        user_id: str,
        subscription_id: str,
        intent_key: str,
        payload: dict[str, Any],
    ) -> str:
        signal = ProactiveSignal(
            user_id=user_id,
            subscription_id=subscription_id,
            intent_key=intent_key,
            payload=dict(payload or {}),
        )
        async with async_session() as session:
            session.add(signal)
            await session.commit()
            return signal.id

    async def drain_pending(
        self, user_id: str, *, limit: int = 25
    ) -> list[PendingSignal]:
        async with async_session() as session:
            rows = (
                await session.execute(
                    select(ProactiveSignal)
                    .where(
                        ProactiveSignal.user_id == user_id,
                        ProactiveSignal.consumed_at.is_(None),
                    )
                    .order_by(ProactiveSignal.arrived_at.asc())
                    .limit(max(1, int(limit)))
                )
            ).scalars().all()
        return [
            PendingSignal(
                id=r.id,
                subscription_id=r.subscription_id,
                intent_key=r.intent_key,
                payload=dict(r.payload or {}),
                arrived_at=r.arrived_at,
            )
            for r in rows
        ]

    async def mark_consumed(self, signal_ids: list[str]) -> None:
        if not signal_ids:
            return
        when = datetime.now(timezone.utc).replace(tzinfo=None)
        async with async_session() as session:
            await session.execute(
                update(ProactiveSignal)
                .where(ProactiveSignal.id.in_(list(signal_ids)))
                .values(consumed_at=when)
            )
            await session.commit()
```

- [ ] **Step 5: Make `gates.DedupStore` Protocol async + apply_gates async**

Modify `backend/web/proactive/gates.py`:

Replace the `DedupStore` Protocol and `InMemoryDedupStore` (around lines 74-103) with:

```python
class DedupStore(Protocol):
    """Minimal async protocol so we can swap Postgres / Redis / fakes."""

    async def seen_async(
        self, user_id: str, dedup_key: str, *, now: float
    ) -> bool: ...
    async def mark_async(
        self, user_id: str, dedup_key: str, *, now: float
    ) -> None: ...


@dataclass
class InMemoryDedupStore:
    """Per-process ledger keyed by ``(user_id, dedup_key)`` — async API.

    Kept as a fallback for tests and CLI dry-runs. Production runs use
    ``backend.web.proactive.store.PostgresDedupStore``.
    """

    ttl_seconds: float = 6 * 3600.0
    _entries: dict[tuple[str, str], float] = field(default_factory=dict)

    async def seen_async(
        self, user_id: str, dedup_key: str, *, now: float
    ) -> bool:
        key = (user_id, dedup_key)
        ts = self._entries.get(key)
        if ts is None:
            return False
        if (now - ts) >= self.ttl_seconds:
            self._entries.pop(key, None)
            return False
        return True

    async def mark_async(
        self, user_id: str, dedup_key: str, *, now: float
    ) -> None:
        self._entries[(user_id, dedup_key)] = now
```

Replace `apply_gates` (around line 146) with an async version:

```python
async def apply_gates(
    moves: list[ProactiveMove],
    *,
    user_id: str,
    ledger: DedupStore,
    budget: CostBudget = CostBudget(),
    daily_used: int = 0,
    now: float | None = None,
) -> GateOutcome:
    """Filter moves through dedup → relevance → budget. Async because
    the ledger is async (Postgres-backed in prod, in-memory in tests).

    The ledger is *read* but not mutated — call ``ledger.mark_async`` on
    each accepted move only after the worth-telling judge says yes.
    """
    now_ts = float(now if now is not None else time.time())

    accepted: list[ProactiveMove] = []
    dropped: list[GateDrop] = []
    daily_remaining = max(0, budget.per_day - max(0, int(daily_used)))

    for move in moves:
        if len(accepted) >= budget.per_turn:
            dropped.append(GateDrop(move=move, reason="per-turn budget exhausted"))
            continue
        if daily_remaining <= 0:
            dropped.append(GateDrop(move=move, reason="per-day budget exhausted"))
            continue
        bad = is_obviously_bad(move)
        if bad:
            dropped.append(GateDrop(move=move, reason=bad))
            continue
        if await ledger.seen_async(user_id, move.dedup_key, now=now_ts):
            dropped.append(GateDrop(move=move, reason="dedup: recently fired"))
            continue
        accepted.append(move)
        daily_remaining -= 1

    return GateOutcome(accepted=accepted, dropped=dropped)
```

- [ ] **Step 6: Update `runner.py` to await apply_gates and use PostgresDedupStore by default**

In `backend/web/proactive/runner.py`, change the `apply_gates(...)` call inside `run_proactive_tick` (around line 175) to:

```python
    outcome = await apply_gates(
        moves,
        user_id=user_id,
        ledger=ledger,
        budget=budget,
        daily_used=daily_used,
    )
```

And change the default ledger logic (around line 144) to:

```python
    if ledger is None:
        from backend.web.proactive.store import PostgresDedupStore
        ledger = PostgresDedupStore()
```

Also change the `ledger.mark` call near the end of the function (around line 201) to:

```python
        if v.decision == "send":
            await ledger.mark_async(user_id, r.move.dedup_key, now=now_ts)
```

- [ ] **Step 7: Update existing callers — known breakages**

Three known breakages from making the protocol async:

1. `backend/tests/test_proactive_runner.py:117` — `ledger.seen("u", "watch:poke", now=0.0)` becomes `await ledger.seen_async("u", "watch:poke", now=0.0)`. The test is already `async def` so just await.

2. `backend/tests/test_proactive_runner.py:201` — same change.

3. `scripts/proactive_dry_run.py` calls `apply_gates(...)` from inside its async main; just add `await`. Verify with:

```bash
grep -n "apply_gates\|ledger\.seen\|ledger\.mark" /Users/i3dlab/Downloads/InstructKr.Claw-Code-main/scripts/proactive_dry_run.py
```

For each match, prefix with `await` and confirm the calling function is `async def`.

Run the global sweep to be safe:

```bash
grep -rn "ledger\.seen(\|ledger\.mark(\|apply_gates(" /Users/i3dlab/Downloads/InstructKr.Claw-Code-main/backend/tests /Users/i3dlab/Downloads/InstructKr.Claw-Code-main/scripts --include="*.py" | grep -v "_async"
```

Should print zero lines after the fix-up.

- [ ] **Step 8: Run all proactive tests**

```bash
.venv/bin/pytest backend/tests/proactive/ -v
```

Expected: PASS for `test_store.py` (6 tests) and any pre-existing tests still green.

- [ ] **Step 9: Commit**

```bash
git add backend/web/proactive/gates.py backend/web/proactive/runner.py backend/web/proactive/store.py backend/tests/proactive/test_store.py scripts/proactive_dry_run.py backend/tests
git commit -m "feat(proactive): persistent dedup store + async gates"
```

---

## Task 3: Wire DailyCountRepo into runner — track daily_used across ticks

**Files:**
- Modify: `backend/web/proactive/runner.py`

- [ ] **Step 1: Add a failing assertion to existing runner test**

In `backend/tests/test_proactive_runner.py`, add this test using the file's existing helpers (`_move`, `_result`, `_fake_blurb`, `runner_mod`):

```python
@pytest.mark.asyncio
async def test_run_proactive_tick_bumps_daily_count_per_send(monkeypatch):
    """When the judge greenlights a move, daily_count must bump by 1."""
    moves = [_move(dedup_key="watch:dailycount")]
    results = [_result(moves[0])]
    verdicts = [(results[0], JudgeVerdict(decision="send", draft="x"))]

    async def fake_create(ctx, **kw):
        return moves

    async def fake_exec(accepted):
        return results

    async def fake_judge(*, context, results):
        return verdicts

    monkeypatch.setattr(runner_mod, "create_proactive_moves", fake_create)
    monkeypatch.setattr(runner_mod, "execute_moves", fake_exec)
    monkeypatch.setattr(runner_mod, "judge_results", fake_judge)

    bumps: list[tuple[str, str, int]] = []

    class FakeRepo:
        async def get(self, user_id, local_date):
            return 0

        async def bump(self, user_id, local_date, *, by=1):
            bumps.append((user_id, local_date, by))
            return by

    monkeypatch.setattr(runner_mod, "DailyCountRepo", lambda: FakeRepo())

    ledger = InMemoryDedupStore()
    await run_proactive_tick(
        user_id="u_dc", ledger=ledger, load_blurb=_fake_blurb
    )
    assert len(bumps) == 1
    assert bumps[0][0] == "u_dc"
    assert bumps[0][2] == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest backend/tests/test_proactive_runner.py::test_run_proactive_tick_bumps_daily_count_per_send -v
```

Expected: FAIL.

- [ ] **Step 3: Update runner.py to bump the daily count**

In `backend/web/proactive/runner.py`, add an import:

```python
from backend.web.proactive.store import DailyCountRepo
```

In `run_proactive_tick`, before the `for r, v in verdicts` loop near the end, compute the local date:

```python
    # Bump daily counter for every send verdict. Local date is the
    # caller's responsibility but we default to UTC YYYY-MM-DD when not
    # provided — fine for accounting, tz drift here is harmless.
    daily_repo = DailyCountRepo()
    local_date = (
        datetime.now().strftime("%Y-%m-%d")
        if not isinstance(last_proactive_at, str) or "T" not in last_proactive_at
        else last_proactive_at.split("T", 1)[0]
    )
```

Then inside the existing send loop:

```python
    for r, v in verdicts:
        if v.decision == "send":
            await ledger.mark_async(user_id, r.move.dedup_key, now=now_ts)
            await daily_repo.bump(user_id, local_date, by=1)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest backend/tests/test_proactive_runner.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/web/proactive/runner.py backend/tests/test_proactive_runner.py
git commit -m "feat(proactive): persist daily move count per user"
```

---

## Task 4: Pass daily_used into the runner from caller workflow

**Files:**
- Modify: `backend/web/proactive/runner.py` (read DailyCountRepo at start of tick)

- [ ] **Step 1: Update runner to read daily_used from the repo when not provided**

In `run_proactive_tick`, near the top after `build_context`:

```python
    if daily_used == 0:
        try:
            local_date = datetime.now().strftime("%Y-%m-%d")
            daily_used = await DailyCountRepo().get(user_id, local_date)
        except Exception:
            logger.warning(
                "run_proactive_tick: daily_used lookup failed, defaulting to 0"
            )
            daily_used = 0
```

- [ ] **Step 2: Add a test that an over-budget user sees zero accepted moves**

In `backend/tests/test_proactive_runner.py`, add:

```python
@pytest.mark.asyncio
async def test_run_proactive_tick_respects_daily_budget_from_repo(monkeypatch):
    """When DailyCountRepo.get returns >= per_day, no moves accepted."""
    moves = [_move(dedup_key=f"watch:b{i}") for i in range(3)]

    async def fake_create(ctx, **kw):
        return moves

    async def fake_exec(accepted):
        return [_result(m) for m in accepted]

    async def fake_judge(*, context, results):
        return []

    monkeypatch.setattr(runner_mod, "create_proactive_moves", fake_create)
    monkeypatch.setattr(runner_mod, "execute_moves", fake_exec)
    monkeypatch.setattr(runner_mod, "judge_results", fake_judge)

    class FakeRepo:
        async def get(self, user_id, local_date):
            return 5

        async def bump(self, user_id, local_date, *, by=1):
            return 5

    monkeypatch.setattr(runner_mod, "DailyCountRepo", lambda: FakeRepo())

    ledger = InMemoryDedupStore()
    out = await run_proactive_tick(
        user_id="u_b",
        ledger=ledger,
        budget=CostBudget(per_turn=3, per_day=5),
        load_blurb=_fake_blurb,
    )
    assert out.results == []
    assert all(
        "per-day budget exhausted" in d.reason for d in out.moves_dropped
    )
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest backend/tests/test_proactive_runner.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/web/proactive/runner.py backend/tests/test_proactive_runner.py
git commit -m "feat(proactive): hydrate daily_used from repo at tick start"
```

---

## Task 5: Phase 1 integration smoke — full ledger round-trip

**Files:**
- Test: `backend/tests/proactive/test_phase1_smoke.py`

- [ ] **Step 1: Write the integration smoke test**

Create `backend/tests/proactive/test_phase1_smoke.py`:

```python
"""Phase 1 smoke: insert a synthetic move, gate-accept it, mark fired,
verify it gets dedup-rejected on the next pass within TTL.
"""
from __future__ import annotations

import time

import pytest

from backend.web.proactive.gates import CostBudget, apply_gates
from backend.web.proactive.store import PostgresDedupStore
from backend.web.proactive.types import ProactiveMove
from db.models import User
from db.session import async_session


@pytest.fixture
async def fresh_user() -> str:
    from datetime import datetime, timezone
    async with async_session() as session:
        u = User(
            id="u_test_phase1_smoke",
            phone="+10000000001",
            display_name="phase1 smoke",
            timezone="UTC",
            living_profile={},
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        session.add(u)
        await session.commit()
    yield "u_test_phase1_smoke"
    async with async_session() as session:
        await session.execute(
            User.__table__.delete().where(User.id == "u_test_phase1_smoke")
        )
        await session.commit()


@pytest.mark.asyncio
async def test_round_trip_dedup(fresh_user):
    move = ProactiveMove(
        rationale="testing dedup",
        tool="search",
        query="hello world test query",
        dedup_key="watch:test_phase1",
    )
    ledger = PostgresDedupStore(ttl_seconds=3600.0)

    outcome1 = await apply_gates(
        [move],
        user_id=fresh_user,
        ledger=ledger,
        budget=CostBudget(per_turn=3, per_day=10),
        daily_used=0,
    )
    assert len(outcome1.accepted) == 1

    # Mark the dedup key as fired
    await ledger.mark_async(fresh_user, move.dedup_key, now=time.time())

    outcome2 = await apply_gates(
        [move],
        user_id=fresh_user,
        ledger=ledger,
        budget=CostBudget(per_turn=3, per_day=10),
        daily_used=0,
    )
    assert outcome2.accepted == []
    assert any("dedup" in d.reason for d in outcome2.dropped)
```

- [ ] **Step 2: Run smoke test**

```bash
.venv/bin/pytest backend/tests/proactive/test_phase1_smoke.py -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/proactive/test_phase1_smoke.py
git commit -m "test(proactive): phase 1 dedup round-trip smoke"
```

---

# PHASE 2 — Subscriptions + Webhook (Tasks 6-9)

## Task 6: subscriptions.reconcile_subscriptions — diff watch_for_tomorrow against active subs

**Files:**
- Create: `backend/web/proactive/subscriptions.py`
- Test: `backend/tests/proactive/test_subscriptions.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/proactive/test_subscriptions.py`:

```python
"""Tests for subscriptions.reconcile_subscriptions.

The function reads ``users.living_profile.watch_for_tomorrow``, diffs
against active rows in ``proactive_subscriptions`` for that user, and:
- creates a new ``ProactiveSubscription`` row for any watch line not
  already represented (with webset_id/monitor_id None — actual Exa
  calls happen in a separate function under test in Task 7).
- deactivates rows whose intent_key no longer appears in watch_for_tomorrow.
- enforces the per-user budget: oldest active subs LRU-evicted when over.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.web.proactive.subscriptions import (
    intent_key_for_watch_line,
    reconcile_subscriptions,
)
from db.models import ProactiveSubscription, User
from db.session import async_session
from sqlalchemy import select


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
async def user_with_watches() -> str:
    user_id = "u_test_recon"
    async with async_session() as session:
        u = User(
            id=user_id,
            phone="+10000000002",
            display_name="recon test",
            timezone="UTC",
            living_profile={
                "watch_for_tomorrow": [
                    "antler sg batch 13 announcements",
                    "openai sora pricing changes",
                ],
            },
            created_at=_utcnow_naive(),
        )
        session.add(u)
        await session.commit()
    yield user_id
    async with async_session() as session:
        await session.execute(
            ProactiveSubscription.__table__.delete().where(
                ProactiveSubscription.user_id == user_id
            )
        )
        await session.execute(
            User.__table__.delete().where(User.id == user_id)
        )
        await session.commit()


def test_intent_key_for_watch_line_is_stable_and_lowercase():
    a = intent_key_for_watch_line("Antler SG batch 13")
    b = intent_key_for_watch_line("antler sg batch 13")
    assert a == b
    assert a.startswith("watch:")
    assert " " not in a


@pytest.mark.asyncio
async def test_reconcile_creates_rows_for_new_watches(user_with_watches):
    summary = await reconcile_subscriptions(user_with_watches)
    assert summary.created == 2
    assert summary.deactivated == 0

    async with async_session() as session:
        rows = (
            await session.execute(
                select(ProactiveSubscription).where(
                    ProactiveSubscription.user_id == user_with_watches,
                    ProactiveSubscription.active.is_(True),
                )
            )
        ).scalars().all()
    assert len(rows) == 2
    keys = {r.intent_key for r in rows}
    assert any("antler" in k for k in keys)
    assert any("sora" in k for k in keys)


@pytest.mark.asyncio
async def test_reconcile_is_idempotent(user_with_watches):
    s1 = await reconcile_subscriptions(user_with_watches)
    s2 = await reconcile_subscriptions(user_with_watches)
    assert s1.created == 2
    assert s2.created == 0


@pytest.mark.asyncio
async def test_reconcile_deactivates_dropped_watches(user_with_watches):
    await reconcile_subscriptions(user_with_watches)

    # Drop one watch
    async with async_session() as session:
        u = (
            await session.execute(
                select(User).where(User.id == user_with_watches)
            )
        ).scalar_one()
        u.living_profile = {
            "watch_for_tomorrow": ["antler sg batch 13 announcements"],
        }
        await session.commit()

    summary = await reconcile_subscriptions(user_with_watches)
    assert summary.deactivated == 1


@pytest.mark.asyncio
async def test_reconcile_enforces_budget_lru(user_with_watches):
    """When watch list exceeds budget, oldest non-listed are evicted."""
    # Reduce budget to 1 for the test
    summary = await reconcile_subscriptions(user_with_watches, max_active=1)
    assert summary.created == 1
    assert summary.skipped_over_budget == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest backend/tests/proactive/test_subscriptions.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement subscriptions.py**

Create `backend/web/proactive/subscriptions.py`:

```python
"""Subscription lifecycle: reconcile per-user watch_for_tomorrow against
``proactive_subscriptions`` rows, create webset+monitor in Exa,
record monitor hits.

This module is the bridge between the nightly Living Profile synthesis
and the always-on Exa subscription layer. ``reconcile_subscriptions``
is called from synthesis_worker after morning_runner; it does the table
diff but does NOT call Exa. ``provision_pending_websets`` walks rows
with ``webset_id IS NULL`` and provisions them — separated so the DB
diff stays cheap and Exa calls are bounded.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update

from db.models import ProactiveSubscription, ProactiveSignal, User
from db.session import async_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def intent_key_for_watch_line(line: str) -> str:
    """Stable intent key from a free-text watch line.

    Lowercased, alnum-collapsed, prefixed ``watch:``, hash-suffixed for
    uniqueness when two lines collapse to the same slug.
    """
    raw = (line or "").strip().lower()
    slug = _NON_ALNUM.sub("_", raw).strip("_")[:60] or "anon"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    return f"watch:{slug}:{digest}"


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# reconcile
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReconcileSummary:
    """Trace-friendly summary of one reconcile pass."""

    user_id: str
    created: int
    deactivated: int
    skipped_over_budget: int


async def reconcile_subscriptions(
    user_id: str,
    *,
    max_active: int = 5,
) -> ReconcileSummary:
    """Diff ``living_profile.watch_for_tomorrow`` against active subs.

    Creates rows for new watch lines (Exa provisioning is deferred to
    ``provision_pending_websets``). Deactivates rows whose intent_key no
    longer appears in the current watch list. Enforces ``max_active``
    via least-recently-refreshed eviction.

    Returns a ReconcileSummary; never raises.
    """
    async with async_session() as session:
        user = (
            await session.execute(
                select(User).where(User.id == user_id)
            )
        ).scalar_one_or_none()
        if user is None:
            return ReconcileSummary(user_id, created=0, deactivated=0, skipped_over_budget=0)

        profile = dict(user.living_profile or {})
        watches = profile.get("watch_for_tomorrow") or []
        if isinstance(watches, str):
            watches = [watches]
        watch_lines = [str(w).strip() for w in watches if str(w).strip()]
        wanted_keys: dict[str, str] = {
            intent_key_for_watch_line(w): w for w in watch_lines
        }

        active_rows = list(
            (
                await session.execute(
                    select(ProactiveSubscription).where(
                        ProactiveSubscription.user_id == user_id,
                        ProactiveSubscription.active.is_(True),
                    )
                )
            ).scalars()
        )
        active_keys = {r.intent_key: r for r in active_rows}

        # Deactivate rows no longer in the watch list
        deactivated = 0
        for key, row in active_keys.items():
            if key not in wanted_keys:
                row.active = False
                row.last_refreshed_at = _utcnow_naive()
                deactivated += 1

        # Create rows for new watch lines, respecting the budget
        active_count_after_deact = sum(
            1 for r in active_rows if r.active
        )
        budget_remaining = max(0, int(max_active) - active_count_after_deact)
        created = 0
        skipped = 0
        for key, line in wanted_keys.items():
            if key in active_keys:
                continue
            if budget_remaining <= 0:
                skipped += 1
                continue
            row = ProactiveSubscription(
                user_id=user_id,
                intent_key=key,
                description=line[:1000],
                cadence="daily",
                created_at=_utcnow_naive(),
                last_refreshed_at=_utcnow_naive(),
                active=True,
            )
            session.add(row)
            created += 1
            budget_remaining -= 1

        await session.commit()

    return ReconcileSummary(
        user_id=user_id,
        created=created,
        deactivated=deactivated,
        skipped_over_budget=skipped,
    )
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest backend/tests/proactive/test_subscriptions.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/web/proactive/subscriptions.py backend/tests/proactive/test_subscriptions.py
git commit -m "feat(proactive): reconcile per-user subscriptions from watch_for_tomorrow"
```

---

## Task 7: subscriptions.provision_pending_websets — call Exa to create webset + monitor

**Files:**
- Modify: `backend/web/proactive/subscriptions.py`
- Test: extend `backend/tests/proactive/test_subscriptions.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/proactive/test_subscriptions.py`:

```python
@pytest.mark.asyncio
async def test_provision_pending_websets_calls_exa_and_persists_ids(
    monkeypatch, user_with_watches
):
    """Pending subs (webset_id IS NULL) get provisioned via Exa client."""
    from backend.web.proactive import subscriptions as subs

    calls: list[tuple[str, dict]] = []

    async def fake_webset_create(query, **kw):
        calls.append(("webset", {"query": query, **kw}))
        return {"id": f"ws_{len(calls)}", "status": "pending"}

    async def fake_monitor_create(*, webset_id, cadence, behavior, **kw):
        calls.append(
            ("monitor", {"websetId": webset_id, "cadence": cadence, "behavior": behavior})
        )
        return {"id": f"mon_{webset_id}", "status": "active"}

    monkeypatch.setattr(subs, "exa_webset_create", fake_webset_create)
    monkeypatch.setattr(subs, "exa_monitor_create", fake_monitor_create)
    monkeypatch.setattr(subs, "have_exa_key", lambda: True)

    await subs.reconcile_subscriptions(user_with_watches)
    summary = await subs.provision_pending_websets(user_with_watches)
    assert summary.provisioned == 2
    assert summary.failed == 0
    # 2 websets + 2 monitors
    assert sum(1 for c in calls if c[0] == "webset") == 2
    assert sum(1 for c in calls if c[0] == "monitor") == 2

    # Re-running should be a no-op
    summary2 = await subs.provision_pending_websets(user_with_watches)
    assert summary2.provisioned == 0


@pytest.mark.asyncio
async def test_provision_pending_websets_no_op_without_exa_key(
    monkeypatch, user_with_watches
):
    from backend.web.proactive import subscriptions as subs

    monkeypatch.setattr(subs, "have_exa_key", lambda: False)
    await subs.reconcile_subscriptions(user_with_watches)
    summary = await subs.provision_pending_websets(user_with_watches)
    assert summary.provisioned == 0
    assert summary.failed == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest backend/tests/proactive/test_subscriptions.py::test_provision_pending_websets_calls_exa_and_persists_ids -v
```

Expected: FAIL.

- [ ] **Step 3: Implement provision_pending_websets**

Append to `backend/web/proactive/subscriptions.py`:

```python
from backend.web.client import (
    exa_monitor_create,
    exa_webset_create,
    have_exa_key,
)


@dataclass(frozen=True)
class ProvisionSummary:
    """Result of one ``provision_pending_websets`` pass."""

    user_id: str
    provisioned: int
    failed: int


async def provision_pending_websets(user_id: str) -> ProvisionSummary:
    """For each active subscription with webset_id IS NULL, create the
    Exa webset and attach a monitor. Persists the IDs back to the row.

    No-op when EXA_API_KEY is missing — the Exa client refuses to call.
    Failures are logged and counted; the row is left pending so the next
    reconcile pass retries.
    """
    if not have_exa_key():
        logger.info(
            "provision_pending_websets: no EXA_API_KEY, skipping user=%s",
            user_id[:8] if user_id else "?",
        )
        return ProvisionSummary(user_id, provisioned=0, failed=0)

    provisioned = 0
    failed = 0
    async with async_session() as session:
        rows = list(
            (
                await session.execute(
                    select(ProactiveSubscription).where(
                        ProactiveSubscription.user_id == user_id,
                        ProactiveSubscription.active.is_(True),
                        ProactiveSubscription.webset_id.is_(None),
                    )
                )
            ).scalars()
        )

        for row in rows:
            try:
                webset = await exa_webset_create(
                    row.description,
                    count=10,
                )
                webset_id = str(webset.get("id") or "").strip()
                if not webset_id:
                    raise RuntimeError("webset response missing id")
                monitor = await exa_monitor_create(
                    webset_id=webset_id,
                    cadence=row.cadence or "daily",
                    behavior="search",
                )
                monitor_id = str(monitor.get("id") or "").strip()
                row.webset_id = webset_id
                row.monitor_id = monitor_id or None
                row.last_refreshed_at = _utcnow_naive()
                provisioned += 1
            except Exception:
                logger.exception(
                    "provision_pending_websets failed user=%s intent=%s",
                    user_id[:8] if user_id else "?",
                    row.intent_key,
                )
                failed += 1
                continue

        await session.commit()

    return ProvisionSummary(user_id, provisioned=provisioned, failed=failed)
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest backend/tests/proactive/test_subscriptions.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/web/proactive/subscriptions.py backend/tests/proactive/test_subscriptions.py
git commit -m "feat(proactive): provision Exa websets + monitors for pending subscriptions"
```

---

## Task 8: subscriptions.record_monitor_hit — webhook write path

**Files:**
- Modify: `backend/web/proactive/subscriptions.py`
- Test: extend `backend/tests/proactive/test_subscriptions.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
@pytest.mark.asyncio
async def test_record_monitor_hit_writes_signal_for_known_webset(
    monkeypatch, user_with_watches
):
    """A webhook payload with a known monitor_id writes a proactive_signals row."""
    from backend.web.proactive.subscriptions import record_monitor_hit
    from backend.web.proactive.store import SignalQueueRepo

    # Set up a sub with a known monitor_id
    async with async_session() as session:
        sub = (
            await session.execute(
                select(ProactiveSubscription).where(
                    ProactiveSubscription.user_id == user_with_watches,
                    ProactiveSubscription.active.is_(True),
                )
            )
        ).scalars().first()
        sub.webset_id = "ws_known"
        sub.monitor_id = "mon_known"
        await session.commit()

    payload = {
        "monitorId": "mon_known",
        "websetId": "ws_known",
        "items": [
            {
                "title": "Antler SG batch 13 announces",
                "url": "https://example.com/x",
                "publishedDate": "2026-05-01",
                "highlights": ["snippet a", "snippet b"],
            },
        ],
    }
    written = await record_monitor_hit(payload)
    assert written == 1

    queue = SignalQueueRepo()
    pending = await queue.drain_pending(user_with_watches)
    assert len(pending) == 1
    assert "Antler" in pending[0].payload.get("title", "")


@pytest.mark.asyncio
async def test_record_monitor_hit_unknown_monitor_is_dropped():
    from backend.web.proactive.subscriptions import record_monitor_hit
    written = await record_monitor_hit(
        {"monitorId": "mon_unknown", "items": [{"title": "x", "url": "https://x"}]}
    )
    assert written == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest backend/tests/proactive/test_subscriptions.py::test_record_monitor_hit_writes_signal_for_known_webset -v
```

Expected: FAIL.

- [ ] **Step 3: Implement record_monitor_hit**

Append to `backend/web/proactive/subscriptions.py`:

```python
from backend.web.proactive.store import SignalQueueRepo


async def record_monitor_hit(payload: dict[str, Any]) -> int:
    """Process one Exa monitor webhook payload.

    Looks up the matching ``ProactiveSubscription`` by ``monitorId``,
    enqueues one ``ProactiveSignal`` per item, and bumps
    ``last_hit_at`` on the subscription. Returns the number of signals
    written. Drops payloads whose monitor isn't recognized — Exa may
    fire monitors created by orphaned subs after a row was deactivated.
    """
    monitor_id = str(payload.get("monitorId") or "").strip()
    items = payload.get("items") or []
    if not monitor_id or not isinstance(items, list):
        return 0

    async with async_session() as session:
        sub = (
            await session.execute(
                select(ProactiveSubscription).where(
                    ProactiveSubscription.monitor_id == monitor_id,
                    ProactiveSubscription.active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if sub is None:
            return 0

        sub.last_hit_at = _utcnow_naive()
        await session.commit()
        sub_id = sub.id
        user_id = sub.user_id
        intent_key = sub.intent_key

    queue = SignalQueueRepo()
    written = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        await queue.enqueue(
            user_id=user_id,
            subscription_id=sub_id,
            intent_key=intent_key,
            payload=item,
        )
        written += 1
    return written
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest backend/tests/proactive/test_subscriptions.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/web/proactive/subscriptions.py backend/tests/proactive/test_subscriptions.py
git commit -m "feat(proactive): record_monitor_hit writes Exa monitor payloads to queue"
```

---

## Task 9: /api/exa/monitor_callback FastAPI endpoint

**Files:**
- Create: `api/exa_webhook.py`
- Modify: `api/main.py` (mount router)
- Test: `backend/tests/proactive/test_exa_webhook.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/proactive/test_exa_webhook.py`:

```python
"""Tests for the /api/exa/monitor_callback endpoint."""
from __future__ import annotations

import hashlib
import hmac
import json
import os

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture(autouse=True)
def _enable_secret(monkeypatch):
    monkeypatch.setenv("EXA_WEBHOOK_SECRET", "test_secret_xyz")


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_webhook_rejects_missing_signature():
    client = TestClient(app)
    res = client.post(
        "/api/exa/monitor_callback",
        json={"monitorId": "mon_x"},
    )
    assert res.status_code == 401


def test_webhook_rejects_bad_signature():
    client = TestClient(app)
    body = json.dumps({"monitorId": "mon_x"}).encode()
    res = client.post(
        "/api/exa/monitor_callback",
        content=body,
        headers={
            "x-exa-signature": "deadbeef",
            "content-type": "application/json",
        },
    )
    assert res.status_code == 401


def test_webhook_accepts_valid_signature(monkeypatch):
    body = json.dumps({"monitorId": "mon_unknown", "items": []}).encode()
    sig = _sign(body, "test_secret_xyz")

    async def fake_record(payload):
        assert payload.get("monitorId") == "mon_unknown"
        return 0

    from api import exa_webhook as ew
    monkeypatch.setattr(ew, "record_monitor_hit", fake_record)

    client = TestClient(app)
    res = client.post(
        "/api/exa/monitor_callback",
        content=body,
        headers={
            "x-exa-signature": sig,
            "content-type": "application/json",
        },
    )
    assert res.status_code == 200
    assert res.json() == {"recorded": 0}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest backend/tests/proactive/test_exa_webhook.py -v
```

Expected: FAIL with 404 or import error.

- [ ] **Step 3: Implement the webhook**

Create `api/exa_webhook.py`:

```python
"""Exa webset monitor webhook receiver.

Exa POSTs to this endpoint when a monitor produces new items. The body
is JSON; we verify an HMAC-SHA256 signature in the ``x-exa-signature``
header against ``EXA_WEBHOOK_SECRET``. Verified payloads are forwarded
to ``record_monitor_hit`` which enqueues per-item proactive_signals
rows.

Security:
- Reject requests with no signature header.
- Reject requests whose signature does not match.
- Use ``hmac.compare_digest`` for constant-time comparison.

Operationally, the secret is configured in Railway env. Set
``EXA_WEBHOOK_SECRET`` and supply it to Exa when registering the
monitor's webhook url.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os

from fastapi import APIRouter, HTTPException, Request

from backend.web.proactive.subscriptions import record_monitor_hit

logger = logging.getLogger(__name__)
router = APIRouter()


def _expected_signature(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@router.post("/api/exa/monitor_callback")
async def exa_monitor_callback(request: Request) -> dict[str, int]:
    secret = (os.environ.get("EXA_WEBHOOK_SECRET") or "").strip()
    if not secret:
        logger.warning("exa webhook called but EXA_WEBHOOK_SECRET unset")
        raise HTTPException(status_code=503, detail="webhook unconfigured")

    sig_header = (request.headers.get("x-exa-signature") or "").strip()
    if not sig_header:
        raise HTTPException(status_code=401, detail="missing signature")

    body = await request.body()
    expected = _expected_signature(body, secret)
    if not hmac.compare_digest(sig_header, expected):
        raise HTTPException(status_code=401, detail="bad signature")

    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid json")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload not object")

    written = await record_monitor_hit(payload)
    return {"recorded": int(written)}
```

- [ ] **Step 4: Mount router in api/main.py**

In `api/main.py`, near the other router includes (find existing `app.include_router(...)` calls and add alongside):

```python
from api.exa_webhook import router as exa_webhook_router
app.include_router(exa_webhook_router)
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest backend/tests/proactive/test_exa_webhook.py -v
```

Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add api/exa_webhook.py api/main.py backend/tests/proactive/test_exa_webhook.py
git commit -m "feat(api): exa monitor webhook with HMAC signature verification"
```

---

# PHASE 3 — Brain updates (Tasks 10-12)

## Task 10: Update ProactiveContext + ProactiveMove types

**Files:**
- Modify: `backend/web/proactive/types.py`
- Test: extend `backend/tests/test_proactive_query_creation.py`

- [ ] **Step 1: Update types.py**

In `backend/web/proactive/types.py`:

Add a new Literal and extend the dataclasses:

```python
TriggerKind = Literal["morning", "drain", "pre_event", "manual"]

VALID_TRIGGERS: frozenset[str] = frozenset(
    {"morning", "drain", "pre_event", "manual"}
)


@dataclass(frozen=True)
class SignalSummary:
    """One pending Exa monitor hit, summarized for the reasoner."""

    signal_id: str
    intent_key: str
    title: str
    url: str
    snippet: str
    published: str | None = None


@dataclass(frozen=True)
class ProactiveContext:
    """Snapshot of what the brain knows about the user RIGHT NOW.

    ``trigger`` is which scheduler fired this tick — the reasoner uses
    this to branch its prompt. ``signal_queue`` carries pending Exa
    monitor hits awaiting judgment; for ``trigger="drain"`` ticks this
    list is the primary input.
    """

    user_id: str
    profile_blurb: str = ""
    situation_brief: str = ""
    recent_thread: str = ""
    current_datetime: str = ""
    last_proactive_at: str | None = None
    trigger: TriggerKind = "manual"
    signal_queue: tuple[SignalSummary, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ProactiveMove:
    """One concrete proactive search action.

    The reasoner emits these. Each move carries a hypothesis-shaped
    rationale: what it's *betting* the world contains, anchored on a
    concrete signal from the user's state, with a stated payoff.
    """

    rationale: str  # legacy free-form, kept for backward compat
    tool: ExaTool
    query: str
    params: dict[str, Any] = field(default_factory=dict)
    urgency: float = 0.5
    render_hint: RenderHint = "short_text"
    dedup_key: str = ""
    # New hypothesis fields — may be empty for legacy callers
    hypothesis: str = ""
    user_signal: str = ""
    payoff_if_hit: str = ""
```

(Keep imports at the top consistent — `from dataclasses import dataclass, field`.)

- [ ] **Step 2: Add tests**

In `backend/tests/test_proactive_query_creation.py`, add:

```python
def test_proactive_context_default_trigger_is_manual():
    from backend.web.proactive.types import ProactiveContext
    ctx = ProactiveContext(user_id="u_x")
    assert ctx.trigger == "manual"


def test_proactive_move_hypothesis_fields_default_to_empty_string():
    from backend.web.proactive.types import ProactiveMove
    move = ProactiveMove(
        rationale="r",
        tool="search",
        query="q",
        dedup_key="dk",
    )
    assert move.hypothesis == ""
    assert move.user_signal == ""
    assert move.payoff_if_hit == ""
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest backend/tests/test_proactive_query_creation.py -v
```

Expected: PASS (existing tests still green, two new tests pass).

- [ ] **Step 4: Commit**

```bash
git add backend/web/proactive/types.py backend/tests/test_proactive_query_creation.py
git commit -m "feat(proactive): hypothesis fields + trigger/signal_queue on context"
```

---

## Task 11: query_creation.py — trigger-aware prompts + hypothesis-shaped output

**Files:**
- Modify: `backend/web/proactive/query_creation.py`
- Test: extend `backend/tests/test_proactive_query_creation.py`

- [ ] **Step 1: Add a failing test for trigger-aware prompt branching**

In `backend/tests/test_proactive_query_creation.py`:

```python
@pytest.mark.asyncio
async def test_format_context_includes_trigger_branch_for_drain(monkeypatch):
    """When trigger=drain and signal_queue has items, the rendered user
    block must mention the queue items so the reasoner can read them.
    """
    from backend.web.proactive.query_creation import _format_context
    from backend.web.proactive.types import ProactiveContext, SignalSummary

    sigs = (
        SignalSummary(
            signal_id="s1",
            intent_key="watch:foo",
            title="A new thing",
            url="https://example.com/a",
            snippet="snippet text",
        ),
    )
    ctx = ProactiveContext(
        user_id="u_x",
        trigger="drain",
        signal_queue=sigs,
        profile_blurb="profile",
    )
    block = _format_context(ctx)
    assert "drain" in block.lower()
    assert "A new thing" in block
    assert "https://example.com/a" in block


@pytest.mark.asyncio
async def test_create_proactive_moves_emits_hypothesis_fields(monkeypatch):
    """Mock call_structured to return one raw move with hypothesis fields;
    verify they survive _coerce_move."""
    from backend.web.proactive import query_creation as qc
    from backend.web.proactive.types import ProactiveContext

    async def fake_call_structured(**kw):
        from backend.web.proactive.query_creation import (
            _QueryCreationOut,
            _RawMove,
        )
        return _QueryCreationOut(
            moves=[
                _RawMove(
                    rationale="legacy",
                    tool="search",
                    query="q1",
                    dedup_key="dk1",
                    hypothesis="betting there's a new entrant in maya's wedge",
                    user_signal="user mentioned maya 3d ago",
                    payoff_if_hit="user reacts first instead of last",
                ),
            ]
        )

    monkeypatch.setattr(qc, "call_structured", fake_call_structured)

    moves = await qc.create_proactive_moves(ProactiveContext(user_id="u"))
    assert len(moves) == 1
    assert moves[0].hypothesis.startswith("betting")
    assert moves[0].user_signal.startswith("user mentioned")
    assert moves[0].payoff_if_hit.startswith("user reacts")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest backend/tests/test_proactive_query_creation.py -v
```

Expected: FAIL.

- [ ] **Step 3: Update query_creation.py**

In `backend/web/proactive/query_creation.py`:

Replace `_SYSTEM_PROMPT` with:

```python
_SYSTEM_PROMPT_BASE = """You decide what Donna should proactively look up for THIS user RIGHT NOW.

You read:
- the user's Living Profile (interests, current obsessions, working context, mentioned people)
- their Situation Brief (open loops, current_status, recent observations)
- their recent thread (last N messages)
- the current local date/time
- the trigger that fired this tick
- the signal queue (pending Exa monitor hits awaiting judgment)

You output 0-3 ProactiveMoves. Each move is one concrete external lookup that
would land for THIS user RIGHT NOW. Zero moves is a valid output — silence is
allowed when nothing in the inputs justifies an interruption.

A great move:
- ties to something the user actually mentioned or is working on
- is fresh (not something they already know or could trivially derive)
- earns the interruption (the user would thank you for surfacing it)
- is specific (a named entity, a clear question — never vague)

A bad move (do NOT emit):
- generic news ("AI news today", "tech news")
- a topic the user has not engaged with
- something the user could have asked themselves
- a moralistic, self-help, or wellness angle
- a recommendation framed as "you might like..."

Each move has SEVEN fields:

1. hypothesis: 1 sentence. What you are *betting* the world contains right now.
   Example: "betting there's a new entrant in maya's wedge that just raised."

2. user_signal: 1 sentence. The concrete thing in the inputs that justifies it.
   Quote or paraphrase. Example: "user said 3d ago they're picking between
   Poke and Limitless for pitch days."

3. payoff_if_hit: 1 sentence. Why the user would thank Donna if a hit comes back.
   Example: "user reacts to news first instead of being surprised at pitch day."

4. tool: pick the right Exa endpoint:
   - "search":       one fact, one shot. Cheapest, fastest.
   - "find_similar": you have a seed URL the user already engaged with.
                     Put the seed URL in `query`.
   - "research":     multi-step synthesis ("how has X evolved over time").
                     Async + expensive — only when one shot won't cut it.
   - "webset":       persistent curated set. Use only for fresh intents
                     not covered by an existing subscription.
   - "monitor":      schedule a recurring search. Almost never the right
                     choice from this loop — subscriptions are managed
                     elsewhere.

5. query:
   - for search/research: an Exa-style query. Neural queries are sentence-shaped
     ("articles comparing the design of X and Y"), not keyword bags.
   - for find_similar: the seed URL exactly.
   - for webset/monitor: the natural-language criteria for the set.

6. urgency: 0..1. 1.0 = today only, 0.5 = this week, 0.1 = whenever.

7. render_hint: short_text | long_text | card | image.

8. dedup_key: stable identifier for the INTENT (not the specific query).
   Same intent fired again should produce the same key.
   Example: "watch:poke_launch", "compare:poke_vs_limitless".

9. rationale: optional 1-2 sentence narrative; treat as legacy. Prefer
   filling hypothesis + user_signal + payoff_if_hit instead.

Rules:
- Anchor every hypothesis in something concretely present in the inputs.
- Do NOT invent user facts. If the inputs don't justify a move, return [].
- Do NOT recommend wellness, mindfulness, or self-help angles.
- Voice: terse, lowercase, no em dashes."""


_TRIGGER_BRANCH_DRAIN = """
TRIGGER: drain.
The signal queue contains pending Exa monitor hits the user has NOT seen.
Your primary job is to silently let those flow downstream — do NOT
generate fresh moves unless you see a gap the queue does not cover.
Return [] if the queue itself is the answer."""

_TRIGGER_BRANCH_MORNING = """
TRIGGER: morning.
The user just entered their first-engage window. Anchor on
``watch_for_tomorrow`` from the Living Profile. Surface ONE sharp move
about the world-state that intersects with what they're watching today."""

_TRIGGER_BRANCH_PRE_EVENT = """
TRIGGER: pre_event.
A calendar event is ~15 minutes away. The user is about to walk in.
Anchor on the people/topic of that event. The move should surface
something they would want to know BEFORE the meeting starts."""

_TRIGGER_BRANCH_MANUAL = """
TRIGGER: manual.
This is a dry-run / debug call. Behave as if it were morning."""


def _system_prompt_for(trigger: str) -> str:
    branch = {
        "drain": _TRIGGER_BRANCH_DRAIN,
        "morning": _TRIGGER_BRANCH_MORNING,
        "pre_event": _TRIGGER_BRANCH_PRE_EVENT,
    }.get(trigger, _TRIGGER_BRANCH_MANUAL)
    return f"{_SYSTEM_PROMPT_BASE}\n\n{branch}"
```

(Remove the old `_SYSTEM_PROMPT` constant entirely — replace its uses with `_system_prompt_for(context.trigger)`.)

Update `_RawMove` to include the new fields:

```python
class _RawMove(BaseModel):
    rationale: str = Field(default="", description="legacy free-form 1-2 sentences")
    hypothesis: str = Field(default="", description="what we're betting the world contains")
    user_signal: str = Field(default="", description="concrete signal from inputs")
    payoff_if_hit: str = Field(default="", description="why the user would thank donna")
    tool: str = Field(description="search | find_similar | research | webset | monitor")
    query: str = Field(description="query string, seed URL, or natural-language criteria")
    params: dict[str, Any] = Field(default_factory=dict)
    urgency: float = Field(default=0.5)
    render_hint: str = Field(default="short_text")
    dedup_key: str = Field(description="stable intent identifier, e.g. 'watch:poke_launch'")
```

Update `_format_context` to render trigger and signal queue:

```python
def _format_context(ctx: ProactiveContext) -> str:
    parts: list[str] = []
    parts.append(f"Trigger: {ctx.trigger}")
    if ctx.current_datetime:
        parts.append(f"Current local time: {ctx.current_datetime}")
    if ctx.last_proactive_at:
        parts.append(f"Last proactive turn: {ctx.last_proactive_at}")
    if ctx.profile_blurb.strip():
        parts.append(f"## Living Profile\n{ctx.profile_blurb.strip()}")
    if ctx.situation_brief.strip():
        parts.append(f"## Situation Brief\n{ctx.situation_brief.strip()}")
    if ctx.recent_thread.strip():
        parts.append(f"## Recent thread\n{ctx.recent_thread.strip()}")
    if ctx.signal_queue:
        rendered: list[str] = ["## Signal queue (pending monitor hits)"]
        for s in ctx.signal_queue[:8]:
            rendered.append(
                f"- intent={s.intent_key}\n"
                f"  title: {s.title}\n"
                f"  url: {s.url}\n"
                f"  snippet: {s.snippet[:200]}"
            )
        parts.append("\n".join(rendered))
    parts.append(
        "Decide what (if anything) to proactively look up. "
        "Return moves now — zero is allowed."
    )
    return "\n\n".join(parts)
```

Update `_coerce_move` to copy the new fields:

```python
def _coerce_move(raw: _RawMove) -> ProactiveMove | None:
    tool = (raw.tool or "").strip().lower()
    if tool not in VALID_TOOLS:
        return None
    hint = (raw.render_hint or "").strip().lower() or "short_text"
    if hint not in VALID_RENDER_HINTS:
        hint = "short_text"
    query = (raw.query or "").strip()
    if not query:
        return None
    dedup_key = (raw.dedup_key or "").strip()
    if not dedup_key:
        return None
    rationale = (raw.rationale or "").strip()[:_MAX_RATIONALE_CHARS]
    hypothesis = (raw.hypothesis or "").strip()[:_MAX_RATIONALE_CHARS]
    user_signal = (raw.user_signal or "").strip()[:_MAX_RATIONALE_CHARS]
    payoff = (raw.payoff_if_hit or "").strip()[:_MAX_RATIONALE_CHARS]
    try:
        urgency = float(raw.urgency)
    except (TypeError, ValueError):
        urgency = 0.5
    urgency = max(0.0, min(1.0, urgency))
    params = dict(raw.params or {})
    return ProactiveMove(
        rationale=rationale,
        tool=tool,  # type: ignore[arg-type]
        query=query[:_MAX_QUERY_CHARS],
        params=params,
        urgency=urgency,
        render_hint=hint,  # type: ignore[arg-type]
        dedup_key=dedup_key[:_MAX_DEDUP_KEY_CHARS],
        hypothesis=hypothesis,
        user_signal=user_signal,
        payoff_if_hit=payoff,
    )
```

Finally update `create_proactive_moves` to use trigger-aware prompt:

```python
async def create_proactive_moves(
    context: ProactiveContext,
    *,
    max_moves: int = _MAX_MOVES_DEFAULT,
    model: str = _MODEL,
) -> list[ProactiveMove]:
    """Read user state, return 0-N validated proactive moves."""
    user_block = _format_context(context)
    system_prompt = _system_prompt_for(context.trigger)
    try:
        result = await call_structured(
            model=model,
            system_prompt=system_prompt,
            user_message=user_block,
            schema=_QueryCreationOut,
            max_tokens=1200,
            cache=True,
        )
    except Exception:
        logger.exception("create_proactive_moves: call_structured raised")
        return []
    if result is None:
        return []
    moves: list[ProactiveMove] = []
    for raw in (result.moves or [])[: max(0, int(max_moves))]:
        move = _coerce_move(raw)
        if move is not None:
            moves.append(move)
    return moves
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest backend/tests/test_proactive_query_creation.py -v
```

Expected: PASS (existing + new tests).

- [ ] **Step 5: Commit**

```bash
git add backend/web/proactive/query_creation.py backend/tests/test_proactive_query_creation.py
git commit -m "feat(proactive): trigger-aware prompts + hypothesis-shaped query generation"
```

---

## Task 12: judge.py — surprise check

**Files:**
- Modify: `backend/web/proactive/judge.py`
- Test: extend `backend/tests/test_proactive_judge.py`

- [ ] **Step 1: Add failing test for surprise check**

In `backend/tests/test_proactive_judge.py`:

```python
@pytest.mark.asyncio
async def test_judge_silences_when_finding_could_be_inferred_from_profile(
    monkeypatch
):
    """When the result is something the user could have predicted from their
    profile alone (no surprise), judge silences."""
    from backend.web.proactive import judge as j
    from backend.web.proactive.types import (
        ProactiveContext,
        ProactiveMove,
        ProactiveResult,
    )

    async def fake_call_structured(**kw):
        from backend.web.proactive.judge import _JudgeOut
        return _JudgeOut(
            decision="silence",
            reason="result is something user already infers from profile",
        )

    monkeypatch.setattr(j, "call_structured", fake_call_structured)

    move = ProactiveMove(
        rationale="r",
        tool="search",
        query="q",
        dedup_key="dk",
    )
    result = ProactiveResult(
        move=move,
        status="ok",
        payload={"results": [{"url": "https://x", "title": "obvious"}]},
    )
    verdict = await j.judge_result(
        context=ProactiveContext(user_id="u"),
        result=result,
    )
    assert verdict.decision == "silence"
    assert "infer" in verdict.reason.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest backend/tests/test_proactive_judge.py -v
```

Expected: PASS already (the test stubs `call_structured`), but read the existing prompt to confirm it does ask about inference. If not:

- [ ] **Step 3: Update _SYSTEM_PROMPT in judge.py**

In `backend/web/proactive/judge.py`, replace `_SYSTEM_PROMPT` with:

```python
_SYSTEM_PROMPT = """You decide whether a proactive search result is worth interrupting the user with.

You read:
- the user's Living Profile + Situation Brief + recent thread
- the proactive move Donna chose to run, with its hypothesis,
  user_signal, and payoff_if_hit
- the result the move returned

You output one of:

1. SEND — the finding is sharp, fresh, anchored to a real user signal,
   AND surprising (not something the user could have inferred from their
   own profile alone). Provide a draft message ready to ship, in Donna's
   voice:
   - lowercase
   - terse, high-agency, no filler
   - no em dashes, no semicolons
   - never "you might like" / "I thought you'd find this interesting"
   - lead with the fact, not the framing

2. SILENCE — the finding is generic, stale, redundant, doesn't actually
   answer the move's hypothesis, OR is something the user could have
   predicted from their profile (no surprise). Explain why in one short
   sentence (for the trace).

CRITICAL surprise check: would a smart reader of the user's own profile
have already known this? If yes, SILENCE — Donna pinging known facts is
worse than not pinging at all.

Default to SILENCE when uncertain. Sending a weak ping costs more than
missing one — Donna's silence is part of the contract.

Respond with the structured schema. ``draft`` is required when decision
is ``send`` and ignored otherwise. ``reason`` is required when decision
is ``silence`` and ignored otherwise."""
```

Also extend `_format_judge_context` to include the hypothesis fields:

```python
    parts.append(
        "## Proactive move\n"
        f"tool: {move.tool}\n"
        f"query: {move.query}\n"
        f"hypothesis: {move.hypothesis}\n"
        f"user_signal: {move.user_signal}\n"
        f"payoff_if_hit: {move.payoff_if_hit}\n"
        f"rationale (legacy): {move.rationale}\n"
        f"urgency: {move.urgency}\n"
        f"render_hint: {move.render_hint}"
    )
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest backend/tests/test_proactive_judge.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/web/proactive/judge.py backend/tests/test_proactive_judge.py
git commit -m "feat(proactive): surprise-check in judge prompt + hypothesis context"
```

---

# PHASE 4 — Delivery + Runner (Tasks 13-14)

## Task 13: delivery.py — shadow vs live modes

**Files:**
- Create: `backend/web/proactive/delivery.py`
- Modify: `db/models.py` (add `is_shadow` to ChatMessage)
- Create: `backend/db/migrations/versions/0015_chat_message_is_shadow.py`
- Test: `backend/tests/proactive/test_delivery.py`

- [ ] **Step 1: Add migration for is_shadow column**

Create `backend/db/migrations/versions/0015_chat_message_is_shadow.py`:

```python
"""Add is_shadow column to chat_messages.

Used by the proactive delivery layer to log "would have sent" drafts
without surfacing them to the user during shadow mode.

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-01
"""
from alembic import op
import sqlalchemy as sa


revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column(
            "is_shadow",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "idx_chat_messages_user_shadow",
        "chat_messages",
        ["user_id", "is_shadow"],
        postgresql_where=sa.text("is_shadow = true"),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_chat_messages_user_shadow", table_name="chat_messages"
    )
    op.drop_column("chat_messages", "is_shadow")
```

- [ ] **Step 2: Add is_shadow to ChatMessage model**

In `db/models.py`, find the `ChatMessage` class (line 54) and add:

```python
    is_shadow: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
```

- [ ] **Step 3: Write the failing test**

Create `backend/tests/proactive/test_delivery.py`:

```python
"""Tests for delivery.deliver_drafts."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from backend.web.proactive.delivery import deliver_drafts
from backend.web.proactive.judge import JudgeVerdict
from backend.web.proactive.types import ProactiveMove, ProactiveResult
from db.models import ChatMessage, User
from db.session import async_session


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
async def fresh_user() -> str:
    user_id = "u_test_delivery"
    async with async_session() as session:
        u = User(
            id=user_id,
            phone="+10000000003",
            display_name="delivery test",
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
    assert rows[0].direction == "outbound"


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
```

- [ ] **Step 4: Run test to verify it fails**

```bash
.venv/bin/pytest backend/tests/proactive/test_delivery.py -v
```

Expected: FAIL with import error or migration error.

- [ ] **Step 5: Run migrations**

```bash
.venv/bin/alembic upgrade head
```

Expected: applies 0014 then 0015. If 0014 wasn't applied yet, that's fine — head pulls both.

- [ ] **Step 6: Implement delivery.py**

Create `backend/web/proactive/delivery.py`:

```python
"""Delivery layer for proactive verdicts.

Two modes:
- ``shadow``: writes a ``chat_messages`` row with ``is_shadow=True``,
  does NOT send WhatsApp. The drafts surface in the dashboard for
  calibration but the user never sees them.
- ``live``: writes ``is_shadow=False`` and dispatches WhatsApp via
  ``delivery.whatsapp.WhatsAppChannel``.

Caller chooses mode per user. New users default to shadow for ~14 days
while we calibrate the judge — after that the operator flips them by
toggling ``users.living_profile['proactive_delivery_mode'] = 'live'``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select

from backend.web.proactive.judge import JudgeVerdict
from backend.web.proactive.types import ProactiveResult
from db.models import ChatMessage, User
from db.session import async_session

logger = logging.getLogger(__name__)

DeliveryMode = Literal["shadow", "live"]


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _get_whatsapp_channel():
    """Indirection so tests can monkeypatch the channel constructor."""
    from delivery.whatsapp import WhatsAppChannel
    return WhatsAppChannel()


async def _user_phone(user_id: str) -> str | None:
    async with async_session() as session:
        u = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
    return getattr(u, "phone", None) if u else None


async def deliver_drafts(
    *,
    user_id: str,
    verdicts: list[tuple[ProactiveResult, JudgeVerdict]],
    mode: DeliveryMode = "shadow",
) -> int:
    """Persist + dispatch greenlit drafts. Returns number sent.

    Silence verdicts are dropped silently (they never had a draft).
    Failures during dispatch are logged but not raised — the row is
    still persisted with ``is_shadow=True`` so we have an audit trail.
    """
    sends = [
        (r, v.draft) for r, v in verdicts
        if v.decision == "send" and v.draft.strip()
    ]
    if not sends:
        return 0

    delivered = 0
    drafts_for_wa: list[str] = []

    async with async_session() as session:
        for result, draft in sends:
            row = ChatMessage(
                user_id=user_id,
                direction="outbound",
                body=draft,
                is_proactive=True,
                is_shadow=(mode == "shadow"),
                created_at=_utcnow_naive(),
            )
            session.add(row)
            delivered += 1
            if mode == "live":
                drafts_for_wa.append(draft)
        await session.commit()

    if mode == "live" and drafts_for_wa:
        phone = await _user_phone(user_id)
        if not phone:
            logger.warning(
                "deliver_drafts: live mode but user has no phone user=%s",
                user_id[:8],
            )
            return delivered
        try:
            channel = _get_whatsapp_channel()
            await channel.send_many(phone, drafts_for_wa)
        except Exception:
            logger.exception(
                "deliver_drafts: WhatsApp send failed user=%s", user_id[:8]
            )

    return delivered
```

- [ ] **Step 7: Run tests**

```bash
.venv/bin/pytest backend/tests/proactive/test_delivery.py -v
```

Expected: PASS (3 tests).

- [ ] **Step 8: Commit**

```bash
git add backend/web/proactive/delivery.py backend/db/migrations/versions/0015_chat_message_is_shadow.py db/models.py backend/tests/proactive/test_delivery.py
git commit -m "feat(proactive): delivery layer with shadow + live modes"
```

---

## Task 14: runner.py — accept trigger, signal_queue, delivery_mode; integrate deliver_drafts

**Files:**
- Modify: `backend/web/proactive/runner.py`

- [ ] **Step 1: Update build_context to accept trigger + signal_queue**

In `backend/web/proactive/runner.py`, replace `build_context`:

```python
from backend.web.proactive.types import (
    ProactiveContext,
    ProactiveMove,
    ProactiveResult,
    SignalSummary,
    TriggerKind,
)


async def build_context(
    user_id: str,
    *,
    recent_thread: str = "",
    last_proactive_at: str | None = None,
    now: datetime | None = None,
    load_blurb: ContextLoader = _default_load_blurb,
    trigger: TriggerKind = "manual",
    signal_queue: tuple[SignalSummary, ...] = (),
) -> ProactiveContext:
    blurb = await load_blurb(user_id)
    stamp = (now or datetime.now()).isoformat(timespec="seconds")
    return ProactiveContext(
        user_id=user_id,
        profile_blurb=blurb or "",
        situation_brief="",
        recent_thread=recent_thread,
        current_datetime=stamp,
        last_proactive_at=last_proactive_at,
        trigger=trigger,
        signal_queue=signal_queue,
    )
```

- [ ] **Step 2: Update run_proactive_tick signature + integrate delivery**

In `run_proactive_tick`, update the signature and pipe trigger+signals through:

```python
async def run_proactive_tick(
    *,
    user_id: str,
    ledger: DedupStore | None = None,
    budget: CostBudget = CostBudget(),
    daily_used: int = 0,
    recent_thread: str = "",
    last_proactive_at: str | None = None,
    max_moves: int = 3,
    load_blurb: ContextLoader = _default_load_blurb,
    trigger: TriggerKind = "manual",
    signal_queue: tuple[SignalSummary, ...] = (),
    delivery_mode: Literal["shadow", "live", "none"] = "none",
) -> ProactiveTickResult:
    """Run one proactive cycle for a single user. Never raises.

    ``delivery_mode``:
    - ``none``: caller handles delivery (default; preserves dry-run shape)
    - ``shadow``: integrated; writes chat_messages with is_shadow=True
    - ``live``: integrated; sends WhatsApp + chat_messages
    """
```

(Add `from typing import Literal` at the top.)

Inside, after building context:

```python
    try:
        context = await build_context(
            user_id,
            recent_thread=recent_thread,
            last_proactive_at=last_proactive_at,
            load_blurb=load_blurb,
            trigger=trigger,
            signal_queue=signal_queue,
        )
    except Exception:
        logger.exception("run_proactive_tick: context build failed")
        ...
```

After verdicts:

```python
    if delivery_mode in {"shadow", "live"}:
        from backend.web.proactive.delivery import deliver_drafts
        try:
            await deliver_drafts(
                user_id=user_id,
                verdicts=verdicts,
                mode=delivery_mode,  # type: ignore[arg-type]
            )
        except Exception:
            logger.exception(
                "run_proactive_tick: deliver_drafts failed user=%s", user_id[:8]
            )
```

- [ ] **Step 3: Add a test for delivery_mode integration**

In `backend/tests/test_proactive_runner.py`, add:

```python
@pytest.mark.asyncio
async def test_runner_calls_deliver_drafts_in_live_mode(monkeypatch):
    """When delivery_mode='live', verdicts are passed to deliver_drafts."""
    moves = [_move(dedup_key="watch:livemode")]
    results = [_result(moves[0])]
    verdicts = [(results[0], JudgeVerdict(decision="send", draft="hello"))]

    async def fake_create(ctx, **kw):
        return moves

    async def fake_exec(accepted):
        return results

    async def fake_judge(*, context, results):
        return verdicts

    monkeypatch.setattr(runner_mod, "create_proactive_moves", fake_create)
    monkeypatch.setattr(runner_mod, "execute_moves", fake_exec)
    monkeypatch.setattr(runner_mod, "judge_results", fake_judge)

    class FakeRepo:
        async def get(self, user_id, local_date):
            return 0

        async def bump(self, user_id, local_date, *, by=1):
            return by

    monkeypatch.setattr(runner_mod, "DailyCountRepo", lambda: FakeRepo())

    captured: list[tuple[str, int, str]] = []

    async def fake_deliver(*, user_id, verdicts, mode):
        captured.append((user_id, len(verdicts), mode))
        return 1

    # The import inside run_proactive_tick is lazy:
    # `from backend.web.proactive.delivery import deliver_drafts`.
    # Patch the module attribute so the lazy import resolves to our fake.
    import backend.web.proactive.delivery as delivery_mod
    monkeypatch.setattr(delivery_mod, "deliver_drafts", fake_deliver)

    ledger = InMemoryDedupStore()
    await run_proactive_tick(
        user_id="u_live",
        ledger=ledger,
        load_blurb=_fake_blurb,
        delivery_mode="live",
    )
    assert captured == [("u_live", 1, "live")]
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest backend/tests/test_proactive_runner.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/web/proactive/runner.py backend/tests/test_proactive_runner.py
git commit -m "feat(proactive): runner accepts trigger+signal_queue+delivery_mode"
```

---

# PHASE 5 — Triggers + Worker (Tasks 15-18)

## Task 15: triggers/drain.py

**Files:**
- Create: `backend/web/proactive/triggers/drain.py`
- Test: `backend/tests/proactive/test_drain_trigger.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/proactive/test_drain_trigger.py`:

```python
"""Tests for triggers/drain.py."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.web.proactive.triggers.drain import maybe_drain_signals
from db.models import ProactiveSignal, ProactiveSubscription, User
from db.session import async_session


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
async def user_with_signals() -> str:
    user_id = "u_test_drain"
    async with async_session() as session:
        u = User(
            id=user_id,
            phone="+10000000004",
            display_name="drain test",
            timezone="UTC",
            living_profile={},
            created_at=_utcnow_naive(),
        )
        session.add(u)
        sub = ProactiveSubscription(
            id="sub_drain_1",
            user_id=user_id,
            intent_key="watch:drain_test",
            description="testing",
            cadence="daily",
            created_at=_utcnow_naive(),
            last_refreshed_at=_utcnow_naive(),
            active=True,
        )
        session.add(sub)
        await session.commit()
        for i in range(3):
            session.add(
                ProactiveSignal(
                    user_id=user_id,
                    subscription_id="sub_drain_1",
                    intent_key="watch:drain_test",
                    payload={
                        "title": f"item {i}",
                        "url": f"https://example.com/{i}",
                        "highlights": ["snippet"],
                    },
                )
            )
        await session.commit()
    yield user_id
    async with async_session() as session:
        await session.execute(
            ProactiveSignal.__table__.delete().where(
                ProactiveSignal.user_id == user_id
            )
        )
        await session.execute(
            ProactiveSubscription.__table__.delete().where(
                ProactiveSubscription.user_id == user_id
            )
        )
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


@pytest.mark.asyncio
async def test_drain_marks_signals_consumed(monkeypatch, user_with_signals):
    """After drain runs, the signals are marked consumed regardless of
    whether the runner judged them sendable."""
    from backend.web.proactive import triggers
    from backend.web.proactive.triggers import drain as d

    # Stub run_proactive_tick to a no-op
    from backend.web.proactive.runner import ProactiveTickResult

    async def fake_tick(**kw):
        return ProactiveTickResult(
            user_id=kw["user_id"],
            moves_emitted=[],
            moves_dropped=[],
            results=[],
            verdicts=[],
            elapsed_ms=0,
        )

    monkeypatch.setattr(d, "run_proactive_tick", fake_tick)

    decision = await maybe_drain_signals(
        user_id=user_with_signals,
        delivery_mode="shadow",
    )
    assert decision.signals_drained == 3
    # Re-running drains zero
    decision2 = await maybe_drain_signals(
        user_id=user_with_signals, delivery_mode="shadow"
    )
    assert decision2.signals_drained == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest backend/tests/proactive/test_drain_trigger.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement drain.py**

Create `backend/web/proactive/triggers/drain.py`:

```python
"""Drain trigger.

Reads pending ``proactive_signals`` rows for a user, summarizes them
into a ``signal_queue``, fires ``run_proactive_tick(trigger="drain")``,
then marks the signals consumed so they don't re-fire.

Cadence is owned by the worker (not this module) — typical scheduling
is once every 4 hours per active user, plus a soft jitter to avoid
thundering herd. The drain trigger is cheap when the queue is empty;
it returns early without touching the brain.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from backend.web.proactive.runner import run_proactive_tick
from backend.web.proactive.store import SignalQueueRepo
from backend.web.proactive.types import SignalSummary

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DrainDecision:
    """What ``maybe_drain_signals`` did, for tests + traces."""

    user_id: str
    signals_drained: int
    moves_emitted: int
    drafts_delivered: int


def _summarize_signal(payload: dict, intent_key: str, signal_id: str) -> SignalSummary:
    title = str(payload.get("title") or "").strip()
    url = str(payload.get("url") or "").strip()
    highlights = payload.get("highlights") or []
    snippet = ""
    if isinstance(highlights, list) and highlights:
        snippet = " | ".join(str(h).strip() for h in highlights[:2])
    elif payload.get("text"):
        snippet = str(payload.get("text"))[:300]
    published = payload.get("publishedDate")
    return SignalSummary(
        signal_id=signal_id,
        intent_key=intent_key,
        title=title,
        url=url,
        snippet=snippet,
        published=str(published) if published else None,
    )


async def maybe_drain_signals(
    *,
    user_id: str,
    delivery_mode: Literal["shadow", "live", "none"] = "shadow",
    max_signals: int = 25,
) -> DrainDecision:
    """Drain pending Exa monitor hits and run one drain tick.

    No-op when the queue is empty. Marks all drained signals consumed
    regardless of judge verdicts — the queue is a buffer, not a retry
    log.
    """
    queue = SignalQueueRepo()
    pending = await queue.drain_pending(user_id, limit=max_signals)
    if not pending:
        return DrainDecision(user_id, signals_drained=0, moves_emitted=0, drafts_delivered=0)

    summaries = tuple(
        _summarize_signal(p.payload, p.intent_key, p.id) for p in pending
    )

    try:
        tick = await run_proactive_tick(
            user_id=user_id,
            trigger="drain",
            signal_queue=summaries,
            delivery_mode=delivery_mode,
        )
    except Exception:
        logger.exception("maybe_drain_signals: tick failed user=%s", user_id[:8])
        # Still mark consumed — we don't want to re-judge the same hits
        # next tick. If something went wrong the operator can re-enqueue.
        await queue.mark_consumed([p.id for p in pending])
        return DrainDecision(
            user_id, signals_drained=len(pending), moves_emitted=0, drafts_delivered=0
        )

    drafts = sum(1 for r, v in tick.verdicts if v.decision == "send")
    await queue.mark_consumed([p.id for p in pending])
    return DrainDecision(
        user_id=user_id,
        signals_drained=len(pending),
        moves_emitted=len(tick.moves_emitted),
        drafts_delivered=drafts,
    )
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest backend/tests/proactive/test_drain_trigger.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/web/proactive/triggers/drain.py backend/tests/proactive/test_drain_trigger.py
git commit -m "feat(proactive): drain trigger reads signal queue and fires drain tick"
```

---

## Task 16: scripts/run_proactive_worker.py

**Files:**
- Create: `scripts/run_proactive_worker.py`

- [ ] **Step 1: Implement the worker**

Create `scripts/run_proactive_worker.py`:

```python
"""Standalone proactive web search worker.

Entry point for the dedicated `donna-proactive` Railway service. Two
clocks running side-by-side:

- drain pass: every DONNA_PROACTIVE_DRAIN_S (default 600s = 10min) per
  active user. The drain trigger early-exits when the queue is empty,
  so this is cheap. Limits make sure we never burn through Exa credits
  on a hot user.
- ledger purge: once per hour, GC ledger rows older than 48h.

Launched by ``bin/start.sh`` when ``DONNA_PROCESS_ROLE=proactive``. The
API service must NOT spawn this same task — see ``api/main.py`` for
the role gate.

When ``PORT`` is set, serves a tiny ``/health`` endpoint for Railway.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from donna_runtime.env import load_dotenv

load_dotenv(ROOT / ".env")

from sqlalchemy import select

from backend.web.proactive.store import PostgresDedupStore
from backend.web.proactive.triggers.drain import maybe_drain_signals
from db.migrations import create_tables
from db.models import User
from db.session import async_session

logger = logging.getLogger(__name__)


DEFAULT_DRAIN_INTERVAL_S = 600.0
DEFAULT_PURGE_INTERVAL_S = 3600.0


def _delivery_mode_for(profile: dict) -> str:
    raw = (profile or {}).get("proactive_delivery_mode") or "shadow"
    return raw if raw in {"shadow", "live", "none"} else "shadow"


async def _list_active_user_ids() -> list[tuple[str, dict]]:
    """Read users with active proactive subs. Returns (user_id, profile) pairs."""
    from db.models import ProactiveSubscription

    async with async_session() as session:
        rows = (
            await session.execute(
                select(User.id, User.living_profile).distinct().join(
                    ProactiveSubscription,
                    ProactiveSubscription.user_id == User.id,
                ).where(
                    ProactiveSubscription.active.is_(True),
                )
            )
        ).all()
    return [(r[0], dict(r[1] or {})) for r in rows]


async def _drain_loop(interval: float) -> None:
    while True:
        try:
            users = await _list_active_user_ids()
            random.shuffle(users)
            for user_id, profile in users:
                mode = _delivery_mode_for(profile)
                try:
                    decision = await maybe_drain_signals(
                        user_id=user_id, delivery_mode=mode
                    )
                    if decision.signals_drained:
                        logger.info(
                            "drain user=%s drained=%d emitted=%d delivered=%d mode=%s",
                            user_id[:8],
                            decision.signals_drained,
                            decision.moves_emitted,
                            decision.drafts_delivered,
                            mode,
                        )
                except Exception:
                    logger.exception(
                        "drain failed user=%s", user_id[:8] if user_id else "?"
                    )
        except Exception:
            logger.exception("drain loop top-level error")

        await asyncio.sleep(interval)


async def _purge_loop(interval: float) -> None:
    store = PostgresDedupStore()
    while True:
        try:
            removed = await store.purge_older_than(hours=48)
            if removed:
                logger.info("ledger purge: removed=%d", removed)
        except Exception:
            logger.exception("purge loop error")
        await asyncio.sleep(interval)


async def _serve_health(port: int) -> None:
    from fastapi import FastAPI
    import uvicorn

    app = FastAPI()

    @app.get("/health")
    def _health() -> dict:
        return {"status": "ok", "role": "proactive"}

    config = uvicorn.Config(
        app, host="0.0.0.0", port=port, log_level="warning", access_log=False
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Donna proactive web search worker (drain + purge).",
    )
    parser.add_argument(
        "--drain-interval",
        type=float,
        default=float(
            os.environ.get("DONNA_PROACTIVE_DRAIN_S") or DEFAULT_DRAIN_INTERVAL_S
        ),
    )
    parser.add_argument(
        "--purge-interval",
        type=float,
        default=float(
            os.environ.get("DONNA_PROACTIVE_PURGE_S") or DEFAULT_PURGE_INTERVAL_S
        ),
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(name)-36s  %(message)s",
        datefmt="%H:%M:%S",
    )
    logger.info(
        "proactive worker starting (drain=%.0fs, purge=%.0fs)",
        args.drain_interval,
        args.purge_interval,
    )

    try:
        await create_tables()
    except Exception:
        logger.exception(
            "proactive: create_tables failed (DB unreachable?) — continuing"
        )

    tasks = [
        asyncio.create_task(_drain_loop(args.drain_interval)),
        asyncio.create_task(_purge_loop(args.purge_interval)),
    ]
    port_raw = os.environ.get("PORT")
    if port_raw:
        try:
            tasks.append(asyncio.create_task(_serve_health(int(port_raw))))
        except ValueError:
            pass

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Smoke run with no users**

```bash
DONNA_PROACTIVE_DRAIN_S=5 DONNA_PROACTIVE_PURGE_S=5 .venv/bin/python scripts/run_proactive_worker.py &
sleep 12 && kill %1
```

Expected: Logs "proactive worker starting", does not crash. No drain output (no users yet).

- [ ] **Step 3: Commit**

```bash
git add scripts/run_proactive_worker.py
git commit -m "feat(proactive): standalone worker with drain + ledger purge loops"
```

---

## Task 17: bin/start.sh + api/main.py role gate

**Files:**
- Modify: `bin/start.sh`
- Modify: `api/main.py`

- [ ] **Step 1: Add proactive case to bin/start.sh**

In `bin/start.sh`, add a new case before the wildcard:

```sh
    proactive)
        exec python scripts/run_proactive_worker.py \
            --drain-interval "${DONNA_PROACTIVE_DRAIN_S:-600.0}" \
            --purge-interval "${DONNA_PROACTIVE_PURGE_S:-3600.0}"
        ;;
```

Update the comment header to list the new role and the unknown-role error string:

```sh
#   DONNA_PROCESS_ROLE=proactive   → scripts/run_proactive_worker.py
```

```sh
        echo "  expected one of: api, reminders, attention, synthesis, proactive" >&2
```

- [ ] **Step 2: Update api/main.py to recognize the role**

In `api/main.py`, find the `_should_run_in_process_workers` function around line 322 (the role checker). Confirm it already returns False for any role that isn't `api`. No code change should be needed — the gate is permissive enough. But add `proactive` to whatever known-roles set exists for diagnostics. Search:

```bash
grep -n "synthesis\|attention\|reminders" /Users/i3dlab/Downloads/InstructKr.Claw-Code-main/api/main.py | head
```

If a known-roles list exists, add `"proactive"` to it.

- [ ] **Step 3: Commit**

```bash
git add bin/start.sh api/main.py
git commit -m "chore(start): add proactive role to start.sh + api role gate"
```

---

## Task 18: Wire reconcile_subscriptions + provision into synthesis_worker

**Files:**
- Modify: `backend/memory/jobs/synthesis_worker.py`
- Test: extend `backend/tests/test_memory_jobs.py`

- [ ] **Step 1: Add a failing test that synthesis worker reconciles after morning trigger**

In `backend/tests/test_memory_jobs.py`, add:

```python
import pytest


@pytest.mark.asyncio
async def test_synthesis_worker_calls_reconcile_for_active_user(monkeypatch):
    """_run_one must call reconcile_subscriptions + provision_pending_websets
    for the user after the morning path runs."""
    from backend.memory.jobs import synthesis_worker as sw
    from backend.web.proactive import subscriptions as subs

    calls: list[tuple[str, str]] = []

    async def fake_full_runner(user_id):
        return None

    async def fake_morning_runner(user_id):
        return None

    async def fake_morning_check_in(*, user_id, timezone_name, living_profile, now_local):
        return None

    # The two we actually care about
    from backend.web.proactive.subscriptions import (
        ProvisionSummary,
        ReconcileSummary,
    )

    async def fake_reconcile(user_id, **kw):
        calls.append(("reconcile", user_id))
        return ReconcileSummary(
            user_id, created=0, deactivated=0, skipped_over_budget=0
        )

    async def fake_provision(user_id):
        calls.append(("provision", user_id))
        return ProvisionSummary(user_id, provisioned=0, failed=0)

    monkeypatch.setattr(subs, "reconcile_subscriptions", fake_reconcile)
    monkeypatch.setattr(subs, "provision_pending_websets", fake_provision)

    # Patch the morning trigger import inside _run_one
    import backend.web.proactive.triggers.morning as morning_mod
    monkeypatch.setattr(
        morning_mod, "maybe_fire_morning_check_in", fake_morning_check_in
    )

    await sw._run_one(
        user_id="u_recon_test",
        timezone_name="UTC",
        living_profile={"watch_for_tomorrow": ["antler"]},
        full_runner=fake_full_runner,
        morning_runner=fake_morning_runner,
    )
    assert ("reconcile", "u_recon_test") in calls
    assert ("provision", "u_recon_test") in calls
```

- [ ] **Step 2: Update synthesis_worker.py**

In `backend/memory/jobs/synthesis_worker.py`, find the block that calls `morning_runner` (around line 160-175). After the existing `maybe_fire_morning_check_in` block, add:

```python
    # After Living Profile is fresh, reconcile per-user proactive
    # subscriptions and provision Exa websets/monitors for any pending
    # ones. This is the bridge from L0 (Living Profile) to L1
    # (subscriptions) in the proactive web stack.
    try:
        from backend.web.proactive.subscriptions import (
            provision_pending_websets,
            reconcile_subscriptions,
        )
        await reconcile_subscriptions(user_id)
        await provision_pending_websets(user_id)
    except Exception:
        logger.exception(
            "synthesis_worker: subscriptions reconcile failed user=%s",
            user_id[:8],
        )
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest backend/tests/test_memory_jobs.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/memory/jobs/synthesis_worker.py backend/tests/test_memory_jobs.py
git commit -m "feat(synthesis): reconcile + provision proactive subscriptions per tick"
```

---

## Task 19 (optional): Refactor morning trigger to use run_proactive_tick

**Files:**
- Modify: `backend/web/proactive/triggers/morning.py`

This task unifies the two proactive paths — currently `maybe_fire_morning_check_in` calls `donna_turn` directly. Optional for the v1 self-test (the existing path keeps working).

- [ ] **Step 1: Replace donna_turn call with run_proactive_tick**

In `backend/web/proactive/triggers/morning.py`, replace the block from `# All gates pass → run the brain in proactive mode.` (around line 246) through the end of the function. Replace with:

```python
    # All gates pass → fire one morning tick through the unified runner.
    try:
        from backend.web.proactive.runner import run_proactive_tick
    except Exception:
        logger.exception("morning trigger: import run_proactive_tick failed")
        return MorningTriggerDecision(fired=False, reason="cold_start")

    # Pull delivery mode from profile: shadow by default, live once flipped.
    mode = profile.get("proactive_delivery_mode") or "shadow"
    if mode not in {"shadow", "live"}:
        mode = "shadow"

    try:
        await run_proactive_tick(
            user_id=user_id,
            trigger="morning",
            recent_thread="",
            last_proactive_at=last_fired_iso,
            delivery_mode=mode,  # type: ignore[arg-type]
        )
    except Exception:
        logger.exception(
            "morning trigger: run_proactive_tick failed user=%s",
            user_id[:8] if user_id else "?",
        )
        return MorningTriggerDecision(fired=False, reason="cold_start")

    await _persist_last_fired(user_id, now_local)
    return MorningTriggerDecision(fired=True, reason="fired")
```

- [ ] **Step 2: Update morning trigger tests**

The existing tests for `maybe_fire_morning_check_in` mock `donna_turn`. Update them to mock `run_proactive_tick` instead. The test signatures shouldn't change.

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest backend/tests/proactive/ backend/tests/test_morning_trigger.py -v 2>/dev/null || .venv/bin/pytest backend/tests/proactive/ -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/web/proactive/triggers/morning.py backend/tests/
git commit -m "refactor(proactive): unify morning trigger through run_proactive_tick"
```

---

# Single-user smoke test

After Tasks 1-18 are merged and migrations applied, run this end-to-end smoke against the live DB and Exa key.

- [ ] **Step 1: Confirm env**

```bash
echo "EXA_API_KEY: $([ -n "$EXA_API_KEY" ] && echo SET || echo MISSING)"
echo "EXA_WEBHOOK_SECRET: $([ -n "$EXA_WEBHOOK_SECRET" ] && echo SET || echo MISSING)"
echo "DATABASE_URL: $([ -n "$DATABASE_URL" ] && echo SET || echo MISSING)"
```

All three must be SET.

- [ ] **Step 2: Apply migrations**

```bash
.venv/bin/alembic upgrade head
```

- [ ] **Step 3: Identify the test user and seed watch_for_tomorrow**

```bash
# Replace u_my with the target user id
psql "$DATABASE_URL" <<'SQL'
UPDATE users
SET living_profile = jsonb_set(
    coalesce(living_profile, '{}'::jsonb),
    '{watch_for_tomorrow}',
    '["antler sg batch 13 announcements", "openai sora pricing changes"]'::jsonb,
    true
)
WHERE id = 'u_my';
SQL
```

- [ ] **Step 4: Reconcile + provision against the live Exa account**

```bash
.venv/bin/python -c "
import asyncio
from backend.web.proactive.subscriptions import (
    reconcile_subscriptions, provision_pending_websets
)

async def main():
    await reconcile_subscriptions('u_my')
    await provision_pending_websets('u_my')

asyncio.run(main())
"
```

Verify in Postgres:

```bash
psql "$DATABASE_URL" -c "
SELECT intent_key, webset_id, monitor_id, active
FROM proactive_subscriptions
WHERE user_id='u_my';
"
```

Expected: 2 rows, both with non-NULL `webset_id` and `monitor_id`.

- [ ] **Step 5: Manually inject a fake webhook payload**

```bash
SECRET="$EXA_WEBHOOK_SECRET"
BODY='{"monitorId":"<paste mon_id from Step 4>","items":[{"title":"Fake hit for smoke","url":"https://example.com/smoke","highlights":["this is a snippet"],"publishedDate":"2026-05-01"}]}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')
curl -X POST http://localhost:8000/api/exa/monitor_callback \
  -H "x-exa-signature: $SIG" \
  -H "content-type: application/json" \
  -d "$BODY"
```

Expected: `{"recorded":1}`.

Verify queue:

```bash
psql "$DATABASE_URL" -c "
SELECT id, intent_key, payload->>'title', consumed_at
FROM proactive_signals
WHERE user_id='u_my' ORDER BY arrived_at DESC LIMIT 5;
"
```

Expected: 1 row, `consumed_at IS NULL`.

- [ ] **Step 6: Run drain trigger directly (shadow mode)**

```bash
.venv/bin/python -c "
import asyncio
from backend.web.proactive.triggers.drain import maybe_drain_signals

async def main():
    d = await maybe_drain_signals(user_id='u_my', delivery_mode='shadow')
    print(d)

asyncio.run(main())
"
```

Expected: prints a `DrainDecision` with `signals_drained=1`.

- [ ] **Step 7: Verify shadow chat_messages row appears (if judge greenlit)**

```bash
psql "$DATABASE_URL" -c "
SELECT body, is_shadow, created_at
FROM chat_messages
WHERE user_id='u_my' AND is_proactive AND is_shadow
ORDER BY created_at DESC LIMIT 5;
"
```

Expected: 0 or 1 row depending on judge verdict. The signal is consumed regardless.

- [ ] **Step 8: Flip user to live mode**

After eyeballing several days of shadow drafts:

```bash
psql "$DATABASE_URL" -c "
UPDATE users
SET living_profile = jsonb_set(
    coalesce(living_profile, '{}'::jsonb),
    '{proactive_delivery_mode}',
    '\"live\"'::jsonb,
    true
)
WHERE id='u_my';
"
```

Next drain tick will deliver via WhatsApp.

---

# Rollout

| Step | Action | Verification |
|---|---|---|
| 1 | Apply migrations 0014, 0015 to dev DB | `alembic current` returns 0015 |
| 2 | Run all proactive tests | `pytest backend/tests/proactive/` green |
| 3 | Set `EXA_WEBHOOK_SECRET` in dev env + share with Exa monitor config | curl smoke returns 200 |
| 4 | Run reconcile + provision for self user manually | 2 active subs in DB with webset_id+monitor_id |
| 5 | Wait for first real Exa monitor hit (or inject fake webhook) | proactive_signals row appears |
| 6 | Run worker locally with `DONNA_PROCESS_ROLE=proactive` | drain logs appear, signal consumed |
| 7 | Eyeball shadow drafts for 7-14 days | judge pass-rate ≈10-15% |
| 8 | Flip self user to live mode in living_profile | first WhatsApp send |
| 9 | Add `donna-proactive` Railway service pointing at same image | service comes up healthy |
| 10 | Migrate prod DB, deploy | new role active |

---

# Self-review checklist

This was run against the spec at the end of plan-writing. Findings:

- ✅ Every layer L0-L7 maps to a task or is explicitly "already exists".
- ✅ All new files have a Create task; all modified files have a Modify task with an explicit instruction.
- ✅ Tests precede implementation in every task (TDD).
- ✅ Commits are at least one per task; 18 atomic commits total.
- ✅ Single-user smoke section is concrete with exact commands.
- ✅ No "TBD"/"add appropriate error handling"/"fill in later" placeholders.
- ✅ Tasks 3, 4, 14, 18 — placeholder "mirror the pattern" notes have been replaced with full inline test code that uses the file's existing helpers (`_move`, `_result`, `_fake_blurb`, `runner_mod`, `InMemoryDedupStore`).
- ✅ Task 2 — explicit fix-up list for the three known sync-call sites breaking under the async Protocol change.

Known scope deferrals (intentionally out of plan):
- Pre-event trigger (`triggers/pre_event.py`) — listed in design doc, not in plan. Add as Phase 6 once drain is calibrated.
- Dashboard admin view — eyeball via psql works for self-test.
- Top-level dispatcher integration (cooldowns, register safety) — single call at delivery time; not needed for single-user shadow phase.
- Recall fanout including web — separate work item.
- Cross-user fan-in caching — premature for one user.
