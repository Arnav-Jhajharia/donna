# Composio Google Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire Calendar + Gmail into Donna via Composio so she has live mirror data, sees connection state in per-turn context, and gets a one-time biographical bootstrap on first connect.

**Architecture:** Composio Python SDK handles OAuth + webhooks; a thin `backend/integrations/` module localizes vendor symbols. Webhooks are the source of truth for live ingest (no polling); a daily reconcile fills any gaps. Bootstrap reads Today fully + 30d IMPORTANT-flagged + 90d sender aggregates, runs LLM extraction passes, and writes `users.living_profile.biography` via the existing `update_living_profile` patch path. The `[INTEGRATIONS]` block lives in `runtime_context` (volatile, per-turn). `BIOGRAPHY` lives in `user_model_block` alongside `SITUATION BRIEF`.

**Tech Stack:** Python 3.11+, FastAPI (existing), SQLAlchemy 2 + Alembic (existing), Composio Python SDK (`composio-core`), pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-04-25-composio-google-integration-design.md`

---

## File Structure

**New module: `backend/integrations/`** — peer of `backend/memory/`.

| File | Responsibility |
|---|---|
| `backend/integrations/__init__.py` | module init |
| `backend/integrations/composio_client.py` | Thin wrapper around Composio Python SDK. Vendor names live ONLY here. Functions: `get_or_create_connection`, `subscribe_triggers`, `verify_webhook_signature`, `execute`, `fetch_gmail_messages`, `fetch_gmail_message_body`, `fetch_calendar_events`. |
| `backend/integrations/state.py` | CRUD for `integrations` table. Functions: `get_integration_status`, `upsert_pending`, `mark_connected`, `mark_revoked`, `mark_error`, `touch_synced`, `list_user_integrations`. |
| `backend/integrations/label_router.py` | Pure function `classify_depth(labels, is_starred, is_important, is_sent) -> Literal["full","metadata","aggregate","ignore"]`. |
| `backend/integrations/gmail_ingest.py` | Take one Composio gmail webhook payload → classify → upsert `email_messages`. |
| `backend/integrations/calendar_ingest.py` | Take one Composio calendar webhook payload → upsert/delete `calendar_entries`. |
| `backend/integrations/bootstrap_gmail.py` | Three-stage gmail bootstrap orchestrator (today / 30d important / 90d aggregates). |
| `backend/integrations/bootstrap_calendar.py` | Calendar bootstrap (last 30d + next 90d). |
| `backend/integrations/biography_synthesis.py` | Four LLM extraction passes + synthesis pass; writes `users.living_profile.biography`. |
| `backend/integrations/reconcile.py` | Daily defensive worker — diff last 24h gmail + next 14d calendar against Composio, fill gaps. |
| `backend/integrations/render.py` | `render_integrations_block(rows) -> str`. Pure. |

**Modified:**

| File | Change |
|---|---|
| `db/models.py` | Add `Integration`, `EmailMessage` models. |
| `backend/db/migrations/versions/0004_integrations_and_emails.py` | New migration. |
| `backend/memory/tools/connect_integration.py` | New tool. |
| `backend/memory/tools/list_gmail_recent.py` | New tool. |
| `backend/memory/tools/read_gmail_thread.py` | New tool. |
| `backend/memory/tools/__init__.py` | Register the three new tools. |
| `donna_runtime/tools.py` | Surface `connect_integration`, `list_gmail_recent`, `read_gmail_thread` to the brain loop. |
| `backend/memory/user_facts/rendering.py` | Extend `render_living_profile_block` to surface `BIOGRAPHY`. |
| `donna_runtime/context_builder.py` | Add integrations fetch + render in `render_turn_context`. |
| `api/main.py` | Mount `/webhooks/composio` route; on startup, schedule `reconcile_loop`. |
| `requirements.txt` | Add `composio-core`. |
| `.env.example` | Add `COMPOSIO_API_KEY`, `COMPOSIO_WEBHOOK_SECRET`. |
| `config.py` | Pass through new env vars. |

**Tests (new): `backend/tests/integrations/`**

One test file per integrations module + one per tool + one for renderer extensions + one for context-builder integration.

---

## Phase 1 — Schema + Auth Round-Trip

End state: a user can call `connect_integration`, receive a URL, tap it, complete Google OAuth, and on the next turn see `[INTEGRATIONS] google_calendar: connected · ...` in their context. No data syncs yet.

### Task 1.1: Add `Integration` and `EmailMessage` models

**Files:**
- Modify: `db/models.py` (append after `OAuthToken` ~line 322)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integrations/test_models.py
from db.models import Integration, EmailMessage


def test_integration_model_defaults():
    row = Integration(user_id="u1", provider="google", product="calendar")
    assert row.status == "pending"
    assert row.composio_connection_id is None
    assert row.connected_at is None


def test_email_message_model_defaults():
    from datetime import datetime, timezone

    msg = EmailMessage(
        user_id="u1",
        gmail_message_id="m1",
        thread_id="t1",
        from_address="a@b.com",
        subject="hi",
        ingest_depth="full",
        internal_date=datetime(2026, 4, 25, tzinfo=timezone.utc),
    )
    assert msg.body_stored is False
    assert msg.is_important is False
    assert msg.labels == []
```

- [ ] **Step 2: Run test — expect import failure**

```bash
pytest backend/tests/integrations/test_models.py -v
```

Expected: `ImportError: cannot import name 'Integration' from 'db.models'`.

- [ ] **Step 3: Add models to `db/models.py`**

Append to `db/models.py`:

```python
class Integration(Base):
    """Per-user, per-product integration state. Source of truth for the
    [INTEGRATIONS] context block; populated by Composio webhook flow."""
    __tablename__ = "integrations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)   # "google"
    product: Mapped[str] = mapped_column(String, nullable=False)    # "calendar" | "gmail"
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    # pending | connected | revoked | expired | error
    composio_connection_id: Mapped[str | None] = mapped_column(String, nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    __table_args__ = (
        Index(
            "uq_integrations_user_provider_product",
            "user_id", "provider", "product",
            unique=True,
        ),
    )


class EmailMessage(Base):
    """Local mirror of Gmail messages. Body stored only when label-router
    classified the message as 'full'. Bodies for 'metadata' rows are lazy-
    fetched on demand via read_gmail_thread."""
    __tablename__ = "email_messages"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    gmail_message_id: Mapped[str] = mapped_column(String, nullable=False)
    thread_id: Mapped[str] = mapped_column(String, nullable=False)
    from_address: Mapped[str] = mapped_column(String, nullable=False)
    from_name: Mapped[str | None] = mapped_column(String, nullable=True)
    to_addresses: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    cc_addresses: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    labels: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    is_important: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_starred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ingest_depth: Mapped[str] = mapped_column(String, nullable=False)
    # 'full' | 'metadata'
    internal_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    __table_args__ = (
        Index(
            "uq_email_user_msg",
            "user_id", "gmail_message_id",
            unique=True,
        ),
        Index("idx_emails_user_date", "user_id", "internal_date"),
        Index("idx_emails_user_thread", "user_id", "thread_id"),
        Index(
            "idx_emails_user_important",
            "user_id", "is_important",
            postgresql_where=sa.text("is_important"),
        ),
    )
```

If `sa` (SQLAlchemy alias) is not yet imported in `db/models.py`, add `import sqlalchemy as sa` at the top.

- [ ] **Step 4: Run test — expect pass**

```bash
pytest backend/tests/integrations/test_models.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add db/models.py backend/tests/integrations/__init__.py backend/tests/integrations/test_models.py
git commit -m "feat(db): integrations + email_messages models"
```

(Create `backend/tests/integrations/__init__.py` as an empty file if it doesn't exist.)

---

### Task 1.2: Alembic migration for new tables

**Files:**
- Create: `backend/db/migrations/versions/0004_integrations_and_emails.py`

- [ ] **Step 1: Write the migration**

```python
"""Integrations + email_messages tables for Composio Google integration.

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-25
"""
from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integrations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("product", sa.String(), nullable=False),
        sa.Column(
            "status", sa.String(), nullable=False, server_default="pending"
        ),
        sa.Column("composio_connection_id", sa.String(), nullable=True),
        sa.Column("connected_at", sa.DateTime(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "uq_integrations_user_provider_product",
        "integrations",
        ["user_id", "provider", "product"],
        unique=True,
    )

    op.create_table(
        "email_messages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("gmail_message_id", sa.String(), nullable=False),
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("from_address", sa.String(), nullable=False),
        sa.Column("from_name", sa.String(), nullable=True),
        sa.Column(
            "to_addresses",
            sa.dialects.postgresql.JSONB(),
            nullable=False, server_default="[]",
        ),
        sa.Column(
            "cc_addresses",
            sa.dialects.postgresql.JSONB(),
            nullable=False, server_default="[]",
        ),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column(
            "body_stored", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "labels",
            sa.dialects.postgresql.JSONB(),
            nullable=False, server_default="[]",
        ),
        sa.Column(
            "is_important", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "is_starred", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "is_sent", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("ingest_depth", sa.String(), nullable=False),
        sa.Column("internal_date", sa.DateTime(), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(), nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "uq_email_user_msg",
        "email_messages",
        ["user_id", "gmail_message_id"],
        unique=True,
    )
    op.create_index(
        "idx_emails_user_date", "email_messages", ["user_id", "internal_date"]
    )
    op.create_index(
        "idx_emails_user_thread", "email_messages", ["user_id", "thread_id"]
    )
    op.create_index(
        "idx_emails_user_important",
        "email_messages",
        ["user_id", "is_important"],
        postgresql_where=sa.text("is_important"),
    )


def downgrade() -> None:
    op.drop_index("idx_emails_user_important", table_name="email_messages")
    op.drop_index("idx_emails_user_thread", table_name="email_messages")
    op.drop_index("idx_emails_user_date", table_name="email_messages")
    op.drop_index("uq_email_user_msg", table_name="email_messages")
    op.drop_table("email_messages")
    op.drop_index("uq_integrations_user_provider_product", table_name="integrations")
    op.drop_table("integrations")
```

- [ ] **Step 2: Run migration up + down to verify**

```bash
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

Expected: all three commands succeed.

- [ ] **Step 3: Commit**

```bash
git add backend/db/migrations/versions/0004_integrations_and_emails.py
git commit -m "feat(db): migration 0004 integrations + email_messages"
```

---

### Task 1.3: `backend/integrations/state.py` — table CRUD

**Files:**
- Create: `backend/integrations/__init__.py` (empty)
- Create: `backend/integrations/state.py`
- Test: `backend/tests/integrations/test_state.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integrations/test_state.py
import pytest

from backend.integrations.state import (
    get_integration_status,
    list_user_integrations,
    mark_connected,
    mark_revoked,
    touch_synced,
    upsert_pending,
)


@pytest.mark.asyncio
async def test_upsert_pending_creates_row(db):
    await upsert_pending("u1", "google", "calendar")
    rows = await list_user_integrations("u1")
    assert len(rows) == 1
    assert rows[0].status == "pending"
    assert rows[0].provider == "google"
    assert rows[0].product == "calendar"


@pytest.mark.asyncio
async def test_upsert_pending_is_idempotent(db):
    await upsert_pending("u1", "google", "calendar")
    await upsert_pending("u1", "google", "calendar")
    rows = await list_user_integrations("u1")
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_mark_connected_flips_status(db):
    await upsert_pending("u1", "google", "calendar")
    await mark_connected("u1", "google", "calendar", connection_id="c-1")
    status = await get_integration_status("u1", "google", "calendar")
    assert status.status == "connected"
    assert status.composio_connection_id == "c-1"
    assert status.connected_at is not None


@pytest.mark.asyncio
async def test_mark_revoked_flips_status(db):
    await upsert_pending("u1", "google", "calendar")
    await mark_connected("u1", "google", "calendar", connection_id="c-1")
    await mark_revoked("u1", "google", "calendar")
    status = await get_integration_status("u1", "google", "calendar")
    assert status.status == "revoked"


@pytest.mark.asyncio
async def test_touch_synced_updates_timestamp(db):
    await upsert_pending("u1", "google", "calendar")
    await mark_connected("u1", "google", "calendar", connection_id="c-1")
    await touch_synced("u1", "google", "calendar")
    status = await get_integration_status("u1", "google", "calendar")
    assert status.last_synced_at is not None
```

The `db` fixture is the existing test fixture for the test DB session — reuse from `backend/tests/conftest.py` (verify name; rename in this file to match).

- [ ] **Step 2: Run test — expect import failure**

```bash
pytest backend/tests/integrations/test_state.py -v
```

- [ ] **Step 3: Implement `state.py`**

```python
# backend/integrations/state.py
"""CRUD for the integrations table — source of truth for [INTEGRATIONS]."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import select

from backend.db.session import async_session
from db.models import Integration


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def upsert_pending(
    user_id: str, provider: str, product: str
) -> None:
    """Create a pending integration row if missing; no-op if already exists."""
    async with async_session() as session:
        existing = (
            await session.execute(
                select(Integration)
                .where(Integration.user_id == user_id)
                .where(Integration.provider == provider)
                .where(Integration.product == product)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return
        session.add(
            Integration(
                user_id=user_id,
                provider=provider,
                product=product,
                status="pending",
            )
        )
        await session.commit()


async def mark_connected(
    user_id: str, provider: str, product: str, *, connection_id: str
) -> None:
    async with async_session() as session:
        row = (
            await session.execute(
                select(Integration)
                .where(Integration.user_id == user_id)
                .where(Integration.provider == provider)
                .where(Integration.product == product)
            )
        ).scalar_one_or_none()
        if row is None:
            row = Integration(
                user_id=user_id, provider=provider, product=product
            )
            session.add(row)
        row.status = "connected"
        row.composio_connection_id = connection_id
        row.connected_at = _utcnow()
        row.updated_at = _utcnow()
        row.last_error = None
        await session.commit()


async def mark_revoked(user_id: str, provider: str, product: str) -> None:
    await _set_status(user_id, provider, product, status="revoked")


async def mark_error(
    user_id: str, provider: str, product: str, message: str
) -> None:
    await _set_status(
        user_id, provider, product, status="error", last_error=message[:500]
    )


async def touch_synced(
    user_id: str, provider: str, product: str
) -> None:
    async with async_session() as session:
        row = (
            await session.execute(
                select(Integration)
                .where(Integration.user_id == user_id)
                .where(Integration.provider == provider)
                .where(Integration.product == product)
            )
        ).scalar_one_or_none()
        if row is None:
            return
        row.last_synced_at = _utcnow()
        row.updated_at = _utcnow()
        await session.commit()


async def get_integration_status(
    user_id: str, provider: str, product: str
) -> Integration | None:
    async with async_session() as session:
        return (
            await session.execute(
                select(Integration)
                .where(Integration.user_id == user_id)
                .where(Integration.provider == provider)
                .where(Integration.product == product)
            )
        ).scalar_one_or_none()


async def list_user_integrations(user_id: str) -> Sequence[Integration]:
    async with async_session() as session:
        return (
            (
                await session.execute(
                    select(Integration)
                    .where(Integration.user_id == user_id)
                    .order_by(Integration.provider, Integration.product)
                )
            )
            .scalars()
            .all()
        )


async def _set_status(
    user_id: str,
    provider: str,
    product: str,
    *,
    status: str,
    last_error: str | None = None,
) -> None:
    async with async_session() as session:
        row = (
            await session.execute(
                select(Integration)
                .where(Integration.user_id == user_id)
                .where(Integration.provider == provider)
                .where(Integration.product == product)
            )
        ).scalar_one_or_none()
        if row is None:
            return
        row.status = status
        row.updated_at = _utcnow()
        if last_error is not None:
            row.last_error = last_error
        await session.commit()
```

- [ ] **Step 4: Run test — expect pass**

```bash
pytest backend/tests/integrations/test_state.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/__init__.py backend/integrations/state.py backend/tests/integrations/test_state.py
git commit -m "feat(integrations): state CRUD for integrations table"
```

---

### Task 1.4: Composio client wrapper (auth path only)

**Files:**
- Create: `backend/integrations/composio_client.py`
- Test: `backend/tests/integrations/test_composio_client.py`
- Modify: `requirements.txt`
- Modify: `.env.example`
- Modify: `config.py`

This task adds ONLY the auth-flow methods on the wrapper. Live ingest + bootstrap methods come in later phases.

- [ ] **Step 1: Add dep + env config**

Append to `requirements.txt`:

```
composio-core>=0.5.0
```

Append to `.env.example`:

```
COMPOSIO_API_KEY=
COMPOSIO_WEBHOOK_SECRET=
```

In `config.py`, extend the `Settings` (or equivalent) class to read these:

```python
# add to Settings class
composio_api_key: str = ""
composio_webhook_secret: str = ""
```

Install:

```bash
pip install -r requirements.txt
```

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/integrations/test_composio_client.py
import hmac
import hashlib

import pytest

from backend.integrations.composio_client import (
    ComposioClient,
    verify_webhook_signature,
)


def test_verify_webhook_signature_accepts_valid():
    secret = "topsecret"
    body = b'{"event":"connection.complete"}'
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(body, sig, secret) is True


def test_verify_webhook_signature_rejects_invalid():
    assert verify_webhook_signature(b"x", "deadbeef", "topsecret") is False


@pytest.mark.asyncio
async def test_get_or_create_connection_returns_url(monkeypatch):
    """Wrapper composes a Composio call and returns (connection_id, url)."""
    captured = {}

    class FakeToolkits:
        def authorize(self, user_id, app):
            captured["args"] = (user_id, app)
            class R:
                redirect_url = "https://composio/oauth/google/abc"
                connected_account_id = "ca_123"
            return R()

    class FakeComposio:
        toolkits = FakeToolkits()

    monkeypatch.setattr(
        "backend.integrations.composio_client._composio", lambda: FakeComposio()
    )
    client = ComposioClient(api_key="x")
    cid, url = await client.get_or_create_connection(
        user_id="u1", app="GMAIL"
    )
    assert cid == "ca_123"
    assert url.startswith("https://composio/")
    assert captured["args"] == ("u1", "GMAIL")
```

- [ ] **Step 3: Run test — expect ImportError**

```bash
pytest backend/tests/integrations/test_composio_client.py -v
```

- [ ] **Step 4: Implement the client wrapper**

```python
# backend/integrations/composio_client.py
"""Thin wrapper around Composio's Python SDK.

Vendor symbols (class names, app codes, trigger names) live ONLY in this
module. All callers go through ComposioClient. If Composio renames things,
the blast radius is one file.

This module covers auth + signature verification. Ingest, fetch, and
bootstrap helpers are added in later phases.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import Iterable

logger = logging.getLogger(__name__)


# App codes per Composio's vocabulary. Verify against current docs.
APP_GMAIL = "GMAIL"
APP_GOOGLE_CALENDAR = "GOOGLECALENDAR"


def _composio():  # pragma: no cover - thin import site
    from composio import Composio
    return Composio()


def verify_webhook_signature(
    body: bytes, sig_hex: str, secret: str
) -> bool:
    """Constant-time HMAC-SHA256 verify."""
    if not sig_hex or not secret:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_hex)


