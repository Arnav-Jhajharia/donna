"""Install a feature manifest for a user.

``install_feature`` is the single entry point for both system features
(via ``install_feature(user_id, template_id)``) and Phase 3 user-composed
features. It is idempotent: re-installing the same template for the same
user is a no-op that returns the existing row.

What install does, in order:

1. Resolve the manifest from the registry.
2. Verify required integrations are connected.
3. Look up the existing Feature row (idempotent path).
4. Create the row with merged config (defaults + overrides).
5. Spawn each manifest attention as an ``AttentionRow`` tagged with
   ``feature_id``. Phase 1 stores the manifest's spawn-time hint on the
   AttentionRow payload; promotion to a full ``Attention`` lives in
   Phase 2.
6. Materialise the next fire of each cron entry as a ``DonnaSchedule``
   row tagged with ``feature_id``. Recurrence is honoured by the
   existing schedule worker once ``recurrence`` is set.
7. Return the Feature row.

Failures at any step roll back the in-flight session — partial installs
are a brand-damaging silent regression and we'd rather refuse and let
the caller retry.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.manifest import (
    AttentionDecl,
    CronDecl,
    FeatureManifest,
)

logger = logging.getLogger(__name__)


# -- Public entry point -----------------------------------------------------


async def install_feature(
    *,
    user_id: str,
    template_id: str,
    config_overrides: dict[str, Any] | None = None,
) -> "InstallResult":
    """Install a system feature for a user.

    Returns an ``InstallResult`` carrying the persisted feature row id,
    the spawned attention ids, and the materialised schedule ids. The
    return shape is intentionally simple — callers (the BRAIN tool
    wrapper, future lifecycle tools) only need ids.
    """
    from sqlalchemy import select

    from backend.db.models import Feature
    from backend.db.session import async_session
    from backend.features.registry import get_registry

    registry = get_registry()
    manifest = registry.get_template(template_id)
    if manifest is None:
        raise ValueError(
            f"unknown feature template_id={template_id!r}; "
            f"known: {registry.template_ids()}"
        )

    overrides = config_overrides or {}
    merged_config = _merge_config(manifest, overrides)

    async with async_session() as session:
        await _verify_integrations(
            session=session, user_id=user_id, manifest=manifest
        )

        existing = await _get_existing_feature(
            session=session,
            user_id=user_id,
            template_id=template_id,
            name=manifest.name,
        )
        if existing is not None:
            # Idempotent: same template for same user = return existing.
            # Config overrides on a re-install are intentionally NOT
            # applied here. Phase 2 ``update_feature_config`` is the
            # right surface for that — re-install must be a no-op so
            # callers don't accidentally clobber user-edited config.
            return InstallResult(
                feature_id=existing.id,
                attention_ids=tuple(),
                schedule_ids=tuple(),
                created=False,
            )

        feature = Feature(
            id=_generate_id(),
            user_id=user_id,
            template_id=template_id,
            name=manifest.name,
            description=manifest.description,
            surface=manifest.surface,
            icon=manifest.icon,
            tone=manifest.tone,
            status="active",
            installed_at=_now_utc_naive(),
            config=merged_config,
            state={},
            manifest_version=manifest.manifest_version,
        )
        session.add(feature)
        await session.flush()  # populate feature.id for FK use below

        attention_ids = await _spawn_attentions(
            session=session,
            user_id=user_id,
            feature=feature,
            manifest=manifest,
        )
        schedule_ids = await _materialise_cron(
            session=session,
            user_id=user_id,
            feature=feature,
            manifest=manifest,
        )
        backfilled = await _backfill_observations(
            session=session,
            user_id=user_id,
            feature=feature,
            manifest=manifest,
        )
        if backfilled:
            logger.info(
                "feature %s: backfilled %d observations user=%s",
                feature.template_id,
                backfilled,
                user_id,
            )
        await session.commit()

    return InstallResult(
        feature_id=feature.id,
        attention_ids=tuple(attention_ids),
        schedule_ids=tuple(schedule_ids),
        created=True,
    )


# -- Result shape -----------------------------------------------------------


class InstallResult:
    """Lightweight container for the install side-effects.

    Not a frozen dataclass because some callers (tests) construct one
    incrementally; immutability is enforced at the SQL layer.
    """

    __slots__ = ("feature_id", "attention_ids", "schedule_ids", "created")

    def __init__(
        self,
        *,
        feature_id: str,
        attention_ids: tuple[str, ...],
        schedule_ids: tuple[str, ...],
        created: bool,
    ) -> None:
        self.feature_id = feature_id
        self.attention_ids = attention_ids
        self.schedule_ids = schedule_ids
        self.created = created

    def __repr__(self) -> str:
        return (
            f"InstallResult(feature_id={self.feature_id!r}, "
            f"attention_ids={self.attention_ids!r}, "
            f"schedule_ids={self.schedule_ids!r}, "
            f"created={self.created})"
        )


# -- Integration check ------------------------------------------------------


async def _verify_integrations(
    *, session: AsyncSession, user_id: str, manifest: FeatureManifest
) -> None:
    """Block install if any required integration is not connected.

    Phase 1 only checks presence — the per-watch fan-out is Phase 4. A
    missing integration raises ``MissingIntegrationError`` so the BRAIN
    tool wrapper can surface a clear "connect Gmail first" reply.
    """
    required_apps = [i.app for i in manifest.integrations if i.required]
    if not required_apps:
        return

    from sqlalchemy import select

    from backend.db.models import Integration

    rows = (
        await session.execute(
            select(Integration).where(
                Integration.user_id == user_id,
                Integration.status == "connected",
                Integration.product.in_(required_apps),
            )
        )
    ).scalars().all()
    connected = {row.product for row in rows}
    missing = [app for app in required_apps if app not in connected]
    if missing:
        raise MissingIntegrationError(missing)


class MissingIntegrationError(Exception):
    """Raised when a required integration is not connected."""

    def __init__(self, missing: list[str]) -> None:
        super().__init__(
            f"required integrations not connected: {', '.join(missing)}"
        )
        self.missing = tuple(missing)


# -- Idempotency lookup -----------------------------------------------------


async def _get_existing_feature(
    *,
    session: AsyncSession,
    user_id: str,
    template_id: str,
    name: str,
) -> Any:
    """Find an existing Feature row for this (user, template) or name.

    ``UNIQUE (user_id, name)`` prevents duplicate-name collisions even
    if the user-composed manifest renames a feature; the per-template
    lookup is the primary check.
    """
    from sqlalchemy import select

    from backend.db.models import Feature

    stmt = select(Feature).where(
        Feature.user_id == user_id,
        Feature.template_id == template_id,
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is not None:
        return row
    # Fallback: same user_id + name. Catches edge cases where two
    # template manifests share a name but only one was installed; the
    # UNIQUE constraint prevents simultaneous installs.
    stmt = select(Feature).where(
        Feature.user_id == user_id, Feature.name == name
    )
    return (await session.execute(stmt)).scalar_one_or_none()


# -- Config merge -----------------------------------------------------------


def _merge_config(
    manifest: FeatureManifest, overrides: dict[str, Any]
) -> dict[str, Any]:
    """Defaults from manifest.config_schema + caller overrides.

    Caller overrides win on key collisions. Unknown keys in overrides
    are kept as-is — Phase 2 ``update_feature_config`` will validate
    against the schema; Phase 1 favours flexibility for user-composed
    features that may extend the schema at install time.
    """
    config: dict[str, Any] = {}
    for key, field in manifest.config_schema.items():
        config[key] = field.default
    for key, value in overrides.items():
        config[key] = value
    return config


# -- Attention spawning -----------------------------------------------------


async def _spawn_attentions(
    *,
    session: AsyncSession,
    user_id: str,
    feature: Any,
    manifest: FeatureManifest,
) -> list[str]:
    """Create one ``AttentionRow`` per manifest.attention entry.

    Phase 1 stores the manifest's spawn-time hint on the row's payload
    so a Phase 2 promoter can hydrate it into a full Attention. We
    deliberately skip the ``donna.attention.author`` LLM round-trip
    here — install is deterministic and feature manifests already
    declare the cadence and card.

    The row's ``feature_id`` FK ties the attention's lifecycle to the
    feature's lifecycle (pause / archive / etc. land in Phase 2).
    """
    from backend.db.models import AttentionRow

    spawned: list[str] = []
    for decl in manifest.attentions:
        row_id = _generate_id()
        cadence_type = _resolve_cadence_type(decl, feature.config)
        payload = _attention_payload(
            decl=decl,
            feature=feature,
            cadence_type=cadence_type,
        )
        row = AttentionRow(
            id=row_id,
            user_id=user_id,
            title=decl.title or f"{manifest.name} {decl.card}",
            card=decl.card,
            cadence_type=cadence_type,
            origin="user_explicit",
            status="live",
            payload=payload,
            feature_id=feature.id,
        )
        session.add(row)
        spawned.append(row_id)
    return spawned


def _resolve_cadence_type(
    decl: AttentionDecl, config: dict[str, Any]
) -> str:
    """Pick the AttentionRow.cadence_type column value.

    The manifest may either set ``cadence`` directly (``on_event``) or
    template it via ``cadence_template`` (``every_N_minutes``) which
    binds to a config key. ``scheduled`` is the canonical column value
    for cadenced pings; ``on_event`` is the canonical for tally cards.
    """
    if decl.cadence:
        return decl.cadence
    if decl.cadence_template == "every_N_minutes":
        return "scheduled"
    return decl.cadence_template or "on_event"


def _attention_payload(
    *,
    decl: AttentionDecl,
    feature: Any,
    cadence_type: str,
) -> dict[str, Any]:
    """Build the AttentionRow.payload JSONB for a feature-spawned row.

    Stores the manifest-author hint so the Phase 2 promoter can hydrate
    a full ``donna.attention.schema.Attention`` without re-deriving from
    the manifest. Keep it explicit (no nested derivations) so a row
    inspected in psql is self-describing.
    """
    return {
        "feature_id": feature.id,
        "feature_template_id": feature.template_id,
        "card": decl.card,
        "subject_type": decl.subject_type,
        "cadence_type": cadence_type,
        "cadence_template": decl.cadence_template,
        "cadence_param_key": decl.cadence_param_key,
        "extractor_hint": decl.extractor_hint,
        "title": decl.title,
        "description": decl.description,
        "spawned_by": "feature_install",
        "manifest_version": feature.manifest_version,
        "status": "live",
    }


# -- Backfill ---------------------------------------------------------------


_BACKFILL_CAP = 1000


async def _backfill_observations(
    *,
    session: AsyncSession,
    user_id: str,
    feature: Any,
    manifest: FeatureManifest,
) -> int:
    """Tag pre-feature observations matching this feature's owned types.

    Runs once per fresh install. Only matches rows where ``feature_id``
    is currently NULL — never overwrites another feature's tag. Capped
    at ``_BACKFILL_CAP`` rows to keep the install transaction bounded;
    if a user has more than 1k untagged observations of one type, the
    older ones simply stay NULL (still readable, just not tagged).

    Only feature-owned ``primary`` types backfill — subscriber types
    (Phase 4) shouldn't claim writes from other features' history.
    """
    if not manifest.observations:
        return 0

    from sqlalchemy import select, update

    from backend.db.models import Observation

    primary_types = [
        d.type for d in manifest.observations if d.owner == "primary"
    ]
    if not primary_types:
        return 0

    candidate_ids = (
        await session.execute(
            select(Observation.id)
            .where(
                Observation.user_id == user_id,
                Observation.type.in_(primary_types),
                Observation.feature_id.is_(None),
            )
            .order_by(Observation.created_at.desc())
            .limit(_BACKFILL_CAP)
        )
    ).scalars().all()

    if not candidate_ids:
        return 0

    await session.execute(
        update(Observation)
        .where(Observation.id.in_(candidate_ids))
        .values(feature_id=feature.id)
    )
    return len(candidate_ids)


# -- Cron materialisation ---------------------------------------------------


async def _materialise_cron(
    *,
    session: AsyncSession,
    user_id: str,
    feature: Any,
    manifest: FeatureManifest,
) -> list[str]:
    """Create one ``DonnaSchedule`` row per manifest.cron entry.

    Each row carries ``feature_id`` so the future ``pause_feature`` /
    ``archive_feature`` tools (Phase 2) can scope cleanups. The next
    fire is computed via croniter against the user's local timezone
    when ``tz_aware=True``.
    """
    if not manifest.cron:
        return []

    from sqlalchemy import select

    from backend.db.models import DonnaSchedule, User

    user_row = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    user_tz = (
        user_row.timezone
        if user_row and user_row.timezone
        else "Asia/Singapore"
    )
    user_phone = user_row.phone if user_row else ""

    from backend.features.handlers import is_cron_handler_registered

    schedule_ids: list[str] = []
    for cron_decl in manifest.cron:
        if not is_cron_handler_registered(cron_decl.handler):
            # Refuse to schedule a row whose handler isn't wired. The
            # worker's else-branch would otherwise send a literal
            # "reminder" WhatsApp text — a brand-damaging silent
            # regression. Phase 4 will register handlers; until then the
            # cron row stays declarative-only.
            logger.warning(
                "feature %s cron %s: skipping schedule materialisation "
                "(handler %r not registered)",
                feature.template_id,
                cron_decl.name,
                cron_decl.handler,
            )
            continue
        next_fire = _next_cron_fire(cron_decl, tz=user_tz)
        if next_fire is None:
            logger.warning(
                "feature %s cron %s: skipping (invalid expression %r)",
                feature.template_id,
                cron_decl.name,
                cron_decl.schedule,
            )
            continue
        row_id = _generate_id()
        recurrence_meta = {
            "feature_id": feature.id,
            "feature_template_id": feature.template_id,
            "cron_name": cron_decl.name,
            "cron_expr": cron_decl.schedule,
            "tz_aware": cron_decl.tz_aware,
            "handler": cron_decl.handler,
            "recurrence": cron_decl.recurrence,
            "user_tz": user_tz,
        }
        schedule_row = DonnaSchedule(
            id=row_id,
            user_id=user_id,
            phone=user_phone,
            fire_at=next_fire,
            origin="donna",
            recurrence=cron_decl.recurrence,
            context={
                "source": "feature_cron",
                "feature_id": feature.id,
                "cron_name": cron_decl.name,
            },
            recurrence_meta=recurrence_meta,
            feature_id=feature.id,
        )
        session.add(schedule_row)
        schedule_ids.append(row_id)
    return schedule_ids


def _next_cron_fire(decl: CronDecl, *, tz: str) -> datetime | None:
    """Compute the next UTC-naive fire time for a cron expression.

    Mirrors the helper in ``donna.attention.firing._next_cron`` rather
    than importing it — that module is a heavy import surface and we
    want install to stay light.
    """
    try:
        from croniter import croniter
    except ImportError:
        logger.warning(
            "croniter not installed; falling back to one-hour offset for "
            "feature cron"
        )
        return _now_utc_naive() + timedelta(hours=1)

    try:
        zone = ZoneInfo(tz)
    except Exception:
        zone = ZoneInfo("UTC")
    now_local = datetime.now(zone)
    try:
        itr = croniter(decl.schedule, now_local)
    except (ValueError, KeyError):
        return None
    nxt_local = itr.get_next(datetime)
    if nxt_local.tzinfo is None:
        nxt_local = nxt_local.replace(tzinfo=zone)
    return nxt_local.astimezone(timezone.utc).replace(tzinfo=None)


# -- Misc helpers -----------------------------------------------------------


def _now_utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _generate_id() -> str:
    return str(uuid.uuid4())
