"""Build dashboard card candidates from a user's active features.

The composer (``backend.dashboard.compose``) calls
``read_feature_card_candidates`` to fold feature-declared
``dashboard_cards`` into the LLM brief. The cards are hydrated with the
feature's current state + config so values like ``today_count`` and
``target_glasses`` are deterministic — the LLM only chooses *which*
cards earn space and how to phrase the hero / thesis.

The candidate set is bounded by what features the user actually has
installed. The LLM cannot invent a hydration tracker block if the user
hasn't installed the hydration feature; nothing to invent against.

This module is read-only on the DB. State derivation that would
otherwise belong in feature-specific hooks (``update_hydration_state``)
is computed *opportunistically* here from the observations payload the
composer already loaded — no extra queries, no Phase 4 dependency.
Once Phase 4 lands hook handlers that maintain ``feature.state``, this
module reads from there directly.

Phase 2 scope: the candidates are emitted as plaintext rows in the
brief. The LLM picks among them. Phase 3+ may bypass the LLM entirely
for live re-fill (when ``feature.state`` changes without a moment
shift).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date as _date, datetime
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Feature, Observation
from backend.features.manifest import DashboardCardDecl, FeatureManifest

logger = logging.getLogger(__name__)


_FLAG_ENV = "DONNA_FEATURE_DASHBOARD_CARDS"


def is_feature_dashboard_enabled(user_id: str | None = None) -> bool:
    """Feature flag gate.

    Default off so production rendering stays exactly as today. Set
    ``DONNA_FEATURE_DASHBOARD_CARDS=1`` (global) to enable for everyone,
    or ``DONNA_FEATURE_DASHBOARD_CARDS=<user_id>`` to enable for a
    single user (Arnav-only validation).
    """
    raw = (os.environ.get(_FLAG_ENV) or "").strip()
    if not raw:
        return False
    if raw == "1":
        return True
    if user_id and user_id == raw:
        return True
    return False


@dataclass(frozen=True)
class CardCandidate:
    """Hydrated dashboard card declaration ready to plant in the brief."""

    feature_id: str
    feature_template_id: str | None
    feature_name: str
    archetype: str
    variant: str | None
    domain: str | None
    priority: int
    render_hint: str | None
    fill: dict[str, Any]

    def to_brief_line(self) -> str:
        """One line per candidate for the LLM brief.

        Shape kept compact so the existing brief budget isn't blown.
        """
        bits = [self.archetype]
        if self.variant:
            bits.append(f"variant={self.variant}")
        if self.domain:
            bits.append(f"domain={self.domain}")
        head = " ".join(bits)
        fill_summary = ", ".join(
            f"{k}={v}" for k, v in self.fill.items() if v not in (None, "")
        )
        feature_tag = f"feature={self.feature_template_id or self.feature_name}"
        line = f"- {head} ({feature_tag}, priority={self.priority})"
        if fill_summary:
            line += f"  fill: {fill_summary}"
        if self.render_hint:
            line += f"  hint: {self.render_hint}"
        return line


# -- Public entry point -----------------------------------------------------


async def read_feature_card_candidates(
    *,
    session: AsyncSession,
    user_id: str,
    observations: Sequence[Observation],
    now_local: datetime,
) -> list[CardCandidate]:
    """Return ordered card candidates for the user's active features.

    ``observations`` is reused from the composer's existing fetch — we
    don't re-read the DB. ``now_local`` is the user-local datetime; used
    for the day boundary and "moment" hints.
    """
    try:
        from backend.features.registry import get_registry
    except Exception:
        logger.exception("dashboard_cards: feature registry unavailable")
        return []

    rows = (
        await session.execute(
            select(Feature).where(
                Feature.user_id == user_id,
                Feature.status == "active",
            )
        )
    ).scalars().all()
    if not rows:
        return []

    registry = get_registry()
    today_local = now_local.date()
    candidates: list[CardCandidate] = []

    for feature in rows:
        if not feature.template_id:
            continue
        manifest = registry.get_template(feature.template_id)
        if manifest is None or not manifest.dashboard_cards:
            continue

        state = _derive_state(
            manifest=manifest,
            feature_state=feature.state or {},
            observations=observations,
            user_id=user_id,
            today_local=today_local,
        )
        config = feature.config or {}

        for card in manifest.dashboard_cards:
            fill = _hydrate_fill(card.fill or {}, state=state, config=config)
            candidates.append(
                CardCandidate(
                    feature_id=feature.id,
                    feature_template_id=feature.template_id,
                    feature_name=manifest.name,
                    archetype=card.archetype,
                    variant=card.variant,
                    domain=card.domain,
                    priority=card.priority,
                    render_hint=card.render_when,
                    fill=fill,
                )
            )

    candidates.sort(key=lambda c: c.priority, reverse=True)
    return candidates


# -- State derivation -------------------------------------------------------


def _derive_state(
    *,
    manifest: FeatureManifest,
    feature_state: dict[str, Any],
    observations: Sequence[Observation],
    user_id: str,
    today_local: _date,
) -> dict[str, Any]:
    """Return the state dict the manifest's fill placeholders see.

    Layered: persisted ``feature.state`` is the truth (Phase 4 hooks
    write here). On top, we layer opportunistic counters derived from
    the observations the composer already loaded — so today's
    ``today_count`` is correct even before the hook dispatcher exists.
    """
    state: dict[str, Any] = dict(feature_state)

    primary_types = {
        d.type for d in manifest.observations if d.owner == "primary"
    }
    if not primary_types:
        return state

    today_count = 0
    today_sum: dict[str, float] = {}
    for obs in observations:
        if obs.user_id != user_id:
            continue
        if obs.type not in primary_types:
            continue
        # Only count observations whose event_time falls on the user's
        # local today. Observations are stored UTC-naive — caller passes
        # the local date so we don't need to TZ-convert each row, and the
        # composer already filters to the last ~36h upstream.
        ev = obs.event_time
        if ev is None or ev.date() != today_local:
            continue
        today_count += 1
        fields = obs.fields or {}
        for key, value in fields.items():
            if isinstance(value, (int, float)):
                today_sum[key] = today_sum.get(key, 0) + value

    state.setdefault("today_count", today_count)
    for key, total in today_sum.items():
        state.setdefault(f"today_sum_{key}", total)
        # Manifests often want the per-field number directly. Only
        # override when persisted state hasn't claimed the key.
        state.setdefault(key, total)
    return state


# -- Placeholder hydration --------------------------------------------------


def _hydrate_fill(
    template: dict[str, Any],
    *,
    state: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Replace ``{state.X}`` and ``{config.X}`` tokens in fill values.

    Only top-level scalar values are hydrated — nested dicts are kept
    as-is. Unknown placeholders are left untouched (so the LLM can see
    them and explicitly choose to drop / handle).
    """
    out: dict[str, Any] = {}
    for key, raw in template.items():
        if isinstance(raw, str):
            out[key] = _hydrate_str(raw, state=state, config=config)
        else:
            out[key] = raw
    return out


