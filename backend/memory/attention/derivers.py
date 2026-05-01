"""Deriver implementations.

Each Deriver turns a SourceResult into a ``current_state`` dict. The
shape of current_state varies by card type but always carries:
    - day:               ISO date in user-local
    - value:             the headline number/string for the dashboard
    - count:             entries that contributed
    - target:            optional goal for progress display
    - evidence_ids:      list of source items that contributed
    - last_event_at:     ISO of the most recent contributing event
    - source:            "deterministic" | "haiku" | "external"
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from backend.memory.attention.runtime import DeriveContext, SourceResult

logger = logging.getLogger(__name__)


class SumDeriver:
    """Sum a numeric field across observations.

    Field name is chosen by the spec's ``sources.params.tag``:
        meal_calories  → fields.calories
        expense / spend → fields.amount
        sleep_hours    → fields.hours
        water          → fields.glasses (or count of obs)
    """

    _TAG_TO_FIELD: dict[str, str] = {
        "meal_calories": "calories",
        "expense": "amount",
        "spend": "amount",
        "sleep_hours": "hours",
    }

    def _target_for(self, attention: Any) -> float | None:
        """Pull a numeric goal from spec.description if mentioned, else None."""
        spec = getattr(attention, "spec", None)
        desc = (getattr(spec, "description", "") or "").lower() if spec else ""
        # Cheap heuristic — looks for "X cal goal", "X cal target", "X kcal".
        import re

        m = re.search(r"(\d+)\s*(cal|kcal|hr|hour|min)", desc)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
        return None

    async def derive(
        self,
        *,
        attention: Any,
        source: SourceResult,
        ctx: DeriveContext,
    ) -> dict[str, Any]:
        tag = source.meta.get("tag") or ""
        field = self._TAG_TO_FIELD.get(tag, "value")

        items = source.items
        contributions: list[dict[str, Any]] = []
        total = 0.0
        unit: str | None = None
        last_event_at: str | None = None

        for it in items:
            fields = it.get("fields") or {}
            v = fields.get(field)
            if v is None:
                continue
            try:
                num = float(v)
            except (TypeError, ValueError):
                continue
            total += num
            unit = unit or fields.get("unit")
            contributions.append(
                {"id": it.get("id"), field: num, "event_time": it.get("event_time")}
            )
            if it.get("event_time"):
                if last_event_at is None or it["event_time"] > last_event_at:
                    last_event_at = it["event_time"]

        target = self._target_for(attention)

        # Format the headline value cleanly for dashboard display.
        if total == int(total):
            display_value = str(int(total))
        else:
            display_value = f"{total:.1f}"

        state: dict[str, Any] = {
            "value": display_value,
            "value_numeric": total,
            "count": len(contributions),
            "target": target,
            "evidence_ids": [c.get("id") for c in contributions],
            "last_event_at": last_event_at,
            "source": "deterministic",
            "rollup": "sum",
            "field": field,
            "unit": unit,
        }
        if target and target > 0:
            state["progress"] = max(0.0, min(1.0, total / target))
        return state


class CountDeriver:
    """Count items in the source. For boolean trackers (did the thing today?)
    and frequency trackers (water glasses, exercise sessions)."""

    async def derive(
        self,
        *,
        attention: Any,
        source: SourceResult,
        ctx: DeriveContext,
    ) -> dict[str, Any]:
        n = len(source.items)
        last_event_at: str | None = None
        for it in source.items:
            t = it.get("event_time")
            if t and (last_event_at is None or t > last_event_at):
                last_event_at = t
        return {
            "value": str(n),
            "value_numeric": float(n),
            "count": n,
            "target": None,
            "evidence_ids": [it.get("id") for it in source.items],
            "last_event_at": last_event_at,
            "source": "deterministic",
            "rollup": "count",
        }


class AgeDeriver:
    """For open_loop attentions: returns the age of each loop and flags
    overdue ones based on the spec's threshold (or a sensible default)."""

    DEFAULT_OVERDUE_DAYS = 5

    async def derive(
        self,
        *,
        attention: Any,
        source: SourceResult,
        ctx: DeriveContext,
    ) -> dict[str, Any]:
        items = source.items
        now = ctx.user_local_now
        with_age: list[dict[str, Any]] = []
        for it in items:
            try:
                ca = it.get("created_at")
                if not ca:
                    continue
                created = datetime.fromisoformat(ca.replace("Z", "+00:00"))
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                age_days = (now - created).days
                with_age.append(
                    {
                        "id": it.get("id"),
                        "content": it.get("content", "")[:200],
                        "age_days": age_days,
                        "overdue": age_days >= self.DEFAULT_OVERDUE_DAYS,
                    }
                )
            except Exception:
                continue
        overdue_count = sum(1 for x in with_age if x["overdue"])
        return {
            "value": str(len(with_age)),
            "value_numeric": float(len(with_age)),
            "count": len(with_age),
            "overdue_count": overdue_count,
            "items": with_age,
            "source": "deterministic",
            "rollup": "age",
        }


class NextFireDeriver:
    """For ping attentions: returns the next scheduled fire time.

    The actual cron evaluation lives in the existing schedule_worker;
    this deriver just exposes a snapshot for the dashboard.
    """

    async def derive(
        self,
        *,
        attention: Any,
        source: SourceResult,
        ctx: DeriveContext,
    ) -> dict[str, Any]:
        spec = getattr(attention, "spec", None)
        cadence = getattr(spec, "cadence", None) if spec else None
        cad_type = getattr(getattr(cadence, "type", None), "value", None) or "?"
        title = getattr(spec, "title", "") if spec else ""
        return {
            "value": title or "ping",
            "cadence_type": cad_type,
            "source": "deterministic",
            "rollup": "next_fire",
        }
