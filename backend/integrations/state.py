"""CRUD for the integrations table — source of truth for [INTEGRATIONS]."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import select

from db.models import Integration

# How long an issued OAuth redirect URL stays "fresh" — re-asks within this
# window get the cached URL back instead of a fresh chain-initiation.
# Composio's short-link endpoints expire fast; 4 minutes is safely under
# their typical TTL and long enough to cover the user re-asking after
# tapping nothing for a few seconds.
REDIRECT_URL_FRESHNESS_SECONDS = 4 * 60


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _session_factory():
    # Lazy import so test monkeypatches of `backend.db.session.async_session`
    # are honored at call time.
    from backend.db.session import async_session

    return async_session


def is_redirect_url_fresh(row: Integration | None) -> bool:
    """Returns True if the row has a cached URL issued within the freshness
    window. Stale or missing URLs return False so the caller knows to
    re-issue the chain."""
    if row is None or not row.redirect_url or row.redirect_url_issued_at is None:
        return False
    age = _utcnow() - row.redirect_url_issued_at
    return age <= timedelta(seconds=REDIRECT_URL_FRESHNESS_SECONDS)


async def upsert_pending(
    user_id: str,
    provider: str,
    product: str,
    *,
    redirect_url: str | None = None,
) -> None:
    """Mark a pending integration. Creates the row if missing; refreshes
    redirect_url + redirect_url_issued_at when a new URL is supplied so
    later turns can reuse the in-flight URL instead of re-initiating the
    Composio chain."""
    async with _session_factory()() as session:
        existing = (
            await session.execute(
                select(Integration)
                .where(Integration.user_id == user_id)
                .where(Integration.provider == provider)
                .where(Integration.product == product)
            )
        ).scalar_one_or_none()
        now = _utcnow()
        if existing is None:
            session.add(
                Integration(
                    user_id=user_id,
                    provider=provider,
                    product=product,
                    status="pending",
                    redirect_url=redirect_url,
                    redirect_url_issued_at=now if redirect_url else None,
                )
            )
            await session.commit()
            return
        if redirect_url is None:
            return
        # Always refresh the cached URL when a new one is supplied — the
        # caller has just successfully initiated a (possibly fresh) chain
        # and the new URL is the one we want to hand back next time.
        existing.redirect_url = redirect_url
        existing.redirect_url_issued_at = now
        existing.updated_at = now
        await session.commit()


async def clear_redirect_url(user_id: str, provider: str, product: str) -> None:
    """Wipe the cached redirect URL — used when a row flips connected or
    when an admin force-resets a pending row."""
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
        row.redirect_url = None
        row.redirect_url_issued_at = None
        row.updated_at = _utcnow()
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
        # Connected rows have no in-flight URL — drop the cached one.
        row.redirect_url = None
        row.redirect_url_issued_at = None
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