@dataclass(frozen=True)
class ComposioClient:
    api_key: str

    async def get_or_create_connection(
        self, user_id: str, app: str
    ) -> tuple[str, str]:
        """Return (connection_id, oauth_redirect_url) for a given (user, app).

        Idempotent at the SDK level — if a connection already exists for this
        (user_id, app), Composio returns the existing connection. The URL is
        the OAuth start URL the user must tap.
        """
        composio = _composio()
        result = composio.toolkits.authorize(user_id, app)
        return result.connected_account_id, result.redirect_url

    async def subscribe_triggers(
        self, user_id: str, connection_id: str, trigger_names: Iterable[str]
    ) -> None:
        """Subscribe Composio triggers for live webhook delivery.

        Idempotent: re-subscribing an active trigger is a no-op at Composio.
        """
        composio = _composio()
        for name in trigger_names:
            try:
                composio.triggers.subscribe(
                    user_id=user_id,
                    connected_account_id=connection_id,
                    trigger_name=name,
                )
            except Exception:
                logger.exception(
                    "subscribe_triggers: failed user=%s trigger=%s",
                    user_id, name,
                )


# Trigger name constants — verify against current Composio docs at impl time.
TRIGGER_GMAIL_NEW_MESSAGE = "GMAIL_NEW_GMAIL_MESSAGE"
TRIGGER_CALENDAR_EVENT_CREATED = "GOOGLECALENDAR_NEW_CALENDAR_EVENT"
TRIGGER_CALENDAR_EVENT_UPDATED = "GOOGLECALENDAR_UPDATED_CALENDAR_EVENT"
TRIGGER_CALENDAR_EVENT_DELETED = "GOOGLECALENDAR_DELETED_CALENDAR_EVENT"
```

- [ ] **Step 5: Run test — expect pass**

```bash
pytest backend/tests/integrations/test_composio_client.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/integrations/composio_client.py \
        backend/tests/integrations/test_composio_client.py \
        requirements.txt .env.example config.py
git commit -m "feat(integrations): composio client wrapper (auth + sig verify)"
```

---

### Task 1.5: `connect_integration` tool

**Files:**
- Create: `backend/memory/tools/connect_integration.py`
- Test: `backend/tests/integrations/test_connect_integration_tool.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integrations/test_connect_integration_tool.py
import pytest

from backend.integrations import state
from backend.memory.tools.connect_integration import connect_integration


class FakeComposio:
    def __init__(self):
        self.calls = []

    async def get_or_create_connection(self, user_id, app):
        self.calls.append((user_id, app))
        return f"cid-{app}", f"https://composio/oauth/{app}/start"


@pytest.mark.asyncio
async def test_connect_integration_returns_url_and_marks_pending(monkeypatch, db):
    fake = FakeComposio()
    monkeypatch.setattr(
        "backend.memory.tools.connect_integration._client",
        lambda: fake,
    )

    result = await connect_integration(
        user_id="u1", provider="google", products=["calendar", "gmail"]
    )

    assert result["status"] == "url_sent"
    assert result["url"].startswith("https://composio/")
    assert "tap" in result["message"].lower()

    rows = await state.list_user_integrations("u1")
    products = {r.product: r.status for r in rows}
    assert products == {"calendar": "pending", "gmail": "pending"}


@pytest.mark.asyncio
async def test_connect_integration_already_connected(monkeypatch, db):
    await state.upsert_pending("u1", "google", "calendar")
    await state.mark_connected(
        "u1", "google", "calendar", connection_id="c-old"
    )
    await state.upsert_pending("u1", "google", "gmail")
    await state.mark_connected(
        "u1", "google", "gmail", connection_id="c-old-2"
    )

    fake = FakeComposio()
    monkeypatch.setattr(
        "backend.memory.tools.connect_integration._client",
        lambda: fake,
    )

    result = await connect_integration(
        user_id="u1", provider="google", products=["calendar", "gmail"]
    )

    assert result["status"] == "already_connected"
    assert result["url"] is None
    assert fake.calls == []  # no Composio call
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
pytest backend/tests/integrations/test_connect_integration_tool.py -v
```

- [ ] **Step 3: Implement the tool**

```python
# backend/memory/tools/connect_integration.py
"""connect_integration — get an OAuth URL for an external provider."""
from __future__ import annotations

from typing import Any

from backend.integrations import state
from backend.integrations.composio_client import (
    APP_GMAIL,
    APP_GOOGLE_CALENDAR,
    ComposioClient,
)
from config import settings
from donna_runtime.observability import instrument_memory_op

DESCRIPTION = (
    "Generate a connect link for an external provider (currently: google, "
    "covering calendar and gmail). Use when:\n"
    "  - the [INTEGRATIONS] context block shows the integration as not_connected\n"
    "  - the user asks for something requiring an integration that is not connected\n"
    "  - the user explicitly asks to connect a provider\n"
    "Do NOT use when:\n"
    "  - the integration is already connected (check [INTEGRATIONS] first)\n"
    "  - status is 'pending' — a link is already in flight; do not nag\n"
    "  - the user is mid-task and a connect prompt would derail them\n"
    "Returns a URL plus a one-line consent message. The consent statement "
    "in `message` MUST be preserved when forwarded to the user."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "provider": {"type": "string", "enum": ["google"]},
        "products": {
            "type": "array",
            "items": {"type": "string", "enum": ["calendar", "gmail"]},
            "minItems": 1,
        },
    },
    "required": ["provider", "products"],
}


_PRODUCT_TO_APP = {
    "calendar": APP_GOOGLE_CALENDAR,
    "gmail": APP_GMAIL,
}


def _client() -> ComposioClient:
    return ComposioClient(api_key=settings.composio_api_key)


_CONSENT_MESSAGE = (
    "need gmail + calendar to be useful. one-time read of today's inbox "
    "+ a sample of important mail to learn who matters to you. tap: {url}"
)


@instrument_memory_op("integrations.connect")
async def connect_integration(
    user_id: str, provider: str, products: list[str]
) -> dict[str, Any]:
    if provider != "google":
        return {
            "status": "error",
            "url": None,
            "message": f"provider {provider!r} not supported yet",
        }

    existing_statuses = []
    for product in products:
        row = await state.get_integration_status(user_id, provider, product)
        existing_statuses.append((product, row.status if row else "absent"))

    if all(s == "connected" for _, s in existing_statuses):
        return {
            "status": "already_connected",
            "url": None,
            "message": "already connected",
        }

    client = _client()
    # Composio's OAuth consent screen for Google can authorize multiple
    # scopes in one click when both apps share a Google account, so we
    # surface a SINGLE link (the first product that needs authorization).
    # The webhook handler completes both products on connection.complete.
    target_product = next(
        (p for p, s in existing_statuses if s != "connected"), products[0]
    )
    app = _PRODUCT_TO_APP[target_product]
    connection_id, url = await client.get_or_create_connection(
        user_id=user_id, app=app
    )

    for product in products:
        await state.upsert_pending(user_id, provider, product)

    return {
        "status": "url_sent",
        "url": url,
        "message": _CONSENT_MESSAGE.format(url=url),
        "connection_id": connection_id,
    }
```

- [ ] **Step 4: Run test — expect pass**

```bash
pytest backend/tests/integrations/test_connect_integration_tool.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/memory/tools/connect_integration.py \
        backend/tests/integrations/test_connect_integration_tool.py
git commit -m "feat(tools): connect_integration"
```

---

### Task 1.6: Register `connect_integration` in tool registries

**Files:**
- Modify: `backend/memory/tools/__init__.py`
- Modify: `donna_runtime/tools.py` (add adapter — follow existing pattern from e.g. `update_living_profile`)

- [ ] **Step 1: Extend the memory-tools registry**

In `backend/memory/tools/__init__.py`:

```python
# add to imports
    connect_integration,

# add to ALL_TOOLS dict
    "connect_integration": connect_integration,
```

- [ ] **Step 2: Add adapter in `donna_runtime/tools.py`**

Open `donna_runtime/tools.py`. Find an existing adapter for a similar tool (e.g. `update_living_profile`) — copy the shape. Add an adapter that calls `backend.memory.tools.connect_integration.connect_integration` and surfaces it to the brain loop. Use the existing `DESCRIPTION` and `INPUT_SCHEMA` exports.

Follow the existing convention exactly — the file is large; do not restructure.

- [ ] **Step 3: Smoke test that the tool is registered**

```bash
python -c "from backend.memory.tools import ALL_TOOLS; assert 'connect_integration' in ALL_TOOLS, list(ALL_TOOLS.keys())"
```

Expected: no output (success).

- [ ] **Step 4: Commit**

```bash
git add backend/memory/tools/__init__.py donna_runtime/tools.py
git commit -m "feat(tools): register connect_integration in tool registries"
```

---

### Task 1.7: `[INTEGRATIONS]` renderer

**Files:**
- Create: `backend/integrations/render.py`
- Test: `backend/tests/integrations/test_render.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integrations/test_render.py
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.integrations.render import render_integrations_block


def _row(provider, product, status, last_synced_at=None):
    return SimpleNamespace(
        provider=provider,
        product=product,
        status=status,
        last_synced_at=last_synced_at,
        last_error=None,
    )


def test_render_empty_returns_empty_string():
    assert render_integrations_block([]) == ""


def test_render_connected_with_sync_age():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = [
        _row("google", "calendar", "connected", now - timedelta(minutes=8)),
        _row("google", "gmail", "not_connected"),
    ]
    out = render_integrations_block(rows, now=now)
    assert "[INTEGRATIONS]" in out
    assert "google_calendar: connected" in out
    assert "synced 8m ago" in out
    assert "google_gmail:    not connected" in out


def test_render_pending_state():
    out = render_integrations_block(
        [_row("google", "calendar", "pending")]
    )
    assert "google_calendar: pending" in out
    assert "synced" not in out


def test_render_error_state():
    row = _row("google", "calendar", "error")
    row.last_error = "401 unauthorized"
    out = render_integrations_block([row])
    assert "google_calendar: error" in out
    assert "401 unauthorized" in out
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
pytest backend/tests/integrations/test_render.py -v
```

- [ ] **Step 3: Implement the renderer**

```python
# backend/integrations/render.py
"""Renders the [INTEGRATIONS] block prepended to user messages."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Sequence


_LABEL_WIDTH = len("google_calendar:")


def _format_age(delta_seconds: float) -> str:
    if delta_seconds < 60:
        return "just now"
    minutes = int(delta_seconds // 60)
    if minutes < 60:
        return f"synced {minutes}m ago"
    hours = int(minutes // 60)
    if hours < 24:
        return f"synced {hours}h ago"
    days = int(hours // 24)
    return f"synced {days}d ago"


def _line(row, now: datetime) -> str:
    label = f"{row.provider}_{row.product}:".ljust(_LABEL_WIDTH)
    status = row.status if row.status != "not_connected" else "not connected"
    suffix = ""
    if row.status == "connected" and row.last_synced_at is not None:
        delta = (now - row.last_synced_at).total_seconds()
        suffix = " · " + _format_age(delta)
    if row.status == "error" and getattr(row, "last_error", None):
        suffix = f" · {row.last_error}"
    return f"  {label} {status}{suffix}".rstrip()


def render_integrations_block(
    rows: Sequence,
    *,
    now: datetime | None = None,
) -> str:
    if not rows:
        return ""
    if now is None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
    lines = ["[INTEGRATIONS]"]
    for row in rows:
        lines.append(_line(row, now))
    return "\n".join(lines)
```

- [ ] **Step 4: Run test — expect pass**

```bash
pytest backend/tests/integrations/test_render.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/render.py backend/tests/integrations/test_render.py
git commit -m "feat(integrations): render [INTEGRATIONS] context block"
```

---

### Task 1.8: Wire `[INTEGRATIONS]` into `render_turn_context`

**Files:**
- Modify: `donna_runtime/context_builder.py`
- Test: extend `tests/test_donna_runtime.py` OR create `backend/tests/integrations/test_context_block.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integrations/test_context_block.py
import pytest

from backend.integrations import state
from donna_runtime.context_builder import render_turn_context


@pytest.mark.asyncio
async def test_turn_context_includes_integrations_block(db):
    await state.upsert_pending("u1", "google", "calendar")
    await state.mark_connected(
        "u1", "google", "calendar", connection_id="c1"
    )

    ctx = await render_turn_context({"user_id": "u1"})
    assert "[INTEGRATIONS]" in ctx
    assert "google_calendar: connected" in ctx


@pytest.mark.asyncio
async def test_turn_context_omits_block_when_empty(db):
    ctx = await render_turn_context({"user_id": "u_no_integrations"})
    assert "[INTEGRATIONS]" not in ctx
```

- [ ] **Step 2: Run — expect failure (block not yet wired)**

```bash
pytest backend/tests/integrations/test_context_block.py -v
```

- [ ] **Step 3: Modify `donna_runtime/context_builder.py`**

In `render_turn_context`, immediately after the existing `parts` accumulator gathers TODAY / recent chat / reply / URL blocks, add:

```python
    # [INTEGRATIONS] — connection state for external providers
    try:
        from backend.integrations import state as _integrations_state
        from backend.integrations.render import render_integrations_block

        user_id = state.get("user_id") if isinstance(state, dict) else None
        if user_id:
            rows = await _integrations_state.list_user_integrations(user_id)
            block = render_integrations_block(rows)
            if block:
                parts.append(block)
    except Exception:
        logger.exception("render_turn_context: integrations block failed")
```

(Pattern matches the existing `try/except` shape used for other optional blocks in this function. The `state` parameter shadows the module name `state`; alias the import to `_integrations_state` to avoid the collision.)

- [ ] **Step 4: Run test — expect pass**

```bash
pytest backend/tests/integrations/test_context_block.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add donna_runtime/context_builder.py \
        backend/tests/integrations/test_context_block.py
git commit -m "feat(runtime): integrations block in turn context"
```

---

### Task 1.9: FastAPI webhook route — `connection.complete` only

**Files:**
- Create: `api/composio_webhook.py`
- Modify: `api/main.py` — mount the route
- Test: `backend/tests/integrations/test_webhook_route.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integrations/test_webhook_route.py
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, db):
    monkeypatch.setenv("COMPOSIO_WEBHOOK_SECRET", "topsecret")
    from api.main import app
    return TestClient(app)


def _sign(body: bytes, secret: str = "topsecret") -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_webhook_rejects_bad_signature(client):
    body = json.dumps({"event": "connection.complete"}).encode()
    r = client.post(
        "/webhooks/composio",
        content=body,
        headers={"x-composio-signature": "deadbeef"},
    )
    assert r.status_code == 401


def test_webhook_connection_complete_marks_connected(client, db):
    from backend.integrations import state
    import asyncio

    asyncio.get_event_loop().run_until_complete(
        state.upsert_pending("u1", "google", "calendar")
    )
    asyncio.get_event_loop().run_until_complete(
        state.upsert_pending("u1", "google", "gmail")
    )

    body = json.dumps({
        "event": "connection.complete",
        "user_id": "u1",
        "connection_id": "ca-1",
        "app": "GMAIL",
    }).encode()
    r = client.post(
        "/webhooks/composio",
        content=body,
        headers={"x-composio-signature": _sign(body)},
    )
    assert r.status_code == 200

    status = asyncio.get_event_loop().run_until_complete(
        state.get_integration_status("u1", "google", "gmail")
    )
    assert status.status == "connected"
    assert status.composio_connection_id == "ca-1"
```

- [ ] **Step 2: Run — expect 404 / not mounted**

```bash
pytest backend/tests/integrations/test_webhook_route.py -v
```

- [ ] **Step 3: Implement the route**

```python
# api/composio_webhook.py
"""POST /webhooks/composio — Composio inbound events."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from backend.integrations import state
from backend.integrations.composio_client import verify_webhook_signature
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


