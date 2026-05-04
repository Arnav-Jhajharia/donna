"""Feature lifecycle: pause / resume / archive / list / update_config.

Each transition fans out to the feature's owned primitives via the
``feature_id`` FK back-link added in migration 0024:

  - ``features.status`` is the canonical truth.
  - ``attentions`` rows owned by the feature follow:
      live  → paused on pause_feature
      paused → live   on resume_feature  (only rows we paused)
      *     → quietly_archived on archive_feature
  - ``donna_schedule`` rows owned by the feature:
      pending → skipped on pause_feature  (fired=True so worker won't pick up)
      skipped → re-materialised next fire on resume_feature
      *     → skipped on archive_feature

We never delete rows — soft-status only — because the FK back-links are
also the audit trail. ``archive_feature`` is the kill-switch; the
feature row keeps its history and can be re-installed later.

These helpers are async functions, not methods on a service class,
because they're called from BRAIN tools and from background workers.
Callers pass either ``feature_id`` or ``template_id`` — most BRAIN
tool calls land via template_id (the user-facing slug), so we resolve
either to one feature row.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import AttentionRow, DonnaSchedule, Feature

logger = logging.getLogger(__name__)


# -- Resolution -------------------------------------------------------------


async def _resolve_feature(
    *,
    session: AsyncSession,
    user_id: str,
    feature_id: str | None = None,
    template_id: str | None = None,
) -> Feature | None:
    """Return the feature row matching either id or template for this user."""
    if not (feature_id or template_id):
        raise ValueError("must pass feature_id or template_id")

    stmt = select(Feature).where(Feature.user_id == user_id)
    if feature_id:
        stmt = stmt.where(Feature.id == feature_id)
    else:
        stmt = stmt.where(Feature.template_id == template_id)
    return (await session.execute(stmt)).scalar_one_or_none()


# -- Public lifecycle API ---------------------------------------------------


async def pause_feature(
    *,
    user_id: str,
    feature_id: str | None = None,
    template_id: str | None = None,
    until: datetime | None = None,
) -> Feature | None:
    """Pause a feature: stop firing reminders, keep observations + state.

    ``until`` lets the caller schedule an auto-resume (e.g. vacation
    until Sunday). Phase 2 only stores ``paused_until`` — the
    background sweeper that auto-resumes lands in Phase 4 alongside
    the cron handler dispatcher.
    """
    from backend.db.session import async_session

    async with async_session() as session:
        feature = await _resolve_feature(
            session=session,
            user_id=user_id,
            feature_id=feature_id,
            template_id=template_id,
        )
        if feature is None:
            return None
        if feature.status == "paused":
            return feature

        feature.status = "paused"
        feature.paused_until = until
        feature.updated_at = _utc_now_naive()

        await session.execute(
            update(AttentionRow)
            .where(
                AttentionRow.feature_id == feature.id,
                AttentionRow.status == "live",
            )
            .values(status="paused")
        )
        await session.execute(
            update(DonnaSchedule)
            .where(
                DonnaSchedule.feature_id == feature.id,
                DonnaSchedule.fired.is_(False),
            )
            .values(
                fired=True,
                status="skipped",
                last_error="feature_paused",
            )
        )
        await session.commit()
        await session.refresh(feature)
        return feature


async def resume_feature(
    *,
    user_id: str,
    feature_id: str | None = None,
    template_id: str | None = None,
) -> Feature | None:
    """Resume a paused feature.

    Re-materialises the next cron fire for any registered handlers and
    flips paused attentions back to live. Attentions paused outside
    the feature lifecycle (manual user pause) are left alone — we only
    touch rows whose ``payload.spawned_by == 'feature_install'``.
    """
    from backend.db.session import async_session
    from backend.features.handlers import is_cron_handler_registered
    from backend.features.install import _materialise_cron, _next_cron_fire
    from backend.features.registry import get_registry

    async with async_session() as session:
        feature = await _resolve_feature(
            session=session,
            user_id=user_id,
            feature_id=feature_id,
            template_id=template_id,
        )
        if feature is None:
            return None
        if feature.status == "active":
            return feature

        feature.status = "active"
        feature.paused_until = None
        feature.updated_at = _utc_now_naive()

        # Flip feature-spawned attentions back to live. Manual-paused
        # rows (no ``feature_install`` marker) stay paused.
        rows = (
            await session.execute(
                select(AttentionRow).where(
                    AttentionRow.feature_id == feature.id,
                    AttentionRow.status == "paused",
                )
            )
        ).scalars().all()
        for row in rows:
            if (row.payload or {}).get("spawned_by") == "feature_install":
                row.status = "live"

        # Re-materialise crons. Skipped rows from the pause window stay
        # marked skipped — we only enqueue the next future fire so the
        # schedule history isn't rewritten.
        manifest = get_registry().get_template(feature.template_id) if feature.template_id else None
        if manifest:
            await _materialise_cron(
                session=session,
                user_id=user_id,
                feature=feature,
                manifest=manifest,
            )

        await session.commit()
        await session.refresh(feature)
        return feature


async def archive_feature(
    *,
    user_id: str,
    feature_id: str | None = None,
    template_id: str | None = None,
) -> Feature | None:
    """Archive a feature: hard kill-switch, soft-delete data.

    Attentions transition to ``quietly_archived`` and pending schedules
    to ``skipped``. Observations and the feature row itself are kept
    so a future re-install can re-attach to the historical data via
    ``feature_id``.
    """
    from backend.db.session import async_session

    async with async_session() as session:
        feature = await _resolve_feature(
            session=session,
            user_id=user_id,
            feature_id=feature_id,
            template_id=template_id,
        )
        if feature is None:
            return None
        if feature.status == "archived":
            return feature

        feature.status = "archived"
        feature.paused_until = None
        feature.updated_at = _utc_now_naive()

        await session.execute(
            update(AttentionRow)
            .where(
                AttentionRow.feature_id == feature.id,
                AttentionRow.status.in_(("live", "paused", "shadow", "offered")),
            )
            .values(status="quietly_archived")
        )
        await session.execute(
            update(DonnaSchedule)
            .where(
                DonnaSchedule.feature_id == feature.id,
                DonnaSchedule.fired.is_(False),
            )
            .values(
                fired=True,
                status="skipped",
                last_error="feature_archived",
            )
        )
        await session.commit()
        await session.refresh(feature)
        return feature


async def list_features(
    *,
    user_id: str,
    status: str | None = None,
) -> list[Feature]:
    """Return features for a user, optionally filtered by status."""
    from backend.db.session import async_session

    async with async_session() as session:
        stmt = select(Feature).where(Feature.user_id == user_id)
        if status:
            stmt = stmt.where(Feature.status == status)
        stmt = stmt.order_by(Feature.installed_at.desc())
        return list((await session.execute(stmt)).scalars().all())


async def update_feature_config(
    *,
    user_id: str,
    feature_id: str | None = None,
    template_id: str | None = None,
    config_patch: dict[str, Any],
) -> Feature | None:
    """Merge a partial config patch into ``features.config``.

    Validates each patched key against the manifest's ``config_schema``
    when available — unknown keys are rejected (typos shouldn't silently
    write to JSONB) and out-of-bounds numeric values are clamped to
    the declared ``min``/``max``.
    """
    from backend.db.session import async_session
    from backend.features.registry import get_registry

    if not config_patch:
        raise ValueError("config_patch must be non-empty")

    async with async_session() as session:
        feature = await _resolve_feature(
            session=session,
            user_id=user_id,
            feature_id=feature_id,
            template_id=template_id,
        )
        if feature is None:
            return None

        manifest = (
            get_registry().get_template(feature.template_id)
            if feature.template_id
            else None
        )
        merged = dict(feature.config or {})
        for key, value in config_patch.items():
            if manifest and key not in manifest.config_schema:
                raise ValueError(
                    f"unknown config key {key!r} for feature "
                    f"{feature.template_id}"
                )
            if manifest and isinstance(value, (int, float)):
                spec = manifest.config_schema[key]
                if spec.min is not None and value < spec.min:
                    value = spec.min
                if spec.max is not None and value > spec.max:
                    value = spec.max
            merged[key] = value

        feature.config = merged
        feature.updated_at = _utc_now_naive()
        await session.commit()
        await session.refresh(feature)
        return feature


def _utc_now_naive() -> datetime:
    from datetime import timezone

    return datetime.now(timezone.utc).replace(tzinfo=None)
