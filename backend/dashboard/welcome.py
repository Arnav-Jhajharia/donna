"""Static welcome plan for brand-new users.

When a new ``User`` row is created, ``user_lookup`` writes this manifest
to ``dashboard_manifests`` synchronously so the first dashboard a user
sees on Day 1 is not a 404 with "text donna with redo my dashboard."

No LLM call. No DB reads. Pure function of name + timezone.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from backend.dashboard.schema import (
    DashboardPlan,
    FooterBlock,
    HeroBlock,
    PlanUser,
    ThesisBlock,
)

_DEFAULT_TZ = "Asia/Singapore"

_GREETING_BY_MOMENT: dict[str, str] = {
    "late": "still up.",
    "dawn": "early one.",
    "morning": "morning.",
    "midday": "midday.",
    "afternoon": "afternoon.",
    "evening": "evening.",
    "night": "tonight.",
}


def _moment_for(now_local: datetime) -> str:
    h = now_local.hour
    if h < 5:
        return "late"
    if h < 7:
        return "dawn"
    if h < 11:
        return "morning"
    if h < 14:
        return "midday"
    if h < 17:
        return "afternoon"
    if h < 20:
        return "evening"
    return "night"


def _resolve_now_local(tz_name: str | None) -> datetime:
    try:
        return datetime.now(ZoneInfo(tz_name or _DEFAULT_TZ))
    except Exception:
        return datetime.now(ZoneInfo(_DEFAULT_TZ))


def build_welcome_plan(
    *,
    user_id: str,
    name: str | None,
    timezone_name: str | None,
    now_local: datetime | None = None,
) -> DashboardPlan:
    """Static three-block welcome plan: hero greeting, thesis ask, footer.

    Used for the first dashboard load before donna has any signal to
    compose with. The fixture is intentionally small so the empty
    state never feels like a broken loop.
    """
    display_name = (name or "").strip() or "friend"
    initial = display_name[:1].upper() or "·"

    when = now_local or _resolve_now_local(timezone_name)
    moment = _moment_for(when)
    server_now = when.isoformat()
    greeting = _GREETING_BY_MOMENT.get(moment, "hi.")

    return DashboardPlan(
        id=f"plan:{user_id}:welcome",
        generated_at=server_now,
        user=PlanUser(name=display_name, initial=initial),
        thesis="we just met. tell me one thing you're holding right now.",
        moment=moment,
        blocks=[
            HeroBlock(
                type="hero",
                date=when.strftime("%a, %b %d"),
                greeting=greeting,
                subtext="i'm donna. text me what's on your mind and i'll start holding it.",
                illustration="none",
            ),
            ThesisBlock(
                type="thesis",
                sentence="we just met. tell me one thing you're holding right now.",
                kicker="day 1",
            ),
            FooterBlock(
                type="footer",
                text="i'll be here when you reply.",
            ),
        ],
    )