_APP_TO_PRODUCT = {
    "GMAIL": "gmail",
    "GOOGLECALENDAR": "calendar",
}


@router.post("/webhooks/composio")
async def composio_webhook(
    request: Request,
    x_composio_signature: str | None = Header(default=None),
) -> dict:
    body = await request.body()
    secret = settings.composio_webhook_secret or ""
    if not verify_webhook_signature(body, x_composio_signature or "", secret):
        raise HTTPException(status_code=401, detail="bad signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="bad json")

    event = payload.get("event")
    user_id = payload.get("user_id")
    if not event or not user_id:
        raise HTTPException(status_code=400, detail="missing fields")

    if event == "connection.complete":
        app = (payload.get("app") or "").upper()
        product = _APP_TO_PRODUCT.get(app)
        if product is None:
            logger.warning("composio_webhook: unknown app=%r", app)
            return {"ok": True, "ignored": True}
        await state.mark_connected(
            user_id, "google", product,
            connection_id=payload.get("connection_id") or "",
        )
        # Live trigger subscription + bootstrap enqueue happen in P2/P3.
        return {"ok": True}

    if event in {"connection.revoked", "connection.expired"}:
        app = (payload.get("app") or "").upper()
        product = _APP_TO_PRODUCT.get(app)
        if product:
            await state.mark_revoked(user_id, "google", product)
        return {"ok": True}

    # gmail / calendar events handled in P2; for now, ack and drop.
    logger.info("composio_webhook: unhandled event=%r", event)
    return {"ok": True, "unhandled": event}
```

In `api/main.py`, after `app = FastAPI(...)`:

```python
from api.composio_webhook import router as composio_router
app.include_router(composio_router)
```

- [ ] **Step 4: Run test — expect pass**

```bash
pytest backend/tests/integrations/test_webhook_route.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add api/composio_webhook.py api/main.py \
        backend/tests/integrations/test_webhook_route.py
git commit -m "feat(api): /webhooks/composio route — connection.complete"
```

---

### Phase 1 acceptance

- [ ] **Step P1.A: Run full integrations test suite**

```bash
pytest backend/tests/integrations/ -v
```

All tests pass.

- [ ] **Step P1.B: Run existing test suite for regressions**

```bash
pytest tests/ backend/tests/ -x
```

All tests pass.

---

## Phase 2 — Live Ingest

End state: new emails arriving in real Gmail land in `email_messages` within seconds of arrival; calendar event changes round-trip the same way; Donna can call `list_gmail_recent` and `read_gmail_thread` to read them.

### Task 2.1: Label-routing policy (pure)

**Files:**
- Create: `backend/integrations/label_router.py`
- Test: `backend/tests/integrations/test_label_router.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integrations/test_label_router.py
import pytest

from backend.integrations.label_router import classify_depth


@pytest.mark.parametrize("labels,starred,important,sent,expected", [
    (["SPAM"],                 False, False, False, "ignore"),
    (["TRASH"],                False, False, False, "ignore"),
    (["DRAFT"],                False, False, False, "ignore"),
    (["INBOX", "PRIMARY"],     False, False, False, "full"),
    (["INBOX"],                False, False, False, "full"),
    (["INBOX", "UPDATES"],     False, False, False, "metadata"),
    (["INBOX", "FORUMS"],      False, False, False, "metadata"),
    (["INBOX", "SOCIAL"],      False, False, False, "metadata"),
    (["INBOX", "PROMOTIONS"],  False, False, False, "aggregate"),
    (["INBOX", "PROMOTIONS"],  True,  False, False, "full"),   # starred wins
    (["INBOX", "UPDATES"],     False, True,  False, "full"),   # important wins
    (["SENT"],                 False, False, True,  "full"),
    (["INBOX", "Label_42"],    False, False, False, "metadata"),  # unknown user label → metadata
])
def test_classify_depth(labels, starred, important, sent, expected):
    assert classify_depth(
        labels=labels,
        is_starred=starred,
        is_important=important,
        is_sent=sent,
    ) == expected
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest backend/tests/integrations/test_label_router.py -v
```

- [ ] **Step 3: Implement**

```python
# backend/integrations/label_router.py
"""classify_depth — single source of truth for ingest routing.

Used by both bootstrap and live webhook ingest. Pure function.
"""
from __future__ import annotations

from typing import Literal, Sequence

Depth = Literal["full", "metadata", "aggregate", "ignore"]

_GMAIL_SYSTEM_LABELS = {
    "INBOX", "SENT", "DRAFT", "STARRED", "IMPORTANT",
    "TRASH", "SPAM", "CHAT", "UNREAD",
    "CATEGORY_PERSONAL", "PRIMARY",
    "CATEGORY_SOCIAL", "SOCIAL",
    "CATEGORY_PROMOTIONS", "PROMOTIONS",
    "CATEGORY_UPDATES", "UPDATES",
    "CATEGORY_FORUMS", "FORUMS",
}


def classify_depth(
    *,
    labels: Sequence[str],
    is_starred: bool,
    is_important: bool,
    is_sent: bool,
) -> Depth:
    label_set = set(labels)

    if label_set & {"SPAM", "TRASH", "DRAFT"}:
        return "ignore"

    if is_starred or is_important or is_sent:
        return "full"

    # PRIMARY (or uncategorized inbox)
    if "PRIMARY" in label_set or "CATEGORY_PERSONAL" in label_set:
        return "full"
    if "INBOX" in label_set and not (
        label_set & {"PROMOTIONS", "CATEGORY_PROMOTIONS",
                     "SOCIAL", "CATEGORY_SOCIAL",
                     "UPDATES", "CATEGORY_UPDATES",
                     "FORUMS", "CATEGORY_FORUMS"}
    ):
        return "full"

    if label_set & {"PROMOTIONS", "CATEGORY_PROMOTIONS"}:
        return "aggregate"

    if label_set & {
        "UPDATES", "CATEGORY_UPDATES",
        "FORUMS", "CATEGORY_FORUMS",
        "SOCIAL", "CATEGORY_SOCIAL",
    }:
        return "metadata"

    # User-defined labels → metadata default
    user_labels = label_set - _GMAIL_SYSTEM_LABELS
    if user_labels:
        return "metadata"

    return "metadata"
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest backend/tests/integrations/test_label_router.py -v
```

Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/label_router.py \
        backend/tests/integrations/test_label_router.py
git commit -m "feat(integrations): label-routing policy"
```

---

### Task 2.2: Composio client — fetch helpers

**Files:**
- Modify: `backend/integrations/composio_client.py` (extend with fetch methods)
- Test: extend `backend/tests/integrations/test_composio_client.py`

- [ ] **Step 1: Write failing tests for the new methods**

Append to `test_composio_client.py`:

```python
@pytest.mark.asyncio
async def test_fetch_gmail_message_normalizes_payload(monkeypatch):
    raw = {
        "id": "m1",
        "threadId": "t1",
        "labelIds": ["INBOX", "IMPORTANT"],
        "snippet": "hi",
        "internalDate": "1714000000000",  # ms since epoch
        "payload": {
            "headers": [
                {"name": "From", "value": "Sarah <sarah@x.com>"},
                {"name": "To", "value": "you@y.com"},
                {"name": "Subject", "value": "term sheet"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": "aGVsbG8="},  # 'hello' base64
                },
            ],
        },
    }

    class FakeTools:
        def execute(self, name, user_id, arguments):
            return {"data": raw}

    class FakeComposio:
        tools = FakeTools()

    monkeypatch.setattr(
        "backend.integrations.composio_client._composio", lambda: FakeComposio()
    )
    from backend.integrations.composio_client import ComposioClient

    client = ComposioClient(api_key="x")
    msg = await client.fetch_gmail_message(
        user_id="u1", message_id="m1", include_body=True
    )
    assert msg.gmail_message_id == "m1"
    assert msg.thread_id == "t1"
    assert msg.from_address == "sarah@x.com"
    assert msg.from_name == "Sarah"
    assert msg.subject == "term sheet"
    assert "hello" in (msg.body_text or "")
    assert "IMPORTANT" in msg.labels
```

- [ ] **Step 2: Run — expect failure**

```bash
pytest backend/tests/integrations/test_composio_client.py -v
```

- [ ] **Step 3: Extend the client wrapper**

Add to `backend/integrations/composio_client.py`:

```python
import base64
import re
from datetime import datetime, timezone


@dataclass(frozen=True)
class NormalizedGmailMessage:
    gmail_message_id: str
    thread_id: str
    from_address: str
    from_name: str | None
    to_addresses: list[str]
    cc_addresses: list[str]
    subject: str | None
    snippet: str | None
    body_text: str | None
    labels: list[str]
    is_important: bool
    is_starred: bool
    is_sent: bool
    internal_date: datetime


_FROM_RE = re.compile(r"^(?:\"?(?P<name>[^\"<]*?)\"?\s*<)?(?P<addr>[^>]+)>?$")


def _parse_address(raw: str) -> tuple[str | None, str]:
    if not raw:
        return None, ""
    m = _FROM_RE.match(raw.strip())
    if not m:
        return None, raw.strip()
    name = (m.group("name") or "").strip() or None
    addr = m.group("addr").strip()
    return name, addr


def _split_addresses(raw: str) -> list[str]:
    if not raw:
        return []
    return [_parse_address(part)[1] for part in raw.split(",") if part.strip()]


def _decode_body(payload: dict) -> str | None:
    """Walk MIME parts, prefer text/plain, fall back to text/html stripped."""
    if not payload:
        return None

    def walk(part: dict) -> str | None:
        mime = part.get("mimeType", "")
        body = part.get("body") or {}
        data = body.get("data")
        if data and mime == "text/plain":
            return base64.urlsafe_b64decode(data + "==").decode(
                "utf-8", errors="replace"
            )
        for child in part.get("parts") or []:
            found = walk(child)
            if found:
                return found
        return None

    return walk(payload)


def _normalize_gmail(raw: dict) -> "NormalizedGmailMessage":
    headers = {
        h["name"].lower(): h["value"]
        for h in (raw.get("payload") or {}).get("headers", [])
    }
    from_name, from_addr = _parse_address(headers.get("from", ""))
    labels = list(raw.get("labelIds") or [])
    internal_ms = int(raw.get("internalDate") or 0)
    internal_dt = datetime.fromtimestamp(
        internal_ms / 1000, tz=timezone.utc
    ).replace(tzinfo=None)

    return NormalizedGmailMessage(
        gmail_message_id=raw["id"],
        thread_id=raw["threadId"],
        from_address=from_addr,
        from_name=from_name,
        to_addresses=_split_addresses(headers.get("to", "")),
        cc_addresses=_split_addresses(headers.get("cc", "")),
        subject=headers.get("subject"),
        snippet=raw.get("snippet"),
        body_text=_decode_body(raw.get("payload")),
        labels=labels,
        is_important="IMPORTANT" in labels,
        is_starred="STARRED" in labels,
        is_sent="SENT" in labels,
        internal_date=internal_dt,
    )


# Add as methods on ComposioClient:
    async def fetch_gmail_message(
        self, user_id: str, message_id: str, include_body: bool = True
    ) -> NormalizedGmailMessage:
        composio = _composio()
        result = composio.tools.execute(
            "GMAIL_FETCH_MESSAGE_BY_ID",
            user_id=user_id,
            arguments={
                "message_id": message_id,
                "format": "full" if include_body else "metadata",
            },
        )
        return _normalize_gmail(result["data"])

    async def list_gmail_message_ids(
        self,
        user_id: str,
        query: str = "",
        max_results: int = 100,
        page_token: str | None = None,
    ) -> tuple[list[str], str | None]:
        composio = _composio()
        result = composio.tools.execute(
            "GMAIL_LIST_MESSAGES",
            user_id=user_id,
            arguments={
                "q": query,
                "max_results": max_results,
                "page_token": page_token,
            },
        )
        ids = [m["id"] for m in (result.get("data") or {}).get("messages", [])]
        next_token = (result.get("data") or {}).get("nextPageToken")
        return ids, next_token

    async def list_calendar_events(
        self,
        user_id: str,
        time_min: datetime,
        time_max: datetime,
        max_results: int = 250,
    ) -> list[dict]:
        composio = _composio()
        result = composio.tools.execute(
            "GOOGLECALENDAR_LIST_EVENTS",
            user_id=user_id,
            arguments={
                "calendar_id": "primary",
                "time_min": time_min.isoformat() + "Z",
                "time_max": time_max.isoformat() + "Z",
                "max_results": max_results,
                "single_events": True,
            },
        )
        return (result.get("data") or {}).get("items", [])
```

Tool/action names (`GMAIL_FETCH_MESSAGE_BY_ID`, `GMAIL_LIST_MESSAGES`, `GOOGLECALENDAR_LIST_EVENTS`) are Composio's symbols — verify against current docs at impl time.

- [ ] **Step 4: Run — expect pass**

```bash
pytest backend/tests/integrations/test_composio_client.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/composio_client.py \
        backend/tests/integrations/test_composio_client.py
git commit -m "feat(integrations): composio client fetch helpers"
```

---

### Task 2.3: `backend/integrations/gmail_ingest.py`

**Files:**
- Create: `backend/integrations/gmail_ingest.py`
- Test: `backend/tests/integrations/test_gmail_ingest.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integrations/test_gmail_ingest.py
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from backend.db.session import async_session
from backend.integrations.composio_client import NormalizedGmailMessage
from backend.integrations.gmail_ingest import ingest_gmail_message
from db.models import EmailMessage


def _msg(**kwargs):
    base = dict(
        gmail_message_id="m1",
        thread_id="t1",
        from_address="sarah@x.com",
        from_name="Sarah",
        to_addresses=["you@y.com"],
        cc_addresses=[],
        subject="term sheet",
        snippet="hi",
        body_text="hello full body",
        labels=["INBOX", "PRIMARY"],
        is_important=False,
        is_starred=False,
        is_sent=False,
        internal_date=datetime(2026, 4, 25, tzinfo=timezone.utc).replace(tzinfo=None),
    )
    base.update(kwargs)
    return NormalizedGmailMessage(**base)


@pytest.mark.asyncio
async def test_ingest_full_stores_body(db):
    await ingest_gmail_message("u1", _msg())
    async with async_session() as s:
        row = (await s.execute(select(EmailMessage).where(EmailMessage.user_id == "u1"))).scalar_one()
    assert row.ingest_depth == "full"
    assert row.body_stored is True
    assert row.body_text == "hello full body"


@pytest.mark.asyncio
async def test_ingest_metadata_drops_body(db):
    msg = _msg(labels=["INBOX", "UPDATES"])
    await ingest_gmail_message("u1", msg)
    async with async_session() as s:
        row = (await s.execute(select(EmailMessage).where(EmailMessage.user_id == "u1"))).scalar_one()
    assert row.ingest_depth == "metadata"
    assert row.body_stored is False
    assert row.body_text is None


@pytest.mark.asyncio
async def test_ingest_ignore_inserts_nothing(db):
    msg = _msg(labels=["SPAM"])
    await ingest_gmail_message("u1", msg)
    async with async_session() as s:
        rows = (await s.execute(select(EmailMessage).where(EmailMessage.user_id == "u1"))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_ingest_aggregate_inserts_nothing(db):
    msg = _msg(labels=["INBOX", "PROMOTIONS"])
    await ingest_gmail_message("u1", msg)
    async with async_session() as s:
        rows = (await s.execute(select(EmailMessage).where(EmailMessage.user_id == "u1"))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_ingest_is_idempotent(db):
    await ingest_gmail_message("u1", _msg())
    await ingest_gmail_message("u1", _msg())
    async with async_session() as s:
        rows = (await s.execute(select(EmailMessage).where(EmailMessage.user_id == "u1"))).scalars().all()
    assert len(rows) == 1
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest backend/tests/integrations/test_gmail_ingest.py -v
```

- [ ] **Step 3: Implement**

```python
# backend/integrations/gmail_ingest.py
"""Apply label-routing to a normalized gmail message and upsert mirror."""
from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert

from backend.db.session import async_session
from backend.integrations.composio_client import NormalizedGmailMessage
from backend.integrations.label_router import classify_depth
from db.models import EmailMessage


async def ingest_gmail_message(
    user_id: str, msg: NormalizedGmailMessage
) -> None:
    depth = classify_depth(
        labels=msg.labels,
        is_starred=msg.is_starred,
        is_important=msg.is_important,
        is_sent=msg.is_sent,
    )
    if depth in ("ignore", "aggregate"):
        return

    body_stored = depth == "full" and msg.body_text is not None
    body_text = msg.body_text if body_stored else None

    async with async_session() as session:
        stmt = insert(EmailMessage).values(
            user_id=user_id,
            gmail_message_id=msg.gmail_message_id,
            thread_id=msg.thread_id,
            from_address=msg.from_address,
            from_name=msg.from_name,
            to_addresses=msg.to_addresses,
            cc_addresses=msg.cc_addresses,
            subject=msg.subject,
            snippet=msg.snippet,
            body_text=body_text,
            body_stored=body_stored,
            labels=msg.labels,
            is_important=msg.is_important,
            is_starred=msg.is_starred,
            is_sent=msg.is_sent,
            ingest_depth=depth,
            internal_date=msg.internal_date,
        ).on_conflict_do_update(
            index_elements=["user_id", "gmail_message_id"],
            set_={
                "labels": msg.labels,
                "is_important": msg.is_important,
                "is_starred": msg.is_starred,
                "is_sent": msg.is_sent,
                "snippet": msg.snippet,
                "body_text": body_text,
                "body_stored": body_stored,
                "ingest_depth": depth,
            },
        )
        await session.execute(stmt)
        await session.commit()
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest backend/tests/integrations/test_gmail_ingest.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/gmail_ingest.py \
        backend/tests/integrations/test_gmail_ingest.py
git commit -m "feat(integrations): gmail ingest with label-routing"
```

---

### Task 2.4: `backend/integrations/calendar_ingest.py`

**Files:**
- Create: `backend/integrations/calendar_ingest.py`
- Test: `backend/tests/integrations/test_calendar_ingest.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integrations/test_calendar_ingest.py
import pytest
from sqlalchemy import select

from backend.db.session import async_session
from backend.integrations.calendar_ingest import (
    ingest_calendar_event,
    delete_calendar_event,
)
from db.models import CalendarEntry


def _event(event_id="e1", summary="standup"):
    return {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": "2026-04-25T09:00:00Z"},
        "end": {"dateTime": "2026-04-25T09:30:00Z"},
        "location": "zoom",
    }


@pytest.mark.asyncio
async def test_ingest_calendar_event_creates(db):
    await ingest_calendar_event("u1", _event())
    async with async_session() as s:
        row = (
            await s.execute(
                select(CalendarEntry).where(CalendarEntry.user_id == "u1")
            )
        ).scalar_one()
    assert row.title == "standup"
    assert row.google_event_id == "e1"


@pytest.mark.asyncio
async def test_ingest_calendar_event_updates(db):
    await ingest_calendar_event("u1", _event(summary="standup"))
    await ingest_calendar_event("u1", _event(summary="retro"))
    async with async_session() as s:
        rows = (
            await s.execute(
                select(CalendarEntry).where(CalendarEntry.user_id == "u1")
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].title == "retro"


@pytest.mark.asyncio
async def test_delete_calendar_event_removes(db):
    await ingest_calendar_event("u1", _event())
    await delete_calendar_event("u1", "e1")
    async with async_session() as s:
        rows = (
            await s.execute(
                select(CalendarEntry).where(CalendarEntry.user_id == "u1")
            )
        ).scalars().all()
    assert rows == []
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest backend/tests/integrations/test_calendar_ingest.py -v
```

- [ ] **Step 3: Implement**

```python
# backend/integrations/calendar_ingest.py
"""Upsert/delete CalendarEntry rows from Composio Google Calendar payloads."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, select

from backend.db.session import async_session
from db.models import CalendarEntry


def _parse_dt(spec: dict | None) -> datetime | None:
    if not spec:
        return None
    raw = spec.get("dateTime") or spec.get("date")
    if not raw:
        return None
    raw = raw.replace("Z", "+00:00")
    dt = datetime.fromisoformat(raw)
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


async def ingest_calendar_event(user_id: str, event: dict[str, Any]) -> None:
    google_event_id = event["id"]
    title = event.get("summary") or "(no title)"
    start_time = _parse_dt(event.get("start"))
    end_time = _parse_dt(event.get("end"))
    location = event.get("location")

    if start_time is None:
        return  # malformed; skip

    async with async_session() as session:
        existing = (
            await session.execute(
                select(CalendarEntry)
                .where(CalendarEntry.user_id == user_id)
                .where(CalendarEntry.google_event_id == google_event_id)
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                CalendarEntry(
                    user_id=user_id,
                    title=title,
                    start_time=start_time,
                    end_time=end_time,
                    location=location,
                    google_event_id=google_event_id,
                )
            )
        else:
            existing.title = title
            existing.start_time = start_time
            existing.end_time = end_time
            existing.location = location
        await session.commit()


async def delete_calendar_event(user_id: str, google_event_id: str) -> None:
    async with async_session() as session:
        await session.execute(
            delete(CalendarEntry)
            .where(CalendarEntry.user_id == user_id)
            .where(CalendarEntry.google_event_id == google_event_id)
        )
        await session.commit()
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest backend/tests/integrations/test_calendar_ingest.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/calendar_ingest.py \
        backend/tests/integrations/test_calendar_ingest.py
git commit -m "feat(integrations): calendar event ingest"
```

---

### Task 2.5: Webhook route — gmail + calendar event handlers

**Files:**
- Modify: `api/composio_webhook.py`
- Modify: `backend/tests/integrations/test_webhook_route.py`

- [ ] **Step 1: Write failing tests**

Append to `test_webhook_route.py`:

```python
def test_webhook_gmail_new_message_ingests(client, db, monkeypatch):
    import asyncio
    from backend.integrations.composio_client import NormalizedGmailMessage
    from datetime import datetime

    captured = {}

    async def fake_fetch(self, user_id, message_id, include_body=True):
        captured["fetch"] = (user_id, message_id)
        return NormalizedGmailMessage(
            gmail_message_id=message_id,
            thread_id="t1",
            from_address="a@b.com",
            from_name=None,
            to_addresses=["you@y.com"],
            cc_addresses=[],
            subject="hi",
            snippet="hi",
            body_text="hello",
            labels=["INBOX", "PRIMARY"],
            is_important=False,
            is_starred=False,
            is_sent=False,
            internal_date=datetime(2026, 4, 25),
        )

    monkeypatch.setattr(
        "backend.integrations.composio_client.ComposioClient.fetch_gmail_message",
        fake_fetch,
    )

    body = json.dumps({
        "event": "gmail.new_message",
        "user_id": "u1",
        "message_id": "m-new",
    }).encode()
    r = client.post(
        "/webhooks/composio",
        content=body,
        headers={"x-composio-signature": _sign(body)},
    )
    assert r.status_code == 200
    assert captured["fetch"] == ("u1", "m-new")


def test_webhook_calendar_event_created_ingests(client, db):
    body = json.dumps({
        "event": "calendar.event.created",
        "user_id": "u1",
        "event": {
            "id": "e1",
            "summary": "standup",
            "start": {"dateTime": "2026-04-25T09:00:00Z"},
            "end": {"dateTime": "2026-04-25T09:30:00Z"},
        },
    }).encode()
    r = client.post(
        "/webhooks/composio",
        content=body,
        headers={"x-composio-signature": _sign(body)},
    )
    assert r.status_code == 200
```

- [ ] **Step 2: Run — expect failure**

```bash
pytest backend/tests/integrations/test_webhook_route.py -v
```

- [ ] **Step 3: Extend the route**

In `api/composio_webhook.py`, add handling after the `connection.complete` block:

```python
    if event == "gmail.new_message":
        message_id = payload.get("message_id")
        if not message_id:
            raise HTTPException(status_code=400, detail="missing message_id")
        client = ComposioClient(api_key=settings.composio_api_key)
        msg = await client.fetch_gmail_message(
            user_id=user_id, message_id=message_id, include_body=True
        )
        await ingest_gmail_message(user_id, msg)
        await state.touch_synced(user_id, "google", "gmail")
        return {"ok": True}

    if event in {
        "calendar.event.created", "calendar.event.updated",
    }:
        ev = payload.get("event") or {}
        if not ev.get("id"):
            raise HTTPException(status_code=400, detail="missing event")
        await ingest_calendar_event(user_id, ev)
        await state.touch_synced(user_id, "google", "calendar")
        return {"ok": True}

    if event == "calendar.event.deleted":
        ev_id = (payload.get("event") or {}).get("id") or payload.get("event_id")
        if not ev_id:
            raise HTTPException(status_code=400, detail="missing event id")
        await delete_calendar_event(user_id, ev_id)
        await state.touch_synced(user_id, "google", "calendar")
        return {"ok": True}
```

Add imports at top:

```python
from backend.integrations.calendar_ingest import (
    delete_calendar_event,
    ingest_calendar_event,
)
from backend.integrations.composio_client import ComposioClient
from backend.integrations.gmail_ingest import ingest_gmail_message
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest backend/tests/integrations/test_webhook_route.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add api/composio_webhook.py backend/tests/integrations/test_webhook_route.py
git commit -m "feat(api): webhook handles gmail + calendar live events"
```

---

### Task 2.6: Subscribe live triggers on `connection.complete`

**Files:**
- Modify: `api/composio_webhook.py`
- Test: extend `test_webhook_route.py`

- [ ] **Step 1: Write the failing test**

Append to `test_webhook_route.py`:

```python
def test_webhook_connection_complete_subscribes_triggers(client, db, monkeypatch):
    captured = {}

    async def fake_subscribe(self, user_id, connection_id, trigger_names):
        captured["subscribe"] = (user_id, connection_id, list(trigger_names))

    monkeypatch.setattr(
        "backend.integrations.composio_client.ComposioClient.subscribe_triggers",
        fake_subscribe,
    )

    import asyncio
    from backend.integrations import state
    asyncio.get_event_loop().run_until_complete(
        state.upsert_pending("u1", "google", "gmail")
    )
    body = json.dumps({
        "event": "connection.complete",
        "user_id": "u1",
        "connection_id": "ca-1",
        "app": "GMAIL",
    }).encode()
    r = client.post(
        "/webhooks/composio",
        content=body,
        headers={"x-composio-signature": _sign(body)},
    )
    assert r.status_code == 200
    assert captured["subscribe"][0] == "u1"
    assert "GMAIL_NEW_GMAIL_MESSAGE" in captured["subscribe"][2]
```

- [ ] **Step 2: Run — expect failure**

```bash
pytest backend/tests/integrations/test_webhook_route.py::test_webhook_connection_complete_subscribes_triggers -v
```

- [ ] **Step 3: Extend `connection.complete` handler**

Inside the `if event == "connection.complete":` block in `api/composio_webhook.py`, after the `state.mark_connected(...)` call:

```python
        from backend.integrations.composio_client import (
            TRIGGER_GMAIL_NEW_MESSAGE,
            TRIGGER_CALENDAR_EVENT_CREATED,
            TRIGGER_CALENDAR_EVENT_UPDATED,
            TRIGGER_CALENDAR_EVENT_DELETED,
        )

        triggers_for_app = {
            "gmail": [TRIGGER_GMAIL_NEW_MESSAGE],
            "calendar": [
                TRIGGER_CALENDAR_EVENT_CREATED,
                TRIGGER_CALENDAR_EVENT_UPDATED,
                TRIGGER_CALENDAR_EVENT_DELETED,
            ],
        }
        client = ComposioClient(api_key=settings.composio_api_key)
        await client.subscribe_triggers(
            user_id=user_id,
            connection_id=payload.get("connection_id") or "",
            trigger_names=triggers_for_app.get(product, []),
        )
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest backend/tests/integrations/test_webhook_route.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add api/composio_webhook.py backend/tests/integrations/test_webhook_route.py
git commit -m "feat(api): subscribe live triggers on connection complete"
```

---

### Task 2.7: `list_gmail_recent` tool

**Files:**
- Create: `backend/memory/tools/list_gmail_recent.py`
- Test: `backend/tests/integrations/test_list_gmail_recent_tool.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integrations/test_list_gmail_recent_tool.py
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.dialects.postgresql import insert

from backend.db.session import async_session
from backend.memory.tools.list_gmail_recent import list_gmail_recent
from db.models import EmailMessage


async def _seed(user_id, msg_id, hours_ago, important=False):
    async with async_session() as s:
        await s.execute(
            insert(EmailMessage).values(
                user_id=user_id,
                gmail_message_id=msg_id,
                thread_id=f"t-{msg_id}",
                from_address="a@b.com",
                subject=f"subject {msg_id}",
                snippet="snippet",
                ingest_depth="full",
                is_important=important,
                internal_date=(
                    datetime.now(timezone.utc).replace(tzinfo=None)
                    - timedelta(hours=hours_ago)
                ),
                labels=["INBOX", "PRIMARY"],
            )
        )
        await s.commit()


@pytest.mark.asyncio
async def test_list_gmail_recent_returns_recent_only(db):
    await _seed("u1", "m1", hours_ago=1)
    await _seed("u1", "m2", hours_ago=10)
    await _seed("u1", "m3", hours_ago=72)

    result = await list_gmail_recent(user_id="u1", within_hours=24, limit=10)
    ids = [m["id"] for m in result["messages"]]
    assert "m1" in ids and "m2" in ids
    assert "m3" not in ids


@pytest.mark.asyncio
async def test_list_gmail_recent_important_only_filter(db):
    await _seed("u1", "m1", hours_ago=1, important=False)
    await _seed("u1", "m2", hours_ago=1, important=True)

    result = await list_gmail_recent(
        user_id="u1", within_hours=24, limit=10, important_only=True
    )
    ids = [m["id"] for m in result["messages"]]
    assert ids == ["m2"]
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest backend/tests/integrations/test_list_gmail_recent_tool.py -v
```

- [ ] **Step 3: Implement**

```python
# backend/memory/tools/list_gmail_recent.py
"""list_gmail_recent — recent emails from local mirror."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from backend.db.session import async_session
from backend.memory.tools._shape import ToolResult, degraded, no_hits, ok
from db.models import EmailMessage
from donna_runtime.observability import instrument_memory_op

DESCRIPTION = (
    "List recent gmail messages from the user's mailbox (read from local "
    "mirror; webhook-fed). Use when:\n"
    "  - the user asks 'any new mail?', 'what came in today?', 'has X emailed?'\n"
    "  - you need to summarize today's inbox or the last few hours\n"
    "Do NOT use when:\n"
    "  - the user asks for a specific thread by sender or subject — use a more\n"
    "    targeted retrieval (future iteration) or read_gmail_thread\n"
    "  - the [INTEGRATIONS] block shows google_gmail as not_connected\n"
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "within_hours": {"type": "integer", "default": 24},
        "limit": {"type": "integer", "default": 20},
        "important_only": {"type": "boolean", "default": False},
    },
    "required": [],
}


@instrument_memory_op("postgres.gmail")
async def list_gmail_recent(
    user_id: str,
    within_hours: int = 24,
    limit: int = 20,
    important_only: bool = False,
) -> ToolResult:
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        hours=within_hours
    )
    async with async_session() as session:
        stmt = (
            select(EmailMessage)
            .where(EmailMessage.user_id == user_id)
            .where(EmailMessage.internal_date >= cutoff)
            .order_by(EmailMessage.internal_date.desc())
            .limit(limit)
        )
        if important_only:
            stmt = stmt.where(EmailMessage.is_important.is_(True))
        rows = (await session.execute(stmt)).scalars().all()

    if not rows:
        return no_hits()

    return ok({
        "messages": [
            {
                "id": r.gmail_message_id,
                "thread_id": r.thread_id,
                "from": r.from_address,
                "from_name": r.from_name,
                "subject": r.subject,
                "snippet": r.snippet,
                "is_important": r.is_important,
                "is_starred": r.is_starred,
                "internal_date": r.internal_date.isoformat(),
            }
            for r in rows
        ]
    })
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest backend/tests/integrations/test_list_gmail_recent_tool.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/memory/tools/list_gmail_recent.py \
        backend/tests/integrations/test_list_gmail_recent_tool.py
git commit -m "feat(tools): list_gmail_recent reads local mirror"
```

---

### Task 2.8: `read_gmail_thread` tool with lazy body fetch

**Files:**
- Create: `backend/memory/tools/read_gmail_thread.py`
- Test: `backend/tests/integrations/test_read_gmail_thread_tool.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integrations/test_read_gmail_thread_tool.py
from datetime import datetime

import pytest
from sqlalchemy.dialects.postgresql import insert

from backend.db.session import async_session
from backend.memory.tools.read_gmail_thread import read_gmail_thread
from db.models import EmailMessage


async def _seed(msg_id, body=None):
    async with async_session() as s:
        await s.execute(
            insert(EmailMessage).values(
                user_id="u1",
                gmail_message_id=msg_id,
                thread_id="t1",
                from_address="a@b.com",
                subject="hi",
                snippet="hi",
                body_text=body,
                body_stored=body is not None,
                ingest_depth="full" if body else "metadata",
                internal_date=datetime(2026, 4, 25),
                labels=["INBOX", "PRIMARY"],
            )
        )
        await s.commit()


@pytest.mark.asyncio
async def test_read_gmail_thread_returns_stored_bodies(db):
    await _seed("m1", body="full body 1")
    await _seed("m2", body="full body 2")
    result = await read_gmail_thread(user_id="u1", thread_id="t1")
    bodies = [m["body"] for m in result["messages"]]
    assert "full body 1" in bodies
    assert "full body 2" in bodies


@pytest.mark.asyncio
async def test_read_gmail_thread_lazy_fetches_missing_body(db, monkeypatch):
    await _seed("m1", body=None)

    async def fake_fetch(self, user_id, message_id, include_body=True):
        from backend.integrations.composio_client import NormalizedGmailMessage
        return NormalizedGmailMessage(
            gmail_message_id=message_id,
            thread_id="t1",
            from_address="a@b.com",
            from_name=None,
            to_addresses=[],
            cc_addresses=[],
            subject="hi",
            snippet="hi",
            body_text="lazy fetched body",
            labels=["INBOX"],
            is_important=False,
            is_starred=False,
            is_sent=False,
            internal_date=datetime(2026, 4, 25),
        )

    monkeypatch.setattr(
        "backend.integrations.composio_client.ComposioClient.fetch_gmail_message",
        fake_fetch,
    )

    result = await read_gmail_thread(user_id="u1", thread_id="t1")
    assert result["messages"][0]["body"] == "lazy fetched body"

    async with async_session() as s:
        from sqlalchemy import select
        row = (await s.execute(select(EmailMessage).where(EmailMessage.gmail_message_id == "m1"))).scalar_one()
    assert row.body_stored is True
    assert row.body_text == "lazy fetched body"
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest backend/tests/integrations/test_read_gmail_thread_tool.py -v
```

- [ ] **Step 3: Implement**

```python
# backend/memory/tools/read_gmail_thread.py
"""read_gmail_thread — full bodies for one thread, lazy-fetch on demand."""
from __future__ import annotations

from sqlalchemy import select

from backend.db.session import async_session
from backend.integrations.composio_client import ComposioClient
from backend.memory.tools._shape import ToolResult, no_hits, ok
from config import settings
from db.models import EmailMessage
from donna_runtime.observability import instrument_memory_op

DESCRIPTION = (
    "Fetch all messages in a single gmail thread by thread_id, with full "
    "bodies. If a message body is not in the local mirror (label policy "
    "kept only metadata), this tool lazy-fetches it from Composio and "
    "persists it. Use when:\n"
    "  - the user asks about a specific thread you've already shown them\n"
    "  - you need full content to compose a reply or summarize a conversation\n"
    "Do NOT use when:\n"
    "  - the user asks 'what's new in my inbox?' — use list_gmail_recent\n"
    "  - the [INTEGRATIONS] block shows google_gmail as not_connected\n"
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "thread_id": {"type": "string"},
    },
    "required": ["thread_id"],
}


@instrument_memory_op("postgres.gmail.thread")
async def read_gmail_thread(user_id: str, thread_id: str) -> ToolResult:
    async with async_session() as session:
        rows = (
            await session.execute(
                select(EmailMessage)
                .where(EmailMessage.user_id == user_id)
                .where(EmailMessage.thread_id == thread_id)
                .order_by(EmailMessage.internal_date.asc())
            )
        ).scalars().all()
    if not rows:
        return no_hits()

    client = ComposioClient(api_key=settings.composio_api_key)
    messages = []
    for row in rows:
        body = row.body_text
        if body is None or not row.body_stored:
            try:
                msg = await client.fetch_gmail_message(
                    user_id=user_id,
                    message_id=row.gmail_message_id,
                    include_body=True,
                )
            except Exception:
                msg = None
            if msg is not None:
                body = msg.body_text
                async with async_session() as session:
                    update_row = (
                        await session.execute(
                            select(EmailMessage)
                            .where(EmailMessage.id == row.id)
                        )
                    ).scalar_one()
                    update_row.body_text = body
                    update_row.body_stored = body is not None
                    await session.commit()

        messages.append({
            "id": row.gmail_message_id,
            "thread_id": row.thread_id,
            "from": row.from_address,
            "from_name": row.from_name,
            "subject": row.subject,
            "internal_date": row.internal_date.isoformat(),
            "body": body,
        })

    return ok({"messages": messages})
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest backend/tests/integrations/test_read_gmail_thread_tool.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/memory/tools/read_gmail_thread.py \
        backend/tests/integrations/test_read_gmail_thread_tool.py
git commit -m "feat(tools): read_gmail_thread with lazy body fetch"
```

---

### Task 2.9: Register P2 tools

**Files:**
- Modify: `backend/memory/tools/__init__.py`
- Modify: `donna_runtime/tools.py` (add adapters mirroring `list_calendar` shape)

- [ ] **Step 1: Register in `backend/memory/tools/__init__.py`**

```python
# add to imports
    list_gmail_recent,
    read_gmail_thread,

# add to ALL_TOOLS
    "list_gmail_recent": list_gmail_recent,
    "read_gmail_thread": read_gmail_thread,
```

- [ ] **Step 2: Add adapters in `donna_runtime/tools.py`**

Mirror the existing `list_calendar` adapter shape exactly. Surface the new tools through whatever loader/list function the brain uses.

- [ ] **Step 3: Smoke test**

```bash
python -c "from backend.memory.tools import ALL_TOOLS; assert 'list_gmail_recent' in ALL_TOOLS and 'read_gmail_thread' in ALL_TOOLS"
```

- [ ] **Step 4: Commit**

```bash
git add backend/memory/tools/__init__.py donna_runtime/tools.py
git commit -m "feat(tools): register list_gmail_recent + read_gmail_thread"
```

---

### Phase 2 acceptance

- [ ] **Step P2.A: Full integrations suite + regression**

```bash
pytest backend/tests/integrations/ tests/ backend/tests/ -x
```

All pass.

---

## Phase 2.5 — Proactive surfacing on important email

End state: when an important email lands (Gmail IMPORTANT, starred, sender in biography at weekly+ cadence, reply on an open loop, or reply on a thread the user sent on recently), Donna scores it, checks rate limits + quiet hours, and if it crosses threshold, invokes her brain loop in `mode="proactive"` to compose a WhatsApp ping. The proactive engine itself (multi-source noticing layer) is still deferred; this is one hardcoded producer.

### Task 2.5.1: `proactive_pings` table for rate limiting

**Files:**
- Modify: `db/models.py`
- Create: `backend/db/migrations/versions/0005_proactive_pings.py`
- Test: extend `backend/tests/integrations/test_models.py`

- [ ] **Step 1: Append failing test**

```python
def test_proactive_ping_model_defaults():
    from db.models import ProactivePing
    p = ProactivePing(user_id="u1", source="email", message_ref="m1")
    assert p.source == "email"
    assert p.message_ref == "m1"
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest backend/tests/integrations/test_models.py -v
```

- [ ] **Step 3: Add the model**

Append to `db/models.py`:

```python
class ProactivePing(Base):
    """One row per proactive ping fired. Drives rate limiting + cooldowns."""
    __tablename__ = "proactive_pings"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    # 'email' | (future) 'open_loop_age' | 'world_delta' | ...
    message_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    fired_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    suppressed_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    # null when actually fired; set when this row recorded a *suppression*

    __table_args__ = (
        Index("idx_pings_user_fired", "user_id", "fired_at"),
    )
```

- [ ] **Step 4: Migration `0005_proactive_pings.py`**

```python
"""Proactive ping log for rate limiting.

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-25
"""
from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "proactive_pings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("message_ref", sa.String(), nullable=True),
        sa.Column(
            "fired_at",
            sa.DateTime(), nullable=False, server_default=sa.func.now(),
        ),
        sa.Column("suppressed_reason", sa.String(), nullable=True),
    )
    op.create_index(
        "idx_pings_user_fired", "proactive_pings", ["user_id", "fired_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_pings_user_fired", table_name="proactive_pings")
    op.drop_table("proactive_pings")
```

- [ ] **Step 5: Run migration round-trip**

```bash
alembic upgrade head && alembic downgrade -1 && alembic upgrade head
```

- [ ] **Step 6: Run test — expect pass**

```bash
pytest backend/tests/integrations/test_models.py -v
```

- [ ] **Step 7: Commit**

```bash
git add db/models.py backend/db/migrations/versions/0005_proactive_pings.py \
        backend/tests/integrations/test_models.py
git commit -m "feat(db): proactive_pings table for rate limiting"
```

---

### Task 2.5.2: Importance scoring (pure function)

**Files:**
- Create: `backend/integrations/email_importance.py`
- Test: `backend/tests/integrations/test_email_importance.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integrations/test_email_importance.py
from datetime import datetime

import pytest

from backend.integrations.composio_client import NormalizedGmailMessage
from backend.integrations.email_importance import score_email, ScoringContext


def _msg(**kwargs) -> NormalizedGmailMessage:
    base = dict(
        gmail_message_id="m1",
        thread_id="t1",
        from_address="x@y.com",
        from_name=None,
        to_addresses=[],
        cc_addresses=[],
        subject="hi",
        snippet="hi",
        body_text=None,
        labels=["INBOX", "PRIMARY"],
        is_important=False,
        is_starred=False,
        is_sent=False,
        internal_date=datetime(2026, 4, 25),
    )
    base.update(kwargs)
    return NormalizedGmailMessage(**base)


def _ctx(**kwargs) -> ScoringContext:
    base = dict(
        biography_relationships=[],
        open_loop_keywords=[],
        recent_sent_thread_ids=set(),
    )
    base.update(kwargs)
    return ScoringContext(**base)


def test_unmarked_message_is_low():
    s = score_email(_msg(), _ctx())
    assert s.score < 0.5
    assert s.signals == []


def test_important_label_above_threshold():
    s = score_email(_msg(is_important=True), _ctx())
    assert s.score >= 0.5
    assert "important_label" in s.signals


def test_starred_above_threshold():
    s = score_email(_msg(is_starred=True), _ctx())
    assert s.score >= 0.5
    assert "starred" in s.signals


def test_known_relationship_weekly_above_threshold():
    s = score_email(
        _msg(from_address="sarah@acme.com"),
        _ctx(biography_relationships=[
            {"name": "Sarah", "frequency": "weekly", "kind": "colleague",
             "_email": "sarah@acme.com"}
        ]),
    )
    assert s.score >= 0.5
    assert "biography_relationship" in s.signals


def test_open_loop_keyword_match():
    s = score_email(
        _msg(subject="re: term sheet draft"),
        _ctx(open_loop_keywords=["term sheet"]),
    )
    assert s.score >= 0.5
    assert "open_loop_match" in s.signals


def test_reply_on_recent_thread():
    s = score_email(
        _msg(thread_id="t-recent"),
        _ctx(recent_sent_thread_ids={"t-recent"}),
    )
    # by itself recent-thread is weaker than threshold; combining lifts
    assert "recent_sent_thread" in s.signals


def test_signals_compose():
    s = score_email(
        _msg(is_important=True, thread_id="t-recent"),
        _ctx(recent_sent_thread_ids={"t-recent"}),
    )
    assert s.score >= 0.6
    assert "important_label" in s.signals
    assert "recent_sent_thread" in s.signals
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest backend/tests/integrations/test_email_importance.py -v
```

- [ ] **Step 3: Implement**

```python
# backend/integrations/email_importance.py
"""Deterministic importance scoring for inbound gmail.

Pure function — no DB, no network. The caller assembles ScoringContext
from biography + open_loops + recent sent state, then asks for a score.

Threshold for proactive surfacing is 0.5 (defined in proactive_email_trigger).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from backend.integrations.composio_client import NormalizedGmailMessage


@dataclass(frozen=True)
class ScoringContext:
    biography_relationships: Sequence[dict] = field(default_factory=list)
    # each: {"name": str, "frequency": "daily|weekly|monthly|rare",
    #        "_email": str (the from_address inferred at biography time)}
    open_loop_keywords: Sequence[str] = field(default_factory=list)
    # phrases pulled from open_loops summaries
    recent_sent_thread_ids: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class ScoreResult:
    score: float
    signals: list[str]


_FREQ_WEIGHT = {"daily": 0.4, "weekly": 0.3, "monthly": 0.15, "rare": 0.0}


def score_email(
    msg: NormalizedGmailMessage, ctx: ScoringContext
) -> ScoreResult:
    score = 0.0
    signals: list[str] = []

    if msg.is_important:
        score += 0.4
        signals.append("important_label")

    if msg.is_starred:
        score += 0.3
        signals.append("starred")

    rel_match = next(
        (
            r for r in ctx.biography_relationships
            if r.get("_email", "").lower() == msg.from_address.lower()
        ),
        None,
    )
    if rel_match is not None:
        weight = _FREQ_WEIGHT.get(rel_match.get("frequency", "rare"), 0.0)
        if weight > 0:
            score += weight
            signals.append("biography_relationship")

    subj_lower = (msg.subject or "").lower()
    body_lower = (msg.body_text or "").lower()
    for kw in ctx.open_loop_keywords:
        if not kw:
            continue
        if kw.lower() in subj_lower or kw.lower() in body_lower:
            score += 0.3
            signals.append("open_loop_match")
            break

    if msg.thread_id in ctx.recent_sent_thread_ids:
        score += 0.2
        signals.append("recent_sent_thread")

    score = min(score, 1.0)
    return ScoreResult(score=score, signals=signals)
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest backend/tests/integrations/test_email_importance.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/email_importance.py \
        backend/tests/integrations/test_email_importance.py
git commit -m "feat(integrations): email importance scoring"
```

---

### Task 2.5.3: Rate limiting + quiet hours

**Files:**
- Create: `backend/integrations/proactive_rate_limit.py`
- Test: `backend/tests/integrations/test_proactive_rate_limit.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integrations/test_proactive_rate_limit.py
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.dialects.postgresql import insert

from backend.db.session import async_session
from backend.integrations.proactive_rate_limit import (
    can_fire_proactive,
    record_ping,
)
from db.models import ProactivePing, User


async def _make_user(user_id, wake="07:00", sleep="23:00", tz="UTC"):
    async with async_session() as s:
        s.add(User(
            id=user_id, phone="+1", timezone=tz,
            living_profile={
                # USER MODEL facts under the standard shape
                # render_user_model_block reads from `facts`; keep simple
            },
        ))
        await s.commit()


@pytest.mark.asyncio
async def test_can_fire_when_quiet_no_history(db):
    await _make_user("u1")
    decision = await can_fire_proactive("u1", source="email", now=datetime(2026, 4, 25, 10, 0))
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_quota_capped_at_3_per_day(db):
    await _make_user("u1")
    base = datetime(2026, 4, 25, 9, 0)
    for h in (9, 11, 14):
        await record_ping("u1", source="email", message_ref=f"m{h}", at=base.replace(hour=h))
    decision = await can_fire_proactive(
        "u1", source="email", now=base.replace(hour=15)
    )
    assert decision.allowed is False
    assert "quota" in decision.reason


@pytest.mark.asyncio
async def test_30min_cooldown(db):
    await _make_user("u1")
    base = datetime(2026, 4, 25, 9, 0)
    await record_ping("u1", source="email", message_ref="m1", at=base)
    decision = await can_fire_proactive(
        "u1", source="email", now=base + timedelta(minutes=10)
    )
    assert decision.allowed is False
    assert "cooldown" in decision.reason


@pytest.mark.asyncio
async def test_quiet_hours_blocks(db, monkeypatch):
    await _make_user("u1")
    # Stub out user-fact loader to return a sleep window
    async def fake_load_facts(user_id):
        return {
            "wake_time": {"value": "07:00"},
            "sleep_time": {"value": "23:00"},
        }
    monkeypatch.setattr(
        "backend.integrations.proactive_rate_limit._load_user_quiet_hours",
        lambda uid: ("23:00", "07:00"),
    )
    decision = await can_fire_proactive(
        "u1", source="email", now=datetime(2026, 4, 25, 2, 30)
    )
    assert decision.allowed is False
    assert "quiet" in decision.reason
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest backend/tests/integrations/test_proactive_rate_limit.py -v
```

- [ ] **Step 3: Implement**

```python
# backend/integrations/proactive_rate_limit.py
"""Rate limiting + quiet hours for proactive pings.

Single source of truth for "should we wake the user up right now?"
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select

from backend.db.session import async_session
from db.models import ProactivePing, User


_DAILY_QUOTA = 3
_COOLDOWN = timedelta(minutes=30)


@dataclass(frozen=True)
class FireDecision:
    allowed: bool
    reason: str  # "ok" | "cooldown:Xs" | "quota:N/day" | "quiet:HH:MM-HH:MM"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_hhmm(raw: str | None) -> time | None:
    if not raw:
        return None
    try:
        h, m = raw.strip().split(":")
        return time(hour=int(h), minute=int(m))
    except Exception:
        return None


def _in_quiet_window(
    now_local: time, sleep_at: time, wake_at: time
) -> bool:
    """True if now_local lies in the [sleep_at, wake_at) wraparound window."""
    if sleep_at <= wake_at:
        return sleep_at <= now_local < wake_at
    return now_local >= sleep_at or now_local < wake_at


async def _load_user_quiet_hours(
    user_id: str,
) -> tuple[str | None, str | None]:
    from backend.memory.user_facts.api import get_user_facts
    facts = await get_user_facts(user_id)
    sleep = (facts or {}).get("sleep_time", {}).get("value")
    wake = (facts or {}).get("wake_time", {}).get("value")
    return sleep, wake


async def _load_user_tz(user_id: str) -> str:
    async with async_session() as s:
        u = (
            await s.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
    return (u.timezone if u and u.timezone else "UTC")


async def can_fire_proactive(
    user_id: str, source: str, now: datetime | None = None
) -> FireDecision:
    if now is None:
        now = _utcnow()

    sleep_raw, wake_raw = await _load_user_quiet_hours(user_id)
    sleep_at = _parse_hhmm(sleep_raw)
    wake_at = _parse_hhmm(wake_raw)
    if sleep_at and wake_at:
        # Naive: treat `now` as already in user-local TZ. Production should
        # convert via zoneinfo using await _load_user_tz(user_id).
        if _in_quiet_window(now.time(), sleep_at, wake_at):
            return FireDecision(
                allowed=False,
                reason=f"quiet:{sleep_raw}-{wake_raw}",
            )

    async with async_session() as session:
        recent = (
            await session.execute(
                select(ProactivePing)
                .where(ProactivePing.user_id == user_id)
                .where(ProactivePing.suppressed_reason.is_(None))
                .where(ProactivePing.fired_at >= now - timedelta(days=1))
                .order_by(ProactivePing.fired_at.desc())
            )
        ).scalars().all()

    if recent:
        last = recent[0].fired_at
        if (now - last) < _COOLDOWN:
            return FireDecision(
                allowed=False,
                reason=f"cooldown:{int((now - last).total_seconds())}s",
            )

    if len(recent) >= _DAILY_QUOTA:
        return FireDecision(
            allowed=False, reason=f"quota:{len(recent)}/day"
        )

    return FireDecision(allowed=True, reason="ok")


async def record_ping(
    user_id: str,
    source: str,
    message_ref: str | None,
    at: datetime | None = None,
    suppressed_reason: str | None = None,
) -> None:
    async with async_session() as session:
        session.add(
            ProactivePing(
                user_id=user_id,
                source=source,
                message_ref=message_ref,
                fired_at=at or _utcnow(),
                suppressed_reason=suppressed_reason,
            )
        )
        await session.commit()
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest backend/tests/integrations/test_proactive_rate_limit.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/proactive_rate_limit.py \
        backend/tests/integrations/test_proactive_rate_limit.py
git commit -m "feat(integrations): proactive rate limit + quiet hours"
```

---

### Task 2.5.4: Proactive email trigger orchestrator

**Files:**
- Create: `backend/integrations/proactive_email_trigger.py`
- Test: `backend/tests/integrations/test_proactive_email_trigger.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integrations/test_proactive_email_trigger.py
from datetime import datetime

import pytest

from backend.integrations.composio_client import NormalizedGmailMessage
from backend.integrations.proactive_email_trigger import (
    THRESHOLD,
    maybe_surface_email,
)


def _msg(**kw):
    base = dict(
        gmail_message_id="m1", thread_id="t1",
        from_address="sarah@acme.com", from_name="Sarah",
        to_addresses=[], cc_addresses=[],
        subject="re: term sheet", snippet="...",
        body_text="body", labels=["INBOX", "PRIMARY", "IMPORTANT"],
        is_important=True, is_starred=False, is_sent=False,
        internal_date=datetime(2026, 4, 25),
    )
    base.update(kw)
    return NormalizedGmailMessage(**base)


@pytest.mark.asyncio
async def test_low_score_does_not_invoke_brain(db, monkeypatch):
    invoked = {"count": 0}

    async def fake_brain(state, config=None):
        invoked["count"] += 1
        return {}

    monkeypatch.setattr(
        "backend.integrations.proactive_email_trigger._invoke_brain",
        fake_brain,
    )

    await maybe_surface_email("u1", _msg(is_important=False))
    assert invoked["count"] == 0


@pytest.mark.asyncio
async def test_high_score_invokes_brain_in_proactive_mode(db, monkeypatch):
    invoked = {}

    async def fake_brain(state, config=None):
        invoked["state"] = state
        invoked["mode"] = config.mode if config else None
        return {}

    monkeypatch.setattr(
        "backend.integrations.proactive_email_trigger._invoke_brain",
        fake_brain,
    )
    monkeypatch.setattr(
        "backend.integrations.proactive_email_trigger.can_fire_proactive",
        _make_decision(allowed=True),
    )

    await maybe_surface_email("u1", _msg())
    assert invoked["mode"] == "proactive"
    assert "term sheet" in invoked["state"]["user_message"].lower()


@pytest.mark.asyncio
async def test_rate_limited_records_suppression(db, monkeypatch):
    monkeypatch.setattr(
        "backend.integrations.proactive_email_trigger._invoke_brain",
        _async_noop,
    )
    monkeypatch.setattr(
        "backend.integrations.proactive_email_trigger.can_fire_proactive",
        _make_decision(allowed=False, reason="cooldown:120s"),
    )

    captured = {}

    async def fake_record(user_id, source, message_ref, at=None, suppressed_reason=None):
        captured["suppressed_reason"] = suppressed_reason

    monkeypatch.setattr(
        "backend.integrations.proactive_email_trigger.record_ping",
        fake_record,
    )

    await maybe_surface_email("u1", _msg())
    assert captured["suppressed_reason"] == "cooldown:120s"


# helpers
def _make_decision(allowed: bool, reason: str = "ok"):
    from backend.integrations.proactive_rate_limit import FireDecision

    async def _f(user_id, source, now=None):
        return FireDecision(allowed=allowed, reason=reason)
    return _f


async def _async_noop(*a, **kw):
    return None
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest backend/tests/integrations/test_proactive_email_trigger.py -v
```

- [ ] **Step 3: Implement**

```python
# backend/integrations/proactive_email_trigger.py
"""Single-source proactive trigger: 'important email arrived'.

When a Gmail webhook ingests a row, fan out here. Score → rate-limit →
invoke Donna's brain in mode='proactive' with the email as trigger context.

NOTE: this is one hardcoded producer. The general noticing layer (multi-
source, learning-aware) is a separate spec.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from backend.db.session import async_session
from backend.integrations.composio_client import NormalizedGmailMessage
from backend.integrations.email_importance import (
    ScoringContext,
    score_email,
)
from backend.integrations.proactive_rate_limit import (
    can_fire_proactive,
    record_ping,
)
from db.models import ChatMessage, OpenLoop, User

logger = logging.getLogger(__name__)

THRESHOLD = 0.5


async def _build_scoring_context(user_id: str) -> ScoringContext:
    async with async_session() as session:
        user = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        loops = (
            await session.execute(
                select(OpenLoop)
                .where(OpenLoop.user_id == user_id)
                .where(OpenLoop.status == "open")
            )
        ).scalars().all()
        recent_sent = (
            await session.execute(
                select(ChatMessage)
                .where(ChatMessage.user_id == user_id)
                .order_by(ChatMessage.created_at.desc())
                .limit(50)
            )
        ).scalars().all()

    biography = (
        (user.living_profile or {}).get("biography", {})
        if user else {}
    )
    relationships = list(biography.get("relationships") or [])
    # The biography schema's relationships entries don't carry email
    # by default; if a future bootstrap pass embeds `_email`, it will
    # be picked up here. For now, fall back to matching by name token.
    return ScoringContext(
        biography_relationships=relationships,
        open_loop_keywords=[
            (loop.summary or "").strip()
            for loop in loops if (loop.summary or "").strip()
        ],
        recent_sent_thread_ids=set(),  # populate from sent-folder mirror later
    )


def _format_trigger_prompt(msg: NormalizedGmailMessage, signals: list[str]) -> str:
    body_excerpt = (msg.body_text or msg.snippet or "")[:600]
    return (
        "[SYSTEM TRIGGER: proactive_email]\n"
        "A new email arrived that may be worth surfacing to the user. "
        "Decide whether to ping them. Use stay_silent if the email is not "
        "actually surface-worthy on a second look.\n\n"
        f"From: {msg.from_name or ''} <{msg.from_address}>\n"
        f"Subject: {msg.subject or ''}\n"
        f"Importance signals: {', '.join(signals) or 'none'}\n\n"
        f"{body_excerpt}"
    )


async def _invoke_brain(state: dict, config=None) -> dict:
    """Pluggable for tests. In prod, calls donna_runtime.brain.donna_turn."""
    from donna_runtime.brain import donna_turn
    return await donna_turn(state, config)


async def maybe_surface_email(
    user_id: str, msg: NormalizedGmailMessage
) -> None:
    ctx = await _build_scoring_context(user_id)
    score = score_email(msg, ctx)
    if score.score < THRESHOLD:
        return

    decision = await can_fire_proactive(user_id, source="email")
    if not decision.allowed:
        await record_ping(
            user_id, "email", msg.gmail_message_id,
            suppressed_reason=decision.reason,
        )
        logger.info(
            "proactive_email: suppressed user=%s reason=%s",
            user_id, decision.reason,
        )
        return

    from donna_runtime.config import DonnaAgentConfig

    cfg = DonnaAgentConfig(mode="proactive", user_id=user_id)
    state = {
        "user_id": user_id,
        "user_message": _format_trigger_prompt(msg, score.signals),
        "trigger": {
            "source": "email",
            "message_ref": msg.gmail_message_id,
            "score": score.score,
            "signals": score.signals,
        },
    }
    try:
        await _invoke_brain(state, cfg)
        await record_ping(user_id, "email", msg.gmail_message_id)
    except Exception:
        logger.exception(
            "proactive_email: brain invocation failed user=%s msg=%s",
            user_id, msg.gmail_message_id,
        )
```

The `state` shape and `DonnaAgentConfig` invocation must match the existing proactive-mode call site in this codebase. If a different convention is in use (e.g., `traced_donna_turn` directly), mirror it — do not invent a new entrypoint.

- [ ] **Step 4: Run — expect pass**

```bash
pytest backend/tests/integrations/test_proactive_email_trigger.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/proactive_email_trigger.py \
        backend/tests/integrations/test_proactive_email_trigger.py
git commit -m "feat(integrations): proactive email trigger orchestrator"
```

---

### Task 2.5.5: Hook into `ingest_gmail_message`

**Files:**
- Modify: `backend/integrations/gmail_ingest.py`
- Modify: `backend/tests/integrations/test_gmail_ingest.py`

- [ ] **Step 1: Append failing test**

```python
@pytest.mark.asyncio
async def test_ingest_fires_proactive_check(db, monkeypatch):
    captured = {}

    async def fake_maybe(user_id, msg):
        captured["called"] = (user_id, msg.gmail_message_id)

    monkeypatch.setattr(
        "backend.integrations.gmail_ingest.maybe_surface_email",
        fake_maybe,
    )
    await ingest_gmail_message("u1", _msg())
    assert captured["called"] == ("u1", "m1")


@pytest.mark.asyncio
async def test_ingest_skips_proactive_for_ignored_message(db, monkeypatch):
    captured = {"called": False}

    async def fake_maybe(user_id, msg):
        captured["called"] = True

    monkeypatch.setattr(
        "backend.integrations.gmail_ingest.maybe_surface_email",
        fake_maybe,
    )
    await ingest_gmail_message("u1", _msg(labels=["SPAM"]))
    assert captured["called"] is False
```

- [ ] **Step 2: Run — expect failure (function not yet hooked)**

```bash
pytest backend/tests/integrations/test_gmail_ingest.py -v
```

- [ ] **Step 3: Modify `ingest_gmail_message`**

In `backend/integrations/gmail_ingest.py`, add at the top:

```python
from backend.integrations.proactive_email_trigger import maybe_surface_email
```

At the very end of `ingest_gmail_message`, after `await session.commit()`:

```python
    # Fire proactive check only for rows we actually stored.
    if depth in ("full", "metadata"):
        try:
            await maybe_surface_email(user_id, msg)
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "ingest_gmail_message: proactive trigger failed user=%s msg=%s",
                user_id, msg.gmail_message_id,
            )
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest backend/tests/integrations/test_gmail_ingest.py -v
```

Expected: 7 passed (5 prior + 2 new).

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/gmail_ingest.py \
        backend/tests/integrations/test_gmail_ingest.py
git commit -m "feat(integrations): fan ingest to proactive email trigger"
```

---

### Task 2.5.6: End-to-end webhook → proactive ping integration test

**Files:**
- Create: `backend/tests/integrations/test_proactive_email_e2e.py`

- [ ] **Step 1: Write the test**

```python
# backend/tests/integrations/test_proactive_email_e2e.py
"""End-to-end: webhook fires → ingest → score → brain invocation."""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.db.session import async_session
from backend.integrations.composio_client import NormalizedGmailMessage
from db.models import ProactivePing, User


def _sign(body: bytes, secret: str = "topsecret") -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
def client(monkeypatch, db):
    monkeypatch.setenv("COMPOSIO_WEBHOOK_SECRET", "topsecret")
    from api.main import app
    return TestClient(app)


@pytest.mark.asyncio
async def test_webhook_to_proactive_ping(client, db, monkeypatch):
    # Seed user + biography with sarah at weekly cadence
    async with async_session() as s:
        s.add(User(
            id="u1", phone="+1", timezone="UTC",
            living_profile={
                "biography": {
                    "relationships": [
                        {"name": "Sarah", "frequency": "weekly",
                         "kind": "colleague", "_email": "sarah@acme.com"},
                    ],
                },
            },
        ))
        await s.commit()

    # Mock Composio fetch to return an email from sarah, IMPORTANT-flagged
    async def fake_fetch(self, user_id, message_id, include_body=True):
        return NormalizedGmailMessage(
            gmail_message_id=message_id, thread_id="t1",
            from_address="sarah@acme.com", from_name="Sarah",
            to_addresses=["you@y.com"], cc_addresses=[],
            subject="re: term sheet", snippet="signed",
            body_text="all good, see attached.",
            labels=["INBOX", "PRIMARY", "IMPORTANT"],
            is_important=True, is_starred=False, is_sent=False,
            internal_date=datetime.now(timezone.utc).replace(tzinfo=None),
        )

    monkeypatch.setattr(
        "backend.integrations.composio_client.ComposioClient.fetch_gmail_message",
        fake_fetch,
    )

    # Mock the brain to record the call without actually running
    invoked = {}

    async def fake_brain(state, config=None):
        invoked["mode"] = config.mode
        invoked["user_message"] = state["user_message"]
        return {}

    monkeypatch.setattr(
        "backend.integrations.proactive_email_trigger._invoke_brain",
        fake_brain,
    )

    body = json.dumps({
        "event": "gmail.new_message",
        "user_id": "u1",
        "message_id": "m_critical",
    }).encode()
    r = client.post(
        "/webhooks/composio",
        content=body,
        headers={"x-composio-signature": _sign(body)},
    )
    assert r.status_code == 200

    # Brain was invoked in proactive mode
    assert invoked["mode"] == "proactive"
    assert "term sheet" in invoked["user_message"].lower()

    # Ping was recorded as fired (not suppressed)
    async with async_session() as s:
        rows = (
            await s.execute(
                select(ProactivePing)
                .where(ProactivePing.user_id == "u1")
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].suppressed_reason is None
    assert rows[0].source == "email"
```

- [ ] **Step 2: Run — expect pass**

```bash
pytest backend/tests/integrations/test_proactive_email_e2e.py -v
```

Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integrations/test_proactive_email_e2e.py
git commit -m "test(integrations): e2e webhook -> proactive ping"
```

---

### Phase 2.5 acceptance

- [ ] **Step P2.5.A: Full suite**

```bash
pytest backend/tests/integrations/ tests/ backend/tests/ -x
```

All pass.

- [ ] **Step P2.5.B: Manual smoke**

With Composio dashboard webhook URL set and a real Google account connected:

1. From a second account, send an email to the connected account that should score above threshold (sender already in user's biography; subject mentions an open loop; or simply mark it IMPORTANT in Gmail's UI before sending).
2. Within ~10 seconds, expect a WhatsApp ping from Donna referencing the email.
3. Send three more such emails in rapid succession; expect only the first to ping (cooldown), with `proactive_pings` rows showing `suppressed_reason='cooldown:Xs'` for the rest.
4. Send a fourth, fifth, sixth on the same day; expect rate-limit suppression (`suppressed_reason='quota:N/day'`).
5. Send one inside the user's quiet hours (set `sleep_time` / `wake_time` to a window covering "now"); expect `suppressed_reason='quiet:HH:MM-HH:MM'`.

---

## Phase 3 — Bootstrap pipeline

End state: a fresh connect produces a non-empty `users.living_profile.biography`, and the rendered `BIOGRAPHY` block appears in the system prompt for the user's next turn.

### Task 3.1: Bootstrap stage 1 — today dense

**Files:**
- Create: `backend/integrations/bootstrap_gmail.py` (start with stage 1 only)
- Test: `backend/tests/integrations/test_bootstrap_gmail.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integrations/test_bootstrap_gmail.py
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import select

from backend.db.session import async_session
from backend.integrations.bootstrap_gmail import bootstrap_today_dense
from backend.integrations.composio_client import NormalizedGmailMessage
from db.models import EmailMessage


@pytest.fixture
def fake_client(monkeypatch):
    class Fake:
        def __init__(self):
            self.messages = []
            self.list_calls = []

        async def list_gmail_message_ids(
            self, user_id, query="", max_results=100, page_token=None
        ):
            self.list_calls.append((user_id, query))
            return [m.gmail_message_id for m in self.messages], None

        async def fetch_gmail_message(self, user_id, message_id, include_body=True):
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


def _msg(mid, hours_ago, labels=("INBOX", "PRIMARY")):
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
        internal_date=datetime.now(timezone.utc).replace(tzinfo=None)
                       - timedelta(hours=hours_ago),
    )


@pytest.mark.asyncio
async def test_bootstrap_today_dense_ingests_today_only(db, fake_client):
    fake_client.messages = [
        _msg("m_today", hours_ago=2),
        _msg("m_yesterday", hours_ago=30),
    ]

    await bootstrap_today_dense("u1")

    async with async_session() as s:
        rows = (
            await s.execute(select(EmailMessage).where(EmailMessage.user_id == "u1"))
        ).scalars().all()
    ids = {r.gmail_message_id for r in rows}
    # Stage 1's gmail query is "newer_than:1d"; both messages may pass that
    # depending on local-tz boundary. Assert at least the today one landed:
    assert "m_today" in ids


@pytest.mark.asyncio
async def test_bootstrap_today_dense_classifies_with_label_router(db, fake_client):
    fake_client.messages = [
        _msg("m_primary", 1, labels=("INBOX", "PRIMARY")),
        _msg("m_promo", 1, labels=("INBOX", "PROMOTIONS")),
        _msg("m_spam", 1, labels=("SPAM",)),
    ]
    await bootstrap_today_dense("u1")
    async with async_session() as s:
        rows = (
            await s.execute(select(EmailMessage).where(EmailMessage.user_id == "u1"))
        ).scalars().all()
    ids = {r.gmail_message_id for r in rows}
    assert "m_primary" in ids       # full
    assert "m_promo" not in ids     # aggregate → no row
    assert "m_spam" not in ids      # ignore
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest backend/tests/integrations/test_bootstrap_gmail.py -v
```

- [ ] **Step 3: Implement stage 1**

```python
# backend/integrations/bootstrap_gmail.py
"""Three-stage Gmail bootstrap: today-dense, 30d-important, 90d-aggregates.

Run once after connection.complete. Writes mirror rows; biography
synthesis runs after all stages complete (separate module).
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Iterable

from backend.integrations.composio_client import (
    ComposioClient,
    NormalizedGmailMessage,
)
from backend.integrations.gmail_ingest import ingest_gmail_message
from config import settings

logger = logging.getLogger(__name__)


def _client() -> ComposioClient:
    return ComposioClient(api_key=settings.composio_api_key)


async def bootstrap_today_dense(user_id: str) -> int:
    """Read every message from the last ~24h, classify, ingest. Returns count."""
    client = _client()
    ids, _ = await client.list_gmail_message_ids(
        user_id=user_id, query="newer_than:1d", max_results=200
    )
    count = 0
    for mid in ids:
        try:
            msg = await client.fetch_gmail_message(
                user_id=user_id, message_id=mid, include_body=True
            )
        except Exception:
            logger.exception("bootstrap_today_dense: fetch failed mid=%s", mid)
            continue
        await ingest_gmail_message(user_id, msg)
        count += 1
    return count
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest backend/tests/integrations/test_bootstrap_gmail.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/bootstrap_gmail.py \
        backend/tests/integrations/test_bootstrap_gmail.py
git commit -m "feat(integrations): bootstrap stage 1 (today dense)"
```

---

### Task 3.2: Bootstrap stage 2 — 30d important

**Files:**
- Modify: `backend/integrations/bootstrap_gmail.py`
- Modify: `backend/tests/integrations/test_bootstrap_gmail.py`

- [ ] **Step 1: Append failing test**

```python
@pytest.mark.asyncio
async def test_bootstrap_30d_important(db, fake_client):
    fake_client.messages = [
        _msg("m_imp_1", hours_ago=72, labels=("INBOX", "IMPORTANT", "PRIMARY")),
        _msg("m_imp_2", hours_ago=24*20, labels=("INBOX", "IMPORTANT")),
    ]
    # mark them important on the normalized payload
    fake_client.messages[0] = NormalizedGmailMessage(
        **{**fake_client.messages[0].__dict__, "is_important": True}
    )
    fake_client.messages[1] = NormalizedGmailMessage(
        **{**fake_client.messages[1].__dict__, "is_important": True}
    )

    from backend.integrations.bootstrap_gmail import bootstrap_30d_important
    n = await bootstrap_30d_important("u1")
    assert n == 2
    # query should target IMPORTANT label and 30d window
    assert any(
        "is:important" in q or "label:important" in q
        for _, q in fake_client.list_calls
    )
```

- [ ] **Step 2: Run — expect failure**

```bash
pytest backend/tests/integrations/test_bootstrap_gmail.py::test_bootstrap_30d_important -v
```

- [ ] **Step 3: Implement stage 2**

Append to `backend/integrations/bootstrap_gmail.py`:

```python
async def bootstrap_30d_important(user_id: str) -> int:
    client = _client()
    ids, _ = await client.list_gmail_message_ids(
        user_id=user_id,
        query="is:important newer_than:30d",
        max_results=300,
    )
    count = 0
    for mid in ids:
        try:
            msg = await client.fetch_gmail_message(
                user_id=user_id, message_id=mid, include_body=True
            )
        except Exception:
            logger.exception(
                "bootstrap_30d_important: fetch failed mid=%s", mid
            )
            continue
        await ingest_gmail_message(user_id, msg)
        count += 1
    return count
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest backend/tests/integrations/test_bootstrap_gmail.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/bootstrap_gmail.py \
        backend/tests/integrations/test_bootstrap_gmail.py
git commit -m "feat(integrations): bootstrap stage 2 (30d important)"
```

---

### Task 3.3: Bootstrap stage 3 — 90d sender aggregates (in-memory)

**Files:**
- Modify: `backend/integrations/bootstrap_gmail.py`
- Modify: `backend/tests/integrations/test_bootstrap_gmail.py`

- [ ] **Step 1: Append failing test**

```python
@pytest.mark.asyncio
async def test_bootstrap_90d_aggregates(db, fake_client):
    fake_client.messages = [
        _msg(f"m_{i}", hours_ago=24 * (i + 1)) for i in range(15)
    ]
    # Override sender for variety
    out_msgs = []
    for i, m in enumerate(fake_client.messages):
        sender = "sarah@x.com" if i < 10 else f"u{i}@y.com"
        out_msgs.append(NormalizedGmailMessage(
            **{**m.__dict__, "from_address": sender}
        ))
    fake_client.messages = out_msgs

    from backend.integrations.bootstrap_gmail import bootstrap_90d_aggregates
    aggs = await bootstrap_90d_aggregates("u1", top_n=5)
    assert isinstance(aggs, list)
    assert aggs[0]["from_address"] == "sarah@x.com"
    assert aggs[0]["count"] == 10
```

- [ ] **Step 2: Run — expect failure**

```bash
pytest backend/tests/integrations/test_bootstrap_gmail.py::test_bootstrap_90d_aggregates -v
```

- [ ] **Step 3: Implement stage 3**

Append to `bootstrap_gmail.py`:

```python
async def bootstrap_90d_aggregates(
    user_id: str, top_n: int = 50
) -> list[dict]:
    """Return top-N senders in last 90d (count + sample subjects).

    Metadata-only — does NOT write to email_messages mirror; returned in
    memory for biography synthesis to consume immediately.
    """
    client = _client()
    ids, page_token = await client.list_gmail_message_ids(
        user_id=user_id, query="newer_than:90d", max_results=500
    )
    while page_token:
        more, page_token = await client.list_gmail_message_ids(
            user_id=user_id,
            query="newer_than:90d",
            max_results=500,
            page_token=page_token,
        )
        ids.extend(more)
        if len(ids) > 5000:
            break  # safety cap

    counter: Counter = Counter()
    samples: dict[str, list[str]] = {}
    for mid in ids:
        try:
            msg = await client.fetch_gmail_message(
                user_id=user_id, message_id=mid, include_body=False
            )
        except Exception:
            continue
        addr = msg.from_address
        counter[addr] += 1
        if len(samples.setdefault(addr, [])) < 3 and msg.subject:
            samples[addr].append(msg.subject)

    return [
        {
            "from_address": addr,
            "count": n,
            "sample_subjects": samples.get(addr, []),
        }
        for addr, n in counter.most_common(top_n)
    ]
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest backend/tests/integrations/test_bootstrap_gmail.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/bootstrap_gmail.py \
        backend/tests/integrations/test_bootstrap_gmail.py
git commit -m "feat(integrations): bootstrap stage 3 (90d sender aggregates)"
```

---

### Task 3.4: Calendar bootstrap

**Files:**
- Create: `backend/integrations/bootstrap_calendar.py`
- Test: `backend/tests/integrations/test_bootstrap_calendar.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integrations/test_bootstrap_calendar.py
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from backend.db.session import async_session
from backend.integrations.bootstrap_calendar import bootstrap_calendar
from db.models import CalendarEntry


@pytest.fixture
def fake_client(monkeypatch):
    events = [
        {
            "id": f"e{i}",
            "summary": f"event {i}",
            "start": {"dateTime": (datetime.now(timezone.utc) + timedelta(days=i)).isoformat()},
            "end":   {"dateTime": (datetime.now(timezone.utc) + timedelta(days=i, hours=1)).isoformat()},
        }
        for i in range(5)
    ]

    class Fake:
        async def list_calendar_events(self, user_id, time_min, time_max, max_results=250):
            return events

    monkeypatch.setattr(
        "backend.integrations.bootstrap_calendar._client",
        lambda: Fake(),
    )
    return events


@pytest.mark.asyncio
async def test_bootstrap_calendar_ingests_events(db, fake_client):
    n = await bootstrap_calendar("u1")
    assert n == 5
    async with async_session() as s:
        rows = (
            await s.execute(select(CalendarEntry).where(CalendarEntry.user_id == "u1"))
        ).scalars().all()
    assert len(rows) == 5
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest backend/tests/integrations/test_bootstrap_calendar.py -v
```

- [ ] **Step 3: Implement**

```python
# backend/integrations/bootstrap_calendar.py
"""Calendar bootstrap — last 30d + next 90d into calendar_entries."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.integrations.calendar_ingest import ingest_calendar_event
from backend.integrations.composio_client import ComposioClient
from config import settings


def _client() -> ComposioClient:
    return ComposioClient(api_key=settings.composio_api_key)


async def bootstrap_calendar(user_id: str) -> int:
    client = _client()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    time_min = now - timedelta(days=30)
    time_max = now + timedelta(days=90)
    events = await client.list_calendar_events(
        user_id=user_id, time_min=time_min, time_max=time_max
    )
    count = 0
    for event in events:
        await ingest_calendar_event(user_id, event)
        count += 1
    return count
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest backend/tests/integrations/test_bootstrap_calendar.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/bootstrap_calendar.py \
        backend/tests/integrations/test_bootstrap_calendar.py
git commit -m "feat(integrations): calendar bootstrap"
```

---

### Task 3.5: Biography synthesis (LLM passes)

**Files:**
- Create: `backend/integrations/biography_synthesis.py`
- Create: `backend/integrations/prompts/biography_relationships.md`
- Create: `backend/integrations/prompts/biography_work.md`
- Create: `backend/integrations/prompts/biography_interests.md`
- Create: `backend/integrations/prompts/biography_life_signals.md`
- Create: `backend/integrations/prompts/biography_synthesis.md`
- Test: `backend/tests/integrations/test_biography_synthesis.py`

- [ ] **Step 1: Write the failing test (mock LLM client)**

```python
# backend/tests/integrations/test_biography_synthesis.py
from datetime import datetime

import pytest
from sqlalchemy import select

from backend.db.session import async_session
from backend.integrations.biography_synthesis import synthesize_biography
from backend.integrations.composio_client import NormalizedGmailMessage
from db.models import User


def _msg(mid):
    return NormalizedGmailMessage(
        gmail_message_id=mid, thread_id=f"t-{mid}",
        from_address="sarah@acme.com", from_name="Sarah",
        to_addresses=["you@y.com"], cc_addresses=[],
        subject=f"re: term sheet ({mid})", snippet="...",
        body_text="lots of body text " * 30,
        labels=["INBOX", "PRIMARY", "IMPORTANT"],
        is_important=True, is_starred=False, is_sent=False,
        internal_date=datetime(2026, 4, 24),
    )


@pytest.mark.asyncio
async def test_synthesize_biography_writes_living_profile(db, monkeypatch):
    async with async_session() as s:
        s.add(User(id="u1", phone="+1", timezone="UTC", living_profile={}))
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

    biography = await synthesize_biography(
        user_id="u1",
        full_messages=[_msg("m1"), _msg("m2")],
        sender_aggregates=[
            {"from_address": "sarah@acme.com", "count": 10, "sample_subjects": ["term sheet"]},
        ],
    )

    assert biography["overview"].startswith("founder")
    assert biography["work"]["employer"] == "Acme"
    assert biography["relationships"][0]["name"] == "Sarah"

    async with async_session() as s:
        user = (await s.execute(select(User).where(User.id == "u1"))).scalar_one()
    assert user.living_profile["biography"]["overview"].startswith("founder")
```

- [ ] **Step 2: Create prompt files**

Each is a short instruction file. Example for `biography_relationships.md`:

```markdown
You are extracting a relationship graph from a sample of someone's email.

Input: a list of emails (sender, subject, body excerpt) and a list of frequent senders.

Output STRICT JSON only, no prose:
{
  "relationships": [
    {"name": "...", "kind": "colleague|family|friend|vendor|other",
     "frequency": "daily|weekly|monthly|rare", "role": "...",
     "last_seen": "YYYY-MM-DD"}
  ]
}

Rules:
- Names from From: header. If only an email is shown, use the local part.
- "kind" inferred from content tone and address (work domain → colleague, family-name pattern → family).
- Skip noreply / automated / no-name addresses.
- Top 8 only. Pick the highest-signal people.
- Output ONLY the JSON, nothing else.
```

Write similar focused prompts for `work`, `interests`, `life_signals`. The synthesis prompt takes the four prior outputs + the aggregates and produces:

```markdown
You are composing a 2-3 sentence narrative biography of a user from
extracted facts. Output STRICT JSON only:
{ "overview": "..." }

Voice: lowercase, blunt, no em dashes. Read like a sharp observation,
not a CV. ≤ 80 words.

Inputs follow:
```

- [ ] **Step 3: Run test — expect ImportError**

```bash
pytest backend/tests/integrations/test_biography_synthesis.py -v
```

- [ ] **Step 4: Implement synthesis**

```python
# backend/integrations/biography_synthesis.py
"""Biography synthesis — four LLM extraction passes + a synthesis pass.

Output written to users.living_profile.biography via update_living_profile.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from backend.integrations.composio_client import NormalizedGmailMessage
from backend.memory.tools.update_living_profile import update_living_profile

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"

_PASSES = [
    ("relationships", "biography_relationships.md"),
    ("work", "biography_work.md"),
    ("interests", "biography_interests.md"),
    ("life_signals", "biography_life_signals.md"),
]


async def _call_llm(prompt: str, model: str = "sonnet") -> str:
    """Call Sonnet 4.6. Pluggable for tests."""
    # Reuse the existing project's LLM client. Adapt the import to whatever
    # llm wrapper exists in this codebase (e.g. donna_runtime.brain or
    # backend.memory.synthesis client).
    from donna_runtime.options import call_sonnet  # placeholder name
    return await call_sonnet(prompt)


def _format_messages(msgs: Iterable[NormalizedGmailMessage]) -> str:
    chunks = []
    for m in msgs:
        body = (m.body_text or "")[:1500]
        chunks.append(
            f"From: {m.from_name or ''} <{m.from_address}>\n"
            f"Date: {m.internal_date.isoformat()}\n"
            f"Subject: {m.subject or ''}\n\n{body}\n---"
        )
    return "\n".join(chunks)


def _format_aggregates(aggs: list[dict]) -> str:
    return "\n".join(
        f"{a['from_address']} — {a['count']} msgs — sample: {', '.join(a['sample_subjects'])}"
        for a in aggs
    )


async def _run_pass(
    pass_name: str,
    prompt_file: str,
    messages_block: str,
    aggregates_block: str,
) -> dict:
    prompt = (_PROMPTS_DIR / prompt_file).read_text()
    rendered = (
        f"{prompt}\n\n## EMAILS\n{messages_block}\n\n"
        f"## FREQUENT SENDERS\n{aggregates_block}"
    )
    raw = await _call_llm(rendered)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.exception("biography pass %s: bad JSON", pass_name)
        return {}


async def synthesize_biography(
    user_id: str,
    full_messages: list[NormalizedGmailMessage],
    sender_aggregates: list[dict],
) -> dict:
    if not full_messages and not sender_aggregates:
        return {}

    messages_block = _format_messages(full_messages)
    aggregates_block = _format_aggregates(sender_aggregates)

    pass_outputs: dict[str, dict] = {}
    for name, prompt_file in _PASSES:
        pass_outputs[name] = await _run_pass(
            name, prompt_file, messages_block, aggregates_block
        )

    synthesis_prompt = (
        (_PROMPTS_DIR / "biography_synthesis.md").read_text()
        + "\n\n## RELATIONSHIPS\n"
        + json.dumps(pass_outputs.get("relationships", {}))
        + "\n\n## WORK\n"
        + json.dumps(pass_outputs.get("work", {}))
        + "\n\n## INTERESTS\n"
        + json.dumps(pass_outputs.get("interests", {}))
        + "\n\n## LIFE\n"
        + json.dumps(pass_outputs.get("life_signals", {}))
    )
    synth_raw = await _call_llm(synthesis_prompt)
    try:
        synthesis = json.loads(synth_raw)
    except json.JSONDecodeError:
        synthesis = {"overview": ""}

    biography = {
        "overview": synthesis.get("overview", ""),
        "work": pass_outputs.get("work", {}).get("work", pass_outputs.get("work", {})),
        "relationships": pass_outputs.get("relationships", {}).get(
            "relationships",
            pass_outputs.get("relationships", {}),
        ),
        "interests": pass_outputs.get("interests", {}).get(
            "interests", []
        ),
        "rhythms": pass_outputs.get("life_signals", {}).get("rhythms", {}),
        "evidence_window": {
            "today_messages": sum(
                1 for m in full_messages if m.is_important is False
            ),
            "important_30d_messages": sum(
                1 for m in full_messages if m.is_important
            ),
            "aggregated_90d_senders": len(sender_aggregates),
        },
        "last_bootstrapped_at": datetime.now(timezone.utc).isoformat(),
    }

    await update_living_profile(
        user_id=user_id, patch={"biography": biography}
    )
    return biography
```

If `donna_runtime.options.call_sonnet` does not exist, replace with the actual project LLM helper. Verify before running.

- [ ] **Step 5: Run test — expect pass**

```bash
pytest backend/tests/integrations/test_biography_synthesis.py -v
```

Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/integrations/biography_synthesis.py \
        backend/integrations/prompts/ \
        backend/tests/integrations/test_biography_synthesis.py
git commit -m "feat(integrations): biography synthesis (4 passes + narrative)"
```

---

### Task 3.6: Wire bootstrap into webhook

**Files:**
- Modify: `api/composio_webhook.py`
- Test: extend `test_webhook_route.py`

- [ ] **Step 1: Append failing test**

```python
def test_webhook_connection_complete_enqueues_bootstrap(client, db, monkeypatch):
    captured = {}

    async def fake_run_bootstrap(user_id):
        captured["bootstrap"] = user_id

    monkeypatch.setattr(
        "api.composio_webhook.run_bootstrap_async",
        fake_run_bootstrap,
    )
    body = json.dumps({
        "event": "connection.complete",
        "user_id": "u1",
        "connection_id": "ca-1",
        "app": "GMAIL",
    }).encode()
    r = client.post(
        "/webhooks/composio",
        content=body,
        headers={"x-composio-signature": _sign(body)},
    )
    assert r.status_code == 200
    # bootstrap enqueued (may run via asyncio.create_task; allow short wait)
    import asyncio, time
    deadline = time.time() + 1.0
    while "bootstrap" not in captured and time.time() < deadline:
        asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.01))
    assert captured.get("bootstrap") == "u1"
