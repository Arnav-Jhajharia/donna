"""Canonical recipe bank for the c-recipe-mosaic block.

Each recipe is a multi-step pipeline donna can stand up in one tap:
{integration + attention + cadence + threshold logic}. The bank lives
here so the dashboard composer doesn't hardcode the set — instead a
selector picks recipes the user DOESN'T already have running, so the
mosaic stays useful even on day 30 (not just day 1).

The metadata on each ``Recipe`` (``provides``, ``requires``, ``surface``)
drives both the selector (skip recipes whose ``provides`` overlap with
the user's existing attentions/integrations) and the prompt (which
surfaces a recipe belongs to).

Adding a new recipe:
1. Append a ``Recipe(...)`` to ``RECIPE_BANK`` below.
2. Set ``provides`` to one or more capability tags — the selector treats
   tags as exclusive (one tracker per provides=tracks_calories).
3. Set ``requires`` to integration toolkits that must be connected, OR
   leave empty if the recipe runs purely from the BRAIN's existing
   tools (e.g. nightly journal, calorie estimator).
4. Pick a ``surface`` so the renderer knows which icon/tone to use when
   a chips-variant mosaic mixes recipes from multiple surfaces.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Surface = Literal["work", "body", "day", "people", "money", "mind"]
Tone = Literal["ink", "rust", "moss", "amber", "oxblood"]


@dataclass(frozen=True)
class Recipe:
    """One tile in the recipe mosaic.

    ``title`` is the short label shown on the chip / mosaic tile.
    ``primer`` is the WhatsApp message body sent on tap — the BRAIN
    handles the actual workflow setup on the inbound message.

    ``provides`` are capability tags the recipe stands up; the selector
    skips recipes whose tags already exist on the user's attentions.

    ``requires`` are integration toolkit slugs the recipe depends on
    (e.g. ``gmail``); the selector down-ranks recipes whose integrations
    aren't connected — the user can still tap to connect on the way in.
    """

    id: str
    title: str
    primer: str
    surface: Surface
    tone: Tone
    icon: str  # CatIconName — bowl / envelope / eye / heart / moon / etc.
    provides: tuple[str, ...] = field(default_factory=tuple)
    requires: tuple[str, ...] = field(default_factory=tuple)
    body: str = ""  # optional longer description for tall mosaic tiles


RECIPE_BANK: tuple[Recipe, ...] = (
    Recipe(
        id="calories_hands_off",
        title="track my calories",
        primer=(
            "track my calories from now on. estimate from anything i "
            "mention. ping me at 8pm if i'm under 1500."
        ),
        surface="body",
        tone="moss",
        icon="bowl",
        provides=("tracks_calories",),
        body=(
            "just mention what you ate. donna estimates, logs, runs the "
            "daily total. pings at 8pm if you're under 1500. weekly "
            "recap saturday."
        ),
    ),
    Recipe(
        id="inbox_5pm_wrap",
        title="wrap my inbox at 5",
        primer=(
            "set up a 5pm inbox wrap — the 3 emails worth replying to "
            "before i log off"
        ),
        surface="work",
        tone="rust",
        icon="envelope",
        provides=("inbox_brief",),
        requires=("gmail",),
        body=(
            "every weekday at 5, donna scans your inbox and sends you "
            "the 3 things worth replying to before you log off."
        ),
    ),
    Recipe(
        id="monday_week_read",
        title="monday week-read",
        primer=(
            "every monday at 8am, read my calendar and send me a "
            "one-paragraph read on the week ahead"
        ),
        surface="day",
        tone="amber",
        icon="eye",
        provides=("week_brief",),
        requires=("googlecalendar",),
        body=(
            "every monday 8am, donna reads your calendar and sends one "
            "paragraph on what you're walking into this week."
        ),
    ),
    Recipe(
        id="silent_vip_detector",
        title="watch my people",
        primer=(
            "track my last touch with mom, dad, and three friends i'll "
            "name. ping me if anyone goes quiet for two weeks."
        ),
        surface="people",
        tone="rust",
        icon="heart",
        provides=("people_staleness_watcher",),
        body=(
            "pick five people. donna pings you if any of them go quiet "
            "for two weeks."
        ),
    ),
    Recipe(
        id="nightly_journal",
        title="nightly journal",
        primer=(
            "every night at 10pm, ask me what stuck with me today and "
            "what i'm proud of. keep a running journal."
        ),
        surface="mind",
        tone="oxblood",
        icon="moon",
        provides=("nightly_reflection",),
        body=(
            "10pm every night: what stuck with you today? what are you "
            "proud of? running journal donna keeps for you."
        ),
    ),
    Recipe(
        id="hydration_silent_pings",
        title="hydration without nagging",
        primer=(
            "log glasses by saying 'water'. ping me at 11/2/4 only if "
            "i'm behind. silent if i'm on track."
        ),
        surface="body",
        tone="moss",
        icon="drop",
        provides=("tracks_hydration",),
        body=(
            "log glasses by saying 'water.' donna pings 11 / 2 / 4 only "
            "if you're behind. silent if you're on track."
        ),
    ),
    Recipe(
        id="sleep_no_app",
        title="sleep tracker (no app)",
        primer=(
            "track my sleep — when i say 'going to bed' note it, when i "
            "say 'morning' close it, weekly recap on sundays."
        ),
        surface="body",
        tone="moss",
        icon="moon",
        provides=("tracks_sleep",),
        body=(
            "say 'going to bed' — donna logs it. say 'morning' — donna "
            "closes it. sunday recap: avg, drift, your worst night."
        ),
    ),
    Recipe(
        id="weekly_burn",
        title="weekly burn",
        primer=(
            "every spend i mention by amount, log it. saturday morning: "
            "where it went, what's recurring, what jumped vs last week. "
            "ping me if i blow past my weekly target."
        ),
        surface="money",
        tone="amber",
        icon="rupee",
        provides=("tracks_spend", "weekly_money_brief"),
        body=(
            "mention any spend by amount, donna logs it. saturday "
            "morning: where it went, what's recurring, what jumped."
        ),
    ),
    Recipe(
        id="subscription_radar",
        title="subscription radar",
        primer=(
            "watch my upcoming subscription renewals from gmail and "
            "calendar. give me a 3-day heads-up so i can cancel before "
            "the charge."
        ),
        surface="money",
        tone="amber",
        icon="rupee",
        provides=("subscription_watcher",),
        requires=("gmail",),
        body=(
            "donna watches your inbox + calendar for renewals and gives "
            "you a 3-day heads up so you can cancel before the charge."
        ),
    ),
    Recipe(
        id="trips_auto_tracker",
        title="auto-track my trips",
        primer=(
            "every flight or hotel confirmation that lands in my inbox "
            "becomes a trip. keep the running list."
        ),
        surface="day",
        tone="amber",
        icon="eye",
        provides=("trips_watcher",),
        requires=("gmail",),
        body=(
            "every confirmation that lands in your inbox becomes a "
            "trip. itinerary, hotel, return date — donna keeps the "
            "running list."
        ),
    ),
    Recipe(
        id="prep_new_people",
        title="prep me for new people",
        primer=(
            "30 min before any meeting with someone i haven't met "
            "before, prep me with what you know about them and why this "
            "meeting probably exists."
        ),
        surface="day",
        tone="rust",
        icon="eye",
        provides=("new_attendee_prep",),
        requires=("googlecalendar",),
        body=(
            "30 min before any meeting with someone you haven't met, "
            "donna pulls up what she knows about them, last touch, and "
            "why this meeting probably exists."
        ),
    ),
    Recipe(
        id="stale_loops_sweep",
        title="sunday loop sweep",
        primer=(
            "sunday evening, list every commitment i made this week and "
            "didn't close. let me mark done / push / drop in one tap."
        ),
        surface="work",
        tone="rust",
        icon="check",
        provides=("weekly_loops_sweep",),
        body=(
            "sunday evening, donna lists every commitment you made this "
            "week and didn't close. mark done / push / drop in one tap."
        ),
    ),
    Recipe(
        id="avoidance_question",
        title="the avoidance question",
        primer=(
            "every sunday at 7pm, ask me 'what's the one thing you're "
            "avoiding?' and remember the answer."
        ),
        surface="mind",
        tone="oxblood",
        icon="moon",
        provides=("weekly_avoidance",),
        body=(
            "sunday 7pm: 'what's the one thing you're avoiding?' donna "
            "remembers. asks again next sunday."
        ),
    ),
    Recipe(
        id="market_5pm_wrap",
        title="5pm market wrap",
        primer=(
            "watch ADBE, NVDA, and anything else i mention. give me a "
            "5pm read on whether anything moved today."
        ),
        surface="work",
        tone="amber",
        icon="eye",
        provides=("market_watcher",),
        body=(
            "ADBE, NVDA, anything you mention — donna watches and gives "
            "you a 5pm read on whether anything moved."
        ),
    ),
)


def recipe_by_id(recipe_id: str) -> Recipe | None:
    """O(n) lookup; the bank is small (<50) so a dict isn't worth the
    serialization overhead."""
    for r in RECIPE_BANK:
        if r.id == recipe_id:
            return r
    return None
