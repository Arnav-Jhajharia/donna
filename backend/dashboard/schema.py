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

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


# ── Base config ──────────────────────────────────────────────────────────
# Every model in this file accepts both camelCase (from the TS side / LLM
# output) and snake_case (from Python callers). When dumping to JSON for
# the frontend, always pass ``by_alias=True``.
class _PlanBase(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
        extra="ignore",
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
    illustration: Literal["mumbai", "none"] | None = None


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


class FooterBlock(_PlanBase):
    type: Literal["footer"]
    text: str


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
        FooterBlock,
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


# ── Top-level plan ────────────────────────────────────────────────────────
class PlanUser(_PlanBase):
    name: str
    initial: str


class DashboardPlan(_PlanBase):
    """The contract between the brain and the dashboard renderer.

    The brain emits one of these per ``compose_manifest`` call. The
    renderer prefers ``rows[]`` (visual contract §4) but falls back to
    legacy ``blocks[]`` flow when ``rows`` is absent.
    """

    id: str
    generated_at: str = Field(alias="generatedAt")
    user: PlanUser
    thesis: str
    moment: MomentTag
    blocks: list[Block] = Field(default_factory=list)
    rows: list[Row] | None = None
    intro: IntroSpec | None = None