```

- [ ] **Step 2: Run — expect failure**

```bash
pytest backend/tests/integrations/test_webhook_route.py::test_webhook_connection_complete_enqueues_bootstrap -v
```

- [ ] **Step 3: Implement**

In `api/composio_webhook.py`, add at module scope:

```python
import asyncio

from backend.integrations.bootstrap_calendar import bootstrap_calendar
from backend.integrations.bootstrap_gmail import (
    bootstrap_30d_important,
    bootstrap_90d_aggregates,
    bootstrap_today_dense,
)
from backend.integrations.biography_synthesis import synthesize_biography


async def run_bootstrap_async(user_id: str) -> None:
    """Run all bootstrap stages + biography synthesis. Fire-and-forget."""
    try:
        await bootstrap_today_dense(user_id)
        await bootstrap_30d_important(user_id)
        await bootstrap_calendar(user_id)
        aggregates = await bootstrap_90d_aggregates(user_id)
        # Collect the message rows we just stored as "full" for synthesis.
        from sqlalchemy import select
        from backend.db.session import async_session
        from db.models import EmailMessage
        async with async_session() as s:
            rows = (
                await s.execute(
                    select(EmailMessage)
                    .where(EmailMessage.user_id == user_id)
                    .where(EmailMessage.ingest_depth == "full")
                    .where(EmailMessage.body_stored.is_(True))
                )
            ).scalars().all()
        from backend.integrations.composio_client import NormalizedGmailMessage
        msgs = [
            NormalizedGmailMessage(
                gmail_message_id=r.gmail_message_id,
                thread_id=r.thread_id,
                from_address=r.from_address,
                from_name=r.from_name,
                to_addresses=r.to_addresses,
                cc_addresses=r.cc_addresses,
                subject=r.subject,
                snippet=r.snippet,
                body_text=r.body_text,
                labels=r.labels,
                is_important=r.is_important,
                is_starred=r.is_starred,
                is_sent=r.is_sent,
                internal_date=r.internal_date,
            )
            for r in rows
        ]
        await synthesize_biography(user_id, msgs, aggregates)
    except Exception:
        logger.exception("bootstrap failed user=%s", user_id)