def _hydrate_str(
    raw: str, *, state: dict[str, Any], config: dict[str, Any]
) -> Any:
    """Replace placeholders in a single string.

    A pure-placeholder string (`"{state.today_count}"`) returns the raw
    Python value (an int) so consumers can inspect it. A mixed string
    (`"{state.today_count}/{config.target_glasses}"`) returns a
    formatted string.
    """
    stripped = raw.strip()
    # Pure placeholder — return the underlying value untouched.
    if stripped.startswith("{") and stripped.endswith("}") and "{" not in stripped[1:-1]:
        token = stripped[1:-1]
        return _resolve_token(token, state=state, config=config, default=raw)

    out = raw
    # Cheap O(n) replacement — manifests never have more than a few tokens.
    cursor = 0
    while True:
        start = out.find("{", cursor)
        if start == -1:
            break
        end = out.find("}", start + 1)
        if end == -1:
            break
        token = out[start + 1 : end]
        value = _resolve_token(token, state=state, config=config, default=None)
        if value is None:
            cursor = end + 1
            continue
        out = out[:start] + str(value) + out[end + 1 :]
        cursor = start + len(str(value))
    return out


def _resolve_token(
    token: str,
    *,
    state: dict[str, Any],
    config: dict[str, Any],
    default: Any,
) -> Any:
    """Resolve ``state.foo`` / ``config.bar`` to their backing dict values."""
    if "." not in token:
        return default
    head, _, key = token.partition(".")
    head = head.strip()
    key = key.strip()
    if head == "state":
        return state.get(key, default)
    if head == "config":
        return config.get(key, default)
    return default
