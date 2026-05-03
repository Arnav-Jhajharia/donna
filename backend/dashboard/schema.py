"""Pydantic mirror of dashboard/web/lib/plan.ts.

Field-for-field mirror of the TypeScript DashboardPlan, used as the
``schema`` argument to ``call_structured`` so Sonnet emits structurally
valid JSON via Anthropic tool-use mode.

Naming contract: TypeScript is camelCase (``generatedAt``, ``lastTouch``,
``trackerName``). Python keeps snake_case for ergonomics. The
``alias_generator=to_camel`` config + ``populate_by_name=True`` lets the
same model accept JSON from either side. Always serialize with
``model_dump(mode="json", by_alias=True)`` when handing JSON back to the
frontend or persisting to JSONB.

When extending: add a new BaseModel for the block kind, add it to the
``Block`` Union with its ``type`` literal as the discriminator. The
TypeScript registry already falls back to ``<PlaceholderFrame>`` for
unknown kinds, so partial schema drift degrades gracefully.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel


# ── Base config ──────────────────────────────────────────────────────────
# Every model in this file accepts both camelCase (from the TS side / LLM
# output) and snake_case (from Python callers). When dumping to JSON for
# the frontend, always pass ``by_alias=True``.
class _PlanBase(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
        # ``allow`` lets new fields like ``domain`` (block surface tag)
        # flow through the Pydantic round-trip without requiring a touch
        # on every block class. The renderer reads them directly from the
        # serialized JSON.
        extra="allow",
    )


# ── ActionVerb (discriminated on `v`) ─────────────────────────────────────
class _ActionStartTracker(_PlanBase):
    v: Literal["start_tracker"]
    name: str


class _ActionLogValue(_PlanBase):
    v: Literal["log_value"]
    tracker: str
    value: float
    unit: str | None = None


class _ActionCompletePick(_PlanBase):
    v: Literal["complete_pick"]
    pick_id: str = Field(alias="pickId")


class _ActionSnoozeReminder(_PlanBase):
    v: Literal["snooze_reminder"]
    reminder_id: str = Field(alias="reminderId")
    until: str


class _ActionMarkReminderDone(_PlanBase):
    v: Literal["mark_reminder_done"]
    reminder_id: str = Field(alias="reminderId")


class _ActionDismissAttention(_PlanBase):
    v: Literal["dismiss_attention"]
    attention_id: str = Field(alias="attentionId")


class _ActionAcceptAttention(_PlanBase):
    v: Literal["accept_attention"]
    attention_id: str = Field(alias="attentionId")


class _ActionConnectIntegration(_PlanBase):
    v: Literal["connect_integration"]
    provider: str


class _ActionAcceptDraft(_PlanBase):
    v: Literal["accept_draft"]
    draft_id: str = Field(alias="draftId")


class _ActionDecideOption(_PlanBase):
    v: Literal["decide_option"]
    decision_id: str = Field(alias="decisionId")
    option_id: str = Field(alias="optionId")


class _ActionQuickLog(_PlanBase):
    v: Literal["quick_log"]
    kind: str
    payload: Any = None


class _ActionOpenRelationship(_PlanBase):
    v: Literal["open_relationship"]
    person_id: str = Field(alias="personId")


class _ActionOpenNews(_PlanBase):
    v: Literal["open_news"]
    news_id: str = Field(alias="newsId")


class _ActionOpenTracker(_PlanBase):
    v: Literal["open_tracker"]
    tracker: str


class _ActionReplyChip(_PlanBase):
    v: Literal["reply_chip"]
    intent: str


ActionVerb = Annotated[
    Union[
        _ActionStartTracker,
        _ActionLogValue,
        _ActionCompletePick,
        _ActionSnoozeReminder,
        _ActionMarkReminderDone,
        _ActionDismissAttention,
        _ActionAcceptAttention,
        _ActionConnectIntegration,
        _ActionAcceptDraft,
        _ActionDecideOption,
        _ActionQuickLog,
        _ActionOpenRelationship,
        _ActionOpenNews,
        _ActionOpenTracker,
        _ActionReplyChip,
    ],
    Field(discriminator="v"),
]


# ── Common literal alphabets ──────────────────────────────────────────────
IconName = Literal[
    "phone", "drop", "bowl", "flower", "flame", "rupee",
    "moon", "sun", "heart", "leaf", "eye", "hourglass",
    "bell", "plug", "sparkles", "pencil", "mic", "check", "x",
]
SignalTone = Literal["ink", "rust", "moss", "amber", "oxblood"]
MomentTag = Literal[
    "dawn", "morning", "midday", "afternoon", "evening", "night", "late"
]

# Catalogue iconography — keys of `cIcons` in components/blocks/catalogue/icons.tsx.
CatIconName = Literal[
    "drop", "flame", "rupee", "envelope", "eye", "book", "link",
    "chev", "check", "plug", "coffee", "bowl", "moon", "heart",
]
TrackerTint = Literal["amber", "paper", "rust", "moss"]
QuickLogTint = Literal["amber", "rust", "moss"]
ScheduleSlotKind = Literal["meeting", "focus", "break", "travel", "personal"]
NoteKind = Literal["editorial", "bar", "confront"]
FooterKind = Literal["caps", "italic", "mark"]


# ── Blocks (discriminated on `type`) ──────────────────────────────────────
class ThesisBlock(_PlanBase):
    type: Literal["thesis"]
    sentence: str
    kicker: str | None = None


class HeroBlock(_PlanBase):
    type: Literal["hero"]
    date: str
    greeting: str
    subtext: str
    illustration: Literal["mumbai", "singapore", "none"] | None = None


class WhisperBlock(_PlanBase):
    type: Literal["whisper"]
    kicker: str
    body: str
    level: Literal["subtle", "loud"] | None = None


class WitnessBlock(_PlanBase):
    type: Literal["witness"]
    observation: str = Field(min_length=1)
    source: str | None = None


class ConfrontationBlock(_PlanBase):
    type: Literal["confrontation"]
    title: str
    body: str
    ask: str | None = None


class CelebrationBlock(_PlanBase):
    type: Literal["celebration"]
    title: str
    body: str
    badge: str | None = None


class ReflectionBlock(_PlanBase):
    type: Literal["reflection"]
    title: str
    prompts: list[str]


class OpenLoopItem(_PlanBase):
    id: str
    title: str
    age: str
    commitment: str


class OpenLoopsBlock(_PlanBase):
    type: Literal["open-loops"]
    title: str
    items: list[OpenLoopItem]


class WeatherOfYouBlock(_PlanBase):
    type: Literal["weather-of-you"]
    mood: str
    energy: float
    basis: str


class CalendarSlot(_PlanBase):
    id: str
    at: str
    label: str
    duration: int
    kind: Literal["meeting", "focus", "break", "travel", "personal"]


class CalendarShapeBlock(_PlanBase):
    type: Literal["calendar-shape"]
    title: str
    slots: list[CalendarSlot]
    shape_read: str | None = Field(default=None, alias="shapeRead")


class TodoItem(_PlanBase):
    id: str
    label: str
    meta: str
    source: str
    done: bool | None = None
    action: ActionVerb | None = None


class TodoListBlock(_PlanBase):
    type: Literal["todo-list"]
    title: str
    items: list[TodoItem]


class TrackerItem(_PlanBase):
    id: str
    title: str
    value: str
    unit: str
    sub: str
    progress: float
    icon: IconName
    tone: SignalTone
    tint: Literal["amber", "moss", "rust", "paper"]
    action: ActionVerb | None = None


class TrackerGridBlock(_PlanBase):
    type: Literal["tracker-grid"]
    title: str
    items: list[TrackerItem]


class NudgeItem(_PlanBase):
    id: str
    title: str
    meta: str
    cta: str
    icon: IconName
    variant: Literal["neutral", "moss", "amber", "featured"]
    progress: float | None = None
    action: ActionVerb | None = None


class NudgeGridBlock(_PlanBase):
    type: Literal["nudge-grid"]
    title: str
    items: list[NudgeItem]


class PermissionBlock(_PlanBase):
    type: Literal["permission"]
    title: str
    body: str
    action: ActionVerb | None = None


class ReminderItem(_PlanBase):
    id: str
    at: str
    label: str
    meta: str | None = None
    done: bool | None = None
    action: ActionVerb | None = None


class RemindersBlock(_PlanBase):
    type: Literal["reminders"]
    title: str
    items: list[ReminderItem]


class TrackerStarterBlock(_PlanBase):
    type: Literal["tracker-starter"]
    title: str
    rationale: str
    tracker_name: str = Field(alias="trackerName")
    cta: str
    icon: IconName
    action: ActionVerb


class RelationshipItem(_PlanBase):
    id: str
    name: str
    role: str | None = None
    last_touch: str = Field(alias="lastTouch")
    nudge: str | None = None
    initial: str
    action: ActionVerb | None = None


class RelationshipBlock(_PlanBase):
    type: Literal["relationship"]
    title: str
    items: list[RelationshipItem]


class NewsBriefItem(_PlanBase):
    id: str
    headline: str
    source: str
    tag: str | None = None
    url: str | None = None
    action: ActionVerb | None = None


class NewsBriefBlock(_PlanBase):
    type: Literal["news-brief"]
    title: str
    items: list[NewsBriefItem]


class NoteActions(_PlanBase):
    primary: str | None = None
    secondary: str | None = None
    tertiary: str | None = None


class NoteBlock(_PlanBase):
    """Catalogue archetype #02. Donna's voice on the moment.

    Three flavors via ``kind``:
      * ``editorial`` — borderless, italic kicker, breathing whitespace (default).
      * ``bar`` — rust-tinted card with a 2px accent stripe.
      * ``confront`` — oxblood, italic eyebrow, serif body. One per plan, ever.
    """

    type: Literal["note"]
    kind: NoteKind | None = None
    eyebrow: str | None = None
    body: str
    actions: NoteActions | None = None


class FooterBlock(_PlanBase):
    """Catalogue archetype #03. Three flavors via ``kind``:

      * ``caps`` — uppercase status line.
      * ``italic`` — warmest, serif italic.
      * ``mark`` — the donna mark with hairline rules; for morning-hero moments.
    """

    type: Literal["footer"]
    text: str
    kind: FooterKind | None = None


# ── Catalogue blocks (#04–#21) ────────────────────────────────────────────
# Mirrors the TypeScript types in
# ``dashboard/web/components/blocks/catalogue/CatBlocks.tsx`` and
# ``dashboard/web/components/blocks/catalogue/CatTracker.tsx``. The frontend
# registry routes ``c-*`` block ``type`` strings directly to these renderers,
# so structural drift here = visual breakage there.


# 04 · Tracker
class TrackerCatItem(_PlanBase):
    label: str
    value: str
    unit: str
    detail: str | None = None
    progress: float
    icon: CatIconName
    tint: TrackerTint


class CatTrackerBlock(_PlanBase):
    type: Literal["c-tracker"]
    variant: Literal["pair", "borderless", "hero"]
    title: str | None = None
    right: str | None = None
    items: list[TrackerCatItem]
    history: list[float] | None = None
    today_index: int | None = Field(default=None, alias="todayIndex")
    week_labels: list[str] | None = Field(default=None, alias="weekLabels")


# 05 · Watch
class WatchItem(_PlanBase):
    subject: str
    signal: str
    at: str
    delta: str | None = None
    up: bool | None = None


class CatWatchBlock(_PlanBase):
    type: Literal["c-watch"]
    variant: Literal["rows", "ticker"]
    title: str | None = None
    items: list[WatchItem]


# 06 · Brief
class BriefIndexItem(_PlanBase):
    subject: str
    cadence: str
    next_fire: str = Field(alias="nextFire")


class CatBriefBlock(_PlanBase):
    type: Literal["c-brief"]
    variant: Literal["newsstand", "index"]
    cadence_label: str | None = Field(default=None, alias="cadenceLabel")
    fire_window: str | None = Field(default=None, alias="fireWindow")
    title: str | None = None
    highlight: str | None = None
    teaser: str | None = None
    chips: list[str] | None = None
    items: list[BriefIndexItem] | None = None


# 07 · Prep
class PrepItem(_PlanBase):
    label: str
    done: bool | None = None


class CatPrepBlock(_PlanBase):
    type: Literal["c-prep"]
    variant: Literal["inline", "card"]
    eyebrow: str | None = None
    title: str
    items: list[PrepItem]
    next_line: str | None = Field(default=None, alias="nextLine")
    meta: str | None = None


# 08 · Schedule
class ScheduleSlotItem(_PlanBase):
    at: str
    label: str
    # The LLM occasionally emits a bare integer (minutes). Accept either
    # and coerce to a "<n>m" string in the validator so the wire shape
    # the frontend expects (e.g. "90m") is preserved.
    duration: str
    kind: ScheduleSlotKind

    @field_validator("duration", mode="before")
    @classmethod
    def _coerce_duration(cls, v: Any) -> str:
        if isinstance(v, int):
            return f"{v}m"
        if isinstance(v, float):
            return f"{int(v)}m"
        return str(v) if v is not None else ""


class ScheduleStripItem(_PlanBase):
    x: float
    w: float
    kind: ScheduleSlotKind


class CatScheduleBlock(_PlanBase):
    type: Literal["c-schedule"]
    variant: Literal["column", "strip"]
    title: str | None = None
    right: str | None = None
    slots: list[ScheduleSlotItem] | None = None
    blocks: list[ScheduleStripItem] | None = None
    ticks: list[str] | None = None
    glance: str | None = None
    range: str | None = None


# 09 · Streak / Milestone
class CatStreakBlock(_PlanBase):
    type: Literal["c-streak"]
    variant: Literal["inline", "badge"]
    eyebrow: str
    body: str
    count: int | None = None


# 10 · Person
class PersonItem(_PlanBase):
    name: str
    role: str | None = None
    nudge: str
    ago: str


class CatPersonBlock(_PlanBase):
    type: Literal["c-person"]
    variant: Literal["list", "hero"]
    title: str | None = None
    items: list[PersonItem] | None = None
    hero_name: str | None = Field(default=None, alias="heroName")
    hero_eyebrow: str | None = Field(default=None, alias="heroEyebrow")
    hero_body: str | None = Field(default=None, alias="heroBody")
    cta_primary: str | None = Field(default=None, alias="ctaPrimary")
    cta_secondary: str | None = Field(default=None, alias="ctaSecondary")


# 11 · Reminder
class ReminderItemCat(_PlanBase):
    label: str
    at: str
    done: bool | None = None


class CatReminderBlock(_PlanBase):
    type: Literal["c-reminder"]
    variant: Literal["editorial", "pill"]
    title: str | None = None
    right: str | None = None
    items: list[ReminderItemCat]


# 12 · Quick log
class QuickLogChip(_PlanBase):
    label: str
    icon: CatIconName
    tint: QuickLogTint | None = None


class CatQuickLogBlock(_PlanBase):
    type: Literal["c-quicklog"]
    variant: Literal["chips", "tray"]
    chips: list[QuickLogChip]


# 13 · Pick
class CatPickBlock(_PlanBase):
    type: Literal["c-pick"]
    variant: Literal["editorial", "card"]
    kind: str
    title: str
    body: str | None = None
    source: str | None = None
    year: str | None = None


# 14 · Offer
class CatOfferBlock(_PlanBase):
    type: Literal["c-offer"]
    variant: Literal["hero", "twoline"]
    eyebrow: str | None = None
    title: str
    rationale: str | None = None
    cta_accept: str = Field(alias="ctaAccept")
    cta_dismiss: str | None = Field(default=None, alias="ctaDismiss")


# 15 · Draft
class CatDraftBlock(_PlanBase):
    type: Literal["c-draft"]
    variant: Literal["letter", "inline"]
    recipient: str
    subject: str
    preview: str


# 16 · Decision
class DecisionOption(_PlanBase):
    label: str
    hint: str | None = None


class CatDecisionBlock(_PlanBase):
    type: Literal["c-decision"]
    variant: Literal["tiles", "stack"]
    question: str
    highlight: str | None = None
    options: list[DecisionOption]


# 17 · Confrontation
class CatConfrontBlock(_PlanBase):
    type: Literal["c-confront"]
    variant: Literal["quiet", "card"]
    eyebrow: str | None = None
    title: str
    body: str | None = None


# 18 · Reflection
class CatReflectionBlock(_PlanBase):
    type: Literal["c-reflection"]
    variant: Literal["prompt", "card"]
    eyebrow: str | None = None
    prompt: str


# 19 · Open loop
class CatOpenLoopItem(_PlanBase):
    """Catalogue-flavored open loop item.

    Distinct from the legacy ``OpenLoopItem`` used by ``OpenLoopsBlock`` —
    catalogue carries the natural-language quote shape (commitment + ago)
    rather than the tracked-id shape.
    """

    commitment: str
    ago: str
    due: str | None = None
    overdue: bool | None = None


class CatOpenLoopBlock(_PlanBase):
    type: Literal["c-openloop"]
    variant: Literal["quote", "dashed"]
    title: str | None = None
    right: str | None = None
    items: list[CatOpenLoopItem]


# 20 · Permission
class CatPermissionBlock(_PlanBase):
    type: Literal["c-permission"]
    variant: Literal["soft", "editorial"]
    provider: str
    body: str
    cta_connect: str | None = Field(default=None, alias="ctaConnect")
    cta_dismiss: str | None = Field(default=None, alias="ctaDismiss")


# 21 · Read
class ReadItem(_PlanBase):
    headline: str
    source: str
    tag: str | None = None
    meta: str | None = None


class CatReadBlock(_PlanBase):
    type: Literal["c-read"]
    variant: Literal["index", "card"]
    items: list[ReadItem]


# 22 · Capability — the "things donna can do for you" surface.
# Renders as tappable chips. Each tap sends a pre-filled WhatsApp message
# (the ``intent``) to donna so she can do the thing. This is the dashboard's
# command palette in catalogue clothing.
class CapabilityItem(_PlanBase):
    label: str
    intent: str
    icon: CatIconName | None = None


class CatCapabilityBlock(_PlanBase):
    type: Literal["c-capability"]
    variant: Literal["chips", "rows"]
    title: str | None = None
    eyebrow: str | None = None
    items: list[CapabilityItem]


# 23 · Recipe mosaic — Day 1 / sparse-signal CTA surface.
# Each tile = "one tap and donna sets up a multi-step pipeline" (e.g.
# "track my calories from now on, ping at 8pm if i'm under 1500"). On
# tap, the dashboard opens a WhatsApp deeplink with the ``primer`` as the
# pre-filled message — the actual setup runs through donna's normal tool
# loop on the inbound. Renders Pinterest-masonry: tall tiles (size="tall")
# carry more explanatory body copy; short tiles are recognisably one-shot.
class RecipeItem(_PlanBase):
    title: str
    body: str  # 1–4 lines of plain prose explaining what donna will set up
    primer: str  # the WhatsApp message body sent on tap
    tone: Literal["ink", "rust", "moss", "amber", "oxblood"] | None = None
    icon: CatIconName | None = None
    size: Literal["short", "tall"] | None = None  # default short


class CatRecipeMosaicBlock(_PlanBase):
    type: Literal["c-recipe-mosaic"]
    eyebrow: str | None = None  # e.g. "start something"
    title: str | None = None  # e.g. "five things donna can do for you. one tap."
    items: list[RecipeItem]


Block = Annotated[
    Union[
        ThesisBlock,
        HeroBlock,
        WhisperBlock,
        WitnessBlock,
        ConfrontationBlock,
        CelebrationBlock,
        ReflectionBlock,
        OpenLoopsBlock,
        WeatherOfYouBlock,
        CalendarShapeBlock,
        TodoListBlock,
        TrackerGridBlock,
        NudgeGridBlock,
        PermissionBlock,
        RemindersBlock,
        TrackerStarterBlock,
        RelationshipBlock,
        NewsBriefBlock,
        NoteBlock,
        FooterBlock,
        # catalogue archetypes #04–#21
        CatTrackerBlock,
        CatWatchBlock,
        CatBriefBlock,
        CatPrepBlock,
        CatScheduleBlock,
        CatStreakBlock,
        CatPersonBlock,
        CatReminderBlock,
        CatQuickLogBlock,
        CatPickBlock,
        CatOfferBlock,
        CatDraftBlock,
        CatDecisionBlock,
        CatConfrontBlock,
        CatReflectionBlock,
        CatOpenLoopBlock,
        CatPermissionBlock,
        CatReadBlock,
        CatCapabilityBlock,
        CatRecipeMosaicBlock,
    ],
    Field(discriminator="type"),
]


# ── Row-based composition (visual contract §4) ────────────────────────────
SlotSize = Literal[
    "full", "three-quarters", "two-thirds", "half", "third", "quarter"
]


class Cell(_PlanBase):
    size: SlotSize
    block: Block


class Row(_PlanBase):
    title: str | None = None
    meta: str | None = None
    cols: list[Cell]


class IntroSpec(_PlanBase):
    kicker: str
    greeting_prefix: str | None = Field(default=None, alias="greetingPrefix")
    accent: str | None = None
    greeting_suffix: str | None = Field(default=None, alias="greetingSuffix")
    greeting: str | None = None
    place: str | None = None
    illustration_id: Literal[
        "mumbai", "tea", "book", "moon", "glass", "walk", "none"
    ] | None = Field(default=None, alias="illustrationId")


# ── Multi-page composition ────────────────────────────────────────────────
# Catalogue mode v2: the dashboard is three pages, not one screen.
#
#   id="now"   — the editorial read for this moment (hero-led, restrained)
#   id="today" — the operational view (schedule, trackers, watches, briefs)
#   id="hold"  — what donna is holding + what she can do (open loops,
#                people, integrations, capability surface)
#
# The renderer treats `pages[]` as the source of truth when present and
# falls back to flat `blocks[]` for backwards-compatible single-page plans.
PageId = Literal["now", "today", "hold"]


class DashboardPage(_PlanBase):
    id: PageId
    kicker: str | None = None  # short eyebrow ("now", "today", "what i'm holding")
    thesis: str | None = None  # page-level read, optional
    blocks: list[Block] = Field(default_factory=list)


# ── Top-level plan ────────────────────────────────────────────────────────
class PlanUser(_PlanBase):
    name: str
    initial: str


class DashboardPlan(_PlanBase):
    """The contract between the brain and the dashboard renderer.

    Catalogue mode v2: the renderer reads ``pages[]`` first (three-page
    surface). Legacy single-page plans without ``pages`` still work via
    the flat ``blocks[]`` array.
    """

    id: str
    generated_at: str = Field(alias="generatedAt")
    user: PlanUser
    thesis: str
    moment: MomentTag
    blocks: list[Block] = Field(default_factory=list)
    rows: list[Row] | None = None
    intro: IntroSpec | None = None
    pages: list[DashboardPage] | None = None