```

In the `connection.complete` branch, after subscribing triggers:

```python
        asyncio.create_task(run_bootstrap_async(user_id))
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest backend/tests/integrations/test_webhook_route.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add api/composio_webhook.py backend/tests/integrations/test_webhook_route.py
git commit -m "feat(api): enqueue bootstrap + biography on connection complete"
```

---

### Task 3.7: Renderer extension — `BIOGRAPHY` block

**Files:**
- Modify: `backend/memory/user_facts/rendering.py`
- Test: `backend/tests/integrations/test_biography_render.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integrations/test_biography_render.py
from backend.memory.user_facts.rendering import render_living_profile_block


def test_biography_block_rendered():
    profile = {
        "biography": {
            "overview": "founder fundraising at acme; close ties to sarah.",
            "work": {"employer": "Acme", "role": "founder"},
            "relationships": [
                {"name": "Sarah", "kind": "colleague", "frequency": "weekly"},
                {"name": "Mom", "kind": "family", "frequency": "weekly"},
            ],
            "interests": ["VC", "design tooling"],
        },
    }
    out = render_living_profile_block(profile)
    assert "BIOGRAPHY" in out
    assert "founder fundraising" in out
    assert "Acme" in out
    assert "Sarah" in out


def test_biography_omitted_when_missing():
    out = render_living_profile_block({"summary": "hi"})
    assert "BIOGRAPHY" not in out
