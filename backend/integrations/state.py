"""CRUD for the integrations table — source of truth for [INTEGRATIONS]."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import select

from db.models import Integration


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _session_factory():
    # Lazy import so test monkeypatches of `backend.db.session.async_session`
    # are honored at call time.
    from backend.db.session import async_session

    return async_session


async def upsert_pending(user_id: str, provider: str, product: str) -> None:
    """Create a pending integration row if missing; no-op if already exists."""
    async with _session_factory()() as session:
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
    async with _session_factory()() as session:
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


async def touch_synced(user_id: str, provider: str, product: str) -> None:
    async with _session_factory()() as session:
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
    async with _session_factory()() as session:
        return (
            await session.execute(
                select(Integration)
                .where(Integration.user_id == user_id)
                .where(Integration.provider == provider)
                .where(Integration.product == product)
            )
        ).scalar_one_or_none()


async def list_user_integrations(user_id: str) -> Sequence[Integration]:
    async with _session_factory()() as session:
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
    async with _session_factory()() as session:
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