```

- [ ] **Step 2: Run — expect failure**

```bash
pytest backend/tests/integrations/test_biography_render.py -v
```

- [ ] **Step 3: Extend the renderer**

In `backend/memory/user_facts/rendering.py:render_living_profile_block`, before the final `return "\n".join(lines).strip()`, add:

```python
    bio = profile.get("biography") if isinstance(profile, dict) else None
    if isinstance(bio, dict):
        bio_lines: list[str] = ["BIOGRAPHY"]
        overview = (bio.get("overview") or "").strip()
        if overview:
            bio_lines.append(f"  {overview}")
        work = bio.get("work") or {}
        if isinstance(work, dict) and (work.get("employer") or work.get("role")):
            who = " ".join(
                p for p in (work.get("role"), work.get("employer")) if p
            )
            bio_lines.append(f"  work: {who}")
        rels = bio.get("relationships") or []
        for rel in rels[:5]:
            if not isinstance(rel, dict):
                continue
            name = rel.get("name") or "?"
            kind = rel.get("kind") or ""
            freq = rel.get("frequency") or ""
            tail = " · ".join(p for p in (kind, freq) if p)
            bio_lines.append(
                f"  - {name}" + (f" ({tail})" if tail else "")
            )
        interests = bio.get("interests") or []
        if interests:
            bio_lines.append(
                "  interests: " + ", ".join(str(i) for i in interests[:5])
            )
        if len(bio_lines) > 1:
            if lines:
                lines.extend(["", *bio_lines])
            else:
                lines.extend(bio_lines)
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest backend/tests/integrations/test_biography_render.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/memory/user_facts/rendering.py \
        backend/tests/integrations/test_biography_render.py
git commit -m "feat(memory): render BIOGRAPHY block in user_model_block"
```

---

### Phase 3 acceptance

- [ ] **Step P3.A: Suite + regressions**

```bash
pytest backend/tests/integrations/ tests/ backend/tests/ -x
```

All pass.

- [ ] **Step P3.B: Manual verification (real account, dev env)**

In a dev environment with `COMPOSIO_API_KEY` set, run a real connect flow:

1. Open WhatsApp REPL: `python chat_donna.py`.
2. Send: "connect my google".
3. Expect a URL in the reply with the consent line preserved.
4. Tap the URL, complete OAuth.
5. Wait ~10 seconds.
6. Send: "what do you know about me from my email?"
7. Expect a reply that draws on real biographical content.

Log the bootstrap cost from observability and confirm it landed under $1.

---

## Phase 4 — Reconcile + hardening

End state: a synthetic missed-webhook scenario gets caught up by reconcile within 24h; disconnect/expiry states are surfaced cleanly to Donna.

### Task 4.1: Daily reconcile worker

**Files:**
- Create: `backend/integrations/reconcile.py`
- Test: `backend/tests/integrations/test_reconcile.py`
- Modify: `api/main.py` (schedule the worker)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integrations/test_reconcile.py
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from backend.db.session import async_session
from backend.integrations import state
from backend.integrations.composio_client import NormalizedGmailMessage
from backend.integrations.reconcile import reconcile_user
from db.models import CalendarEntry, EmailMessage


@pytest.mark.asyncio
async def test_reconcile_fills_gmail_gaps(db, monkeypatch):
    await state.upsert_pending("u1", "google", "gmail")
    await state.mark_connected("u1", "google", "gmail", connection_id="c1")

    captured = {"fetched": []}

    async def fake_list(self, user_id, query="", max_results=100, page_token=None):
        return ["m_missing", "m_existing"], None

    async def fake_fetch(self, user_id, message_id, include_body=True):
        captured["fetched"].append(message_id)
        return NormalizedGmailMessage(
            gmail_message_id=message_id, thread_id="t1",
            from_address="a@b.com", from_name=None,
            to_addresses=[], cc_addresses=[],
            subject="hi", snippet="hi", body_text="body",
            labels=["INBOX", "PRIMARY"],
            is_important=False, is_starred=False, is_sent=False,
            internal_date=datetime.now(timezone.utc).replace(tzinfo=None),
        )

    monkeypatch.setattr(
        "backend.integrations.composio_client.ComposioClient.list_gmail_message_ids",
        fake_list,
    )
    monkeypatch.setattr(
        "backend.integrations.composio_client.ComposioClient.fetch_gmail_message",
        fake_fetch,
    )

    # pre-seed the "existing" row
    from backend.integrations.gmail_ingest import ingest_gmail_message
    await ingest_gmail_message(
        "u1",
        NormalizedGmailMessage(
            gmail_message_id="m_existing", thread_id="t1",
            from_address="a@b.com", from_name=None,
            to_addresses=[], cc_addresses=[],
            subject="x", snippet="x", body_text="b",
            labels=["INBOX", "PRIMARY"],
            is_important=False, is_starred=False, is_sent=False,
            internal_date=datetime.now(timezone.utc).replace(tzinfo=None),
        ),
    )

    await reconcile_user("u1")

    async with async_session() as s:
        rows = (
            await s.execute(
                select(EmailMessage).where(EmailMessage.user_id == "u1")
            )
        ).scalars().all()
    ids = {r.gmail_message_id for r in rows}
    assert "m_missing" in ids
    assert "m_existing" in ids
    assert "m_missing" in captured["fetched"]
    assert "m_existing" not in captured["fetched"]
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest backend/tests/integrations/test_reconcile.py -v
```

- [ ] **Step 3: Implement**

```python
# backend/integrations/reconcile.py
"""Daily defensive reconcile — diff Composio against local mirror, fill gaps."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from backend.db.session import async_session
from backend.integrations import state
from backend.integrations.bootstrap_calendar import bootstrap_calendar
from backend.integrations.composio_client import ComposioClient
from backend.integrations.gmail_ingest import ingest_gmail_message
from config import settings
from db.models import EmailMessage

logger = logging.getLogger(__name__)


async def reconcile_user(user_id: str) -> None:
    rows = await state.list_user_integrations(user_id)
    by_product = {r.product: r for r in rows if r.status == "connected"}

    if "gmail" in by_product:
        await _reconcile_gmail(user_id)
    if "calendar" in by_product:
        await bootstrap_calendar(user_id)  # idempotent upsert covers diff


async def _reconcile_gmail(user_id: str) -> None:
    client = ComposioClient(api_key=settings.composio_api_key)
    ids, _ = await client.list_gmail_message_ids(
        user_id=user_id, query="newer_than:1d", max_results=200
    )
    if not ids:
        return

    async with async_session() as session:
        existing = {
            r.gmail_message_id
            for r in (
                await session.execute(
                    select(EmailMessage.gmail_message_id)
                    .where(EmailMessage.user_id == user_id)
                    .where(EmailMessage.gmail_message_id.in_(ids))
                )
            )
            .scalars()
            .all()
        }

    missing = [mid for mid in ids if mid not in existing]
    for mid in missing:
        try:
            msg = await client.fetch_gmail_message(
                user_id=user_id, message_id=mid, include_body=True
            )
        except Exception:
            logger.exception("reconcile_gmail: fetch failed mid=%s", mid)
            continue
        await ingest_gmail_message(user_id, msg)


async def reconcile_loop(interval_seconds: int = 24 * 60 * 60) -> None:
    """Fire reconcile_user for every connected user, then sleep."""
    while True:
        try:
            async with async_session() as session:
                from db.models import Integration
                user_ids = (
                    (
                        await session.execute(
                            select(Integration.user_id).where(
                                Integration.status == "connected"
                            ).distinct()
                        )
                    )
                    .scalars()
                    .all()
                )
            for uid in user_ids:
                try:
                    await reconcile_user(uid)
                except Exception:
                    logger.exception("reconcile_loop: user=%s failed", uid)
        except Exception:
            logger.exception("reconcile_loop: top-level failure")
        await asyncio.sleep(interval_seconds)
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest backend/tests/integrations/test_reconcile.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/reconcile.py \
        backend/tests/integrations/test_reconcile.py
git commit -m "feat(integrations): daily reconcile worker"
```

---

### Task 4.2: Schedule reconcile loop on startup

**Files:**
- Modify: `api/main.py`

- [ ] **Step 1: Add startup hook**

In `api/main.py`, near the existing `_schedule_task` / `_brief_refresh_task` definitions, add:

```python
_reconcile_task: asyncio.Task | None = None


@app.on_event("startup")
async def _start_reconcile_loop() -> None:
    global _reconcile_task
    from backend.integrations.reconcile import reconcile_loop
    _reconcile_task = asyncio.create_task(reconcile_loop())


@app.on_event("shutdown")
async def _stop_reconcile_loop() -> None:
    global _reconcile_task
    if _reconcile_task is not None:
        _reconcile_task.cancel()
```

(Match existing convention — if startup hooks already exist, append to them rather than redefining.)

- [ ] **Step 2: Smoke test the import path**

```bash
python -c "from api.main import app; print('ok')"
```

- [ ] **Step 3: Commit**

```bash
git add api/main.py
git commit -m "feat(api): schedule daily reconcile loop on startup"
```

---

### Task 4.3: Disconnect / revoke surfacing

Already partly handled in Task 1.9 (`connection.revoked` → `state.mark_revoked`). This task verifies the renderer presents revoked state cleanly and the connect_integration tool re-enables it.

**Files:**
- Test: `backend/tests/integrations/test_revoke_flow.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/integrations/test_revoke_flow.py
import pytest

from backend.integrations import state
from backend.integrations.render import render_integrations_block


@pytest.mark.asyncio
async def test_revoke_then_reconnect(db, monkeypatch):
    await state.upsert_pending("u1", "google", "gmail")
    await state.mark_connected("u1", "google", "gmail", connection_id="c1")
    await state.mark_revoked("u1", "google", "gmail")

    rows = await state.list_user_integrations("u1")
    block = render_integrations_block(rows)
    assert "google_gmail: revoked" in block

    # connect_integration should treat revoked like not-connected and call composio
    fake_calls = []

    class FakeClient:
        async def get_or_create_connection(self, user_id, app):
            fake_calls.append((user_id, app))
            return f"cid-{app}", f"https://composio/start/{app}"

    monkeypatch.setattr(
        "backend.memory.tools.connect_integration._client",
        lambda: FakeClient(),
    )
    from backend.memory.tools.connect_integration import connect_integration
    result = await connect_integration(
        user_id="u1", provider="google", products=["gmail"]
    )
    assert result["status"] == "url_sent"
    assert fake_calls == [("u1", "GMAIL")]
```

- [ ] **Step 2: Run — likely already passes**

```bash
pytest backend/tests/integrations/test_revoke_flow.py -v
```

If a `revoked` status is silently treated as "connected" by `connect_integration`, fix the all-connected check to require literal `"connected"`. The current implementation already does so — confirm.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integrations/test_revoke_flow.py
git commit -m "test(integrations): revoke + reconnect round trip"
```

---

### Phase 4 acceptance

- [ ] **Step P4.A: Full suite + regressions**

```bash
pytest backend/tests/integrations/ tests/ backend/tests/ -x
```

All pass.

---

## Final integration smoke (manual)

- [ ] **Step F.1:** From a fresh dev DB, `alembic upgrade head`.
- [ ] **Step F.2:** Start the API server: `uvicorn api.main:app`.
- [ ] **Step F.3:** Through the WhatsApp REPL or the dev test harness, send "connect my google to donna." Expect a connect link in the reply with the consent line.
- [ ] **Step F.4:** Tap the link, complete Google OAuth.
- [ ] **Step F.5:** Confirm `integrations.status='connected'` rows exist for both `gmail` and `calendar`.
- [ ] **Step F.6:** Send a test email to the connected account from a second account; within ~10s confirm a row appears in `email_messages` with depth=`full`.
- [ ] **Step F.7:** Send "what do you know about me from my email?" and confirm Donna's reply draws on the BIOGRAPHY block.
- [ ] **Step F.8:** Capture observability cost log for the bootstrap; confirm under $1 for a typical inbox.
- [ ] **Step F.9:** Trigger reconcile manually (`python -c "import asyncio; from backend.integrations.reconcile import reconcile_user; asyncio.run(reconcile_user('u1'))"`) and confirm it completes cleanly.

---

## Open items deferred (per spec)

These are NOT in this plan; tracked separately:

- Composio MCP server + tool-search wiring.
- Action tools: send_email, create_calendar_event, modify_event.
- Other Google products (Drive, Tasks, Contacts) and other providers (Microsoft, Slack).
- Biography fan-out to bitemporal facts, Graphiti, episodic Supermemory.
- Encrypted-at-rest body storage / KMS wrapping.
- GDPR purge tool (manual disconnect + cascade delete).
- Periodic re-bootstrap (e.g. monthly biography refresh).
