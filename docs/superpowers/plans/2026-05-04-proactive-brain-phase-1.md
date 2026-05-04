# Proactive Brain Phase 1 (Skeletons) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the fat-contract Tier 3 path in mirror-mode. Every proactive-event escalation logs both the legacy thin-directive draft AND the new fat-contract draft to a `proactive_dispatch_telemetry` table, with zero user-visible behavior change. Lets us evaluate the new path against today's path before flipping anything live.

**Architecture:** Add new types (`SpeechAct`, `ProactiveDispatchTelemetry` row), new tools (`donna_runtime/tools_tier3.py`), new context builder (`donna_runtime/context_builder_tier3.py`), new system prompt + mode (`mode="proactive_tier3"`). Wire a counterfactual run into the existing `proactive/dispatcher.py:_escalate_to_brain` so today's legacy thin-directive ship continues unchanged AND the fat-contract Tier 3 turn runs alongside, logs its decision, but does not ship. Mirror mode is the discipline.

**Tech Stack:** Python 3.11+, Pydantic v2, SQLAlchemy 2 + alembic, Anthropic SDK (Sonnet 4.6 + Haiku 4.5), Postgres, pytest.

**Spec:** [`2026-05-04-proactive-brain-redesign.md`](../specs/2026-05-04-proactive-brain-redesign.md) (Phase 1 only).

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `proactive/events.py` | modify | Add `SpeechAct` literal + `speech_act` field on `ProactiveEvent`; extend `ProactiveSource` with `"system_b_web"` |
| `proactive/sources/_inference.py` | create | `infer_speech_act(source, payload, signals)` helper |
| `proactive/judge.py` | modify | Add `channel_hint` + `reclassify_speech_act` to `JudgeResult` dataclass + `_JudgeOut` Pydantic schema |
| `proactive/fresh_signal.py` | create | Conditional source-specific pre-fetcher (`fetch_for_event`) |
| `proactive/dispatcher.py` | modify | Add counterfactual fat-contract Tier 3 run in `_escalate_to_brain`, mirror-only |
| `donna_runtime/tools_tier3.py` | create | Six tools: `quick_check`, `read_external`, `reshape_attention`, `kill_attention`, `send_burst` (with `push`+`surface_at`), `skip` |
| `donna_runtime/context_builder_tier3.py` | create | `build_tier3_context(event, judge, escalation_reason)` returns the 11-block user message |
| `donna_runtime/prompt_tier3.py` | create | Tier 3 system prompt string |
| `donna_runtime/brain.py` | modify | Add `mode="proactive_tier3"` branch — register Tier 3 tools, lower `max_turns=3`, use Tier 3 system prompt |
| `donna_runtime/config.py` | modify | Extend `DonnaAgentConfig.mode` literal + add `tier3_max_turns: int = 3` field |
| `db/models.py` | modify | Add `ProactiveDispatchTelemetry` ORM row |
| `backend/db/migrations/versions/0023_proactive_dispatch_telemetry.py` | create | Alembic migration for telemetry table |
| `scripts/proactive_counterfactual_eval.py` | create | CLI report comparing legacy vs fat-contract decisions over a window |

**Tests:**

| File | Action |
|---|---|
| `backend/tests/proactive/test_events_speech_act.py` | create |
| `backend/tests/proactive/test_judge_schema.py` | create |
| `backend/tests/proactive/test_speech_act_inference.py` | create |
| `backend/tests/proactive/test_fresh_signal.py` | create |
| `backend/tests/proactive/test_dispatcher_tier3_mirror.py` | create |
| `backend/tests/runtime/test_tools_tier3.py` | create |
| `backend/tests/runtime/test_context_builder_tier3.py` | create |
| `backend/tests/runtime/test_prompt_tier3.py` | create |

---

## Task 1: Add SpeechAct + speech_act field on ProactiveEvent

**Files:**
- Modify: `proactive/events.py`
- Test: `backend/tests/proactive/test_events_speech_act.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/proactive/test_events_speech_act.py`:

```python
"""ProactiveEvent envelope — speech_act field and system_b_web source."""
from __future__ import annotations

import pytest

from proactive.events import ProactiveEvent, SpeechAct


def test_proactive_event_carries_speech_act():
    event = ProactiveEvent(
        user_id="u1",
        source="email",
        source_ref="msg_abc",
        topic_key="thread_xyz",
        speech_act="heads_up",
        payload={"from_address": "luca@x.com"},
    )
    assert event.speech_act == "heads_up"


def test_proactive_event_speech_act_defaults_to_thought_youd_want():
    """Back-compat default keeps unmigrated callers working in Phase 1."""
    event = ProactiveEvent(
        user_id="u1",
        source="attention_fire",
        source_ref="att_1",
        topic_key="att_1",
    )
    assert event.speech_act == "thought_youd_want"


def test_speech_act_allows_five_canonical_values():
    valid: list[SpeechAct] = [
        "dont_forget",
        "heads_up",
        "i_noticed",
        "now_the_moment",
        "thought_youd_want",
    ]
    for sa in valid:
        e = ProactiveEvent(
            user_id="u1",
            source="email",
            source_ref="r",
            topic_key="t",
            speech_act=sa,
        )
        assert e.speech_act == sa


def test_proactive_source_includes_system_b_web():
    event = ProactiveEvent(
        user_id="u1",
        source="system_b_web",
        source_ref="https://example.com/post",
        topic_key="sysb:example.com:abc",
        speech_act="thought_youd_want",
    )
    assert event.source == "system_b_web"
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest backend/tests/proactive/test_events_speech_act.py -v
```
Expected: ImportError on `SpeechAct` (not yet defined) or `system_b_web` literal mismatch.

- [ ] **Step 3: Modify `proactive/events.py`**

Replace the `ProactiveSource` literal and `ProactiveEvent` dataclass:

```python
ProactiveSource = Literal[
    "email",
    "attention_fire",
    "attention_offer",
    "calendar",
    "pattern",
    "system_b_web",          # NEW: System B web hits as a unified source
]

SpeechAct = Literal[
    "dont_forget",            # keeper — user opted in, never miss
    "heads_up",               # alert — world moved, situation changed
    "i_noticed",              # mirror — pattern reflected, soft register
    "now_the_moment",         # anticipator — time has arrived
    "thought_youd_want",      # curator — earn the interrupt
]


@dataclass(frozen=True)
class ProactiveEvent:
    """Source-agnostic envelope for the proactive pipeline."""

    user_id: str
    source: ProactiveSource
    source_ref: str
    topic_key: str
    # speech_act defaults to thought_youd_want for back-compat with existing
    # call sites. Source adapters set it explicitly post-Phase-1.
    speech_act: SpeechAct = "thought_youd_want"
    payload: dict[str, Any] = field(default_factory=dict)
    signals: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest backend/tests/proactive/test_events_speech_act.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add proactive/events.py backend/tests/proactive/test_events_speech_act.py
git commit -m "feat(proactive): add SpeechAct + speech_act field on ProactiveEvent

Five canonical speech acts: dont_forget, heads_up, i_noticed,
now_the_moment, thought_youd_want. Default = thought_youd_want for
back-compat. Adds system_b_web as a unified source.

Phase 1 of proactive brain redesign."
```

---

## Task 2: Add channel_hint + reclassify_speech_act to JudgeResult

**Files:**
- Modify: `proactive/judge.py`
- Test: `backend/tests/proactive/test_judge_schema.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/proactive/test_judge_schema.py`:

```python
"""JudgeResult schema — channel_hint and reclassify_speech_act."""
from __future__ import annotations

from proactive.events import SpeechAct
from proactive.judge import JudgeResult, _JudgeOut


def test_judge_result_default_channel_hint_is_none():
    j = JudgeResult(
        action="ping",
        register="alert",
        draft="luca replied to the term sheet thread",
        tie_in=("luca",),
        needs_tools=False,
        reasoning="ok",
        raw_response="{}",
    )
    assert j.channel_hint is None
    assert j.reclassify_speech_act is None


def test_judge_result_accepts_channel_hint():
    j = JudgeResult(
        action="ping",
        register="alert",
        draft="x",
        tie_in=(),
        needs_tools=False,
        reasoning="",
        raw_response="",
        channel_hint="whatsapp",
    )
    assert j.channel_hint == "whatsapp"


def test_judge_result_accepts_reclassify():
    sa: SpeechAct = "heads_up"
    j = JudgeResult(
        action="ping",
        register=None,
        draft=None,
        tie_in=(),
        needs_tools=False,
        reasoning="",
        raw_response="",
        reclassify_speech_act=sa,
    )
    assert j.reclassify_speech_act == "heads_up"


def test_judge_out_pydantic_accepts_new_fields():
    out = _JudgeOut(
        action="ping",
        register="soft",
        draft="hey",
        tie_in=["x"],
        needs_tools=False,
        reasoning="",
        channel_hint="dashboard",
        reclassify_speech_act="i_noticed",
    )
    assert out.channel_hint == "dashboard"
    assert out.reclassify_speech_act == "i_noticed"


def test_judge_out_pydantic_back_compat_omits_new_fields():
    out = _JudgeOut(
        action="drop",
        register=None,
        draft=None,
        tie_in=[],
        needs_tools=False,
        reasoning="not interesting",
    )
    assert out.channel_hint is None
    assert out.reclassify_speech_act is None
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest backend/tests/proactive/test_judge_schema.py -v
```
Expected: AttributeError on `channel_hint` / `reclassify_speech_act`.

- [ ] **Step 3: Modify `proactive/judge.py`**

Add two fields on the dataclass and Pydantic model:

```python
# In JudgeResult dataclass (search for `class JudgeResult:` ~line 35):
@dataclass(frozen=True)
class JudgeResult:
    action: JudgeAction
    register: JudgeRegister | None
    draft: str | None
    tie_in: tuple[str, ...]
    needs_tools: bool
    reasoning: str
    raw_response: str
    # NEW (default-None for back-compat with existing constructions)
    channel_hint: Literal["whatsapp", "dashboard", "digest", "hold"] | None = None
    reclassify_speech_act: "SpeechAct | None" = None
```

Add to the Pydantic `_JudgeOut` model (search for `class _JudgeOut(BaseModel):` ~line 60):

```python
class _JudgeOut(BaseModel):
    action: Literal["ping", "hold", "drop"] = Field(...)
    register: Literal["alert", "soft"] | None = Field(default=None)
    draft: str | None = Field(default=None)
    tie_in: list[str] = Field(default_factory=list)
    needs_tools: bool = Field(default=False)
    reasoning: str = Field(default="")
    # NEW
    channel_hint: Literal["whatsapp", "dashboard", "digest", "hold"] | None = Field(
        default=None,
        description="Tier 2's channel routing recommendation. Tier 3 may override.",
    )
    reclassify_speech_act: Literal[
        "dont_forget", "heads_up", "i_noticed", "now_the_moment", "thought_youd_want"
    ] | None = Field(
        default=None,
        description="If Tier 2 disagrees with the source's speech_act tag.",
    )
```

Import `SpeechAct` at top of file:

```python
from proactive.events import SpeechAct  # for the dataclass annotation
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest backend/tests/proactive/test_judge_schema.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add proactive/judge.py backend/tests/proactive/test_judge_schema.py
git commit -m "feat(proactive): add channel_hint + reclassify_speech_act to JudgeResult

Tier 2 may suggest channel (whatsapp/dashboard/digest/hold) and may
reclassify the source's speech_act tag. Both default None for
back-compat with existing call sites.

Phase 1 of proactive brain redesign."
```

---

## Task 3: Speech-act inference helper for source adapters

**Files:**
- Create: `proactive/sources/__init__.py` (if missing)
- Create: `proactive/sources/_inference.py`
- Test: `backend/tests/proactive/test_speech_act_inference.py`

- [ ] **Step 1: Verify `proactive/sources/` exists**

```
ls proactive/sources/
```
If missing, create it with `touch proactive/sources/__init__.py`.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/proactive/test_speech_act_inference.py`:

```python
"""Speech-act inference per source/payload."""
from __future__ import annotations

from proactive.sources._inference import infer_speech_act


def test_email_defaults_to_heads_up():
    assert infer_speech_act("email", payload={}, signals={}) == "heads_up"


def test_attention_fire_user_requested_ping_is_dont_forget():
    payload = {"origin": "USER_REQUESTED", "card": "PING"}
    assert infer_speech_act("attention_fire", payload, {}) == "dont_forget"


def test_attention_fire_donna_anticipated_is_now_the_moment():
    payload = {"origin": "DONNA_ANTICIPATED"}
    assert infer_speech_act("attention_fire", payload, {}) == "now_the_moment"


def test_attention_fire_observation_frequency_is_i_noticed():
    payload = {
        "origin": "SHADOW_INFERRED",
        "proposer": "ObservationFrequencyProposer",
    }
    assert infer_speech_act("attention_fire", payload, {}) == "i_noticed"


def test_calendar_is_heads_up():
    assert infer_speech_act("calendar", payload={}, signals={}) == "heads_up"


def test_system_b_web_default_is_thought_youd_want():
    assert (
        infer_speech_act("system_b_web", payload={}, signals={})
        == "thought_youd_want"
    )


def test_system_b_web_upgrades_to_heads_up_when_urgent():
    sa = infer_speech_act(
        "system_b_web",
        payload={"angle": "postmortem"},
        signals={"is_urgent_signal": True},
    )
    assert sa == "heads_up"


def test_unknown_source_falls_back_to_thought_youd_want():
    assert infer_speech_act("pattern", payload={}, signals={}) == "thought_youd_want"
```

- [ ] **Step 3: Run test to verify it fails**

```
pytest backend/tests/proactive/test_speech_act_inference.py -v
```
Expected: ImportError on `_inference`.

- [ ] **Step 4: Create `proactive/sources/_inference.py`**

```python
"""Infer ProactiveEvent.speech_act from source + payload + signals.

The mapping is intentionally narrow and explicit. Source adapters call
this when they don't have a more specific reason to set speech_act
themselves.
"""
from __future__ import annotations

from typing import Any

from proactive.events import ProactiveSource, SpeechAct


_DEFAULT: SpeechAct = "thought_youd_want"


def infer_speech_act(
    source: ProactiveSource,
    payload: dict[str, Any],
    signals: dict[str, Any],
) -> SpeechAct:
    """Return the speech_act for an event whose adapter didn't set one.

    Today's mappings:
      email             -> heads_up
      calendar          -> heads_up
      attention_fire    -> based on origin: USER_REQUESTED+PING -> dont_forget,
                           DONNA_ANTICIPATED -> now_the_moment,
                           SHADOW_INFERRED + ObservationFrequencyProposer
                              -> i_noticed,
                           else -> thought_youd_want
      system_b_web      -> heads_up if signals.is_urgent_signal else
                           thought_youd_want
      attention_offer   -> thought_youd_want (offered cards are passive)
      pattern           -> thought_youd_want (cross-source patterns are
                           low-confidence by default)
    """
    if source == "email":
        return "heads_up"
    if source == "calendar":
        return "heads_up"
    if source == "attention_fire":
        return _infer_attention_fire(payload)
    if source == "system_b_web":
        return "heads_up" if signals.get("is_urgent_signal") else "thought_youd_want"
    if source in {"attention_offer", "pattern"}:
        return "thought_youd_want"
    return _DEFAULT


def _infer_attention_fire(payload: dict[str, Any]) -> SpeechAct:
    origin = str(payload.get("origin") or "").upper()
    card = str(payload.get("card") or "").upper()
    proposer = str(payload.get("proposer") or "")
    if origin == "USER_REQUESTED" and card == "PING":
        return "dont_forget"
    if origin == "DONNA_ANTICIPATED":
        return "now_the_moment"
    if origin == "SHADOW_INFERRED" and proposer == "ObservationFrequencyProposer":
        return "i_noticed"
    return _DEFAULT
```

- [ ] **Step 5: Run test to verify it passes**

```
pytest backend/tests/proactive/test_speech_act_inference.py -v
```
Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add proactive/sources/_inference.py backend/tests/proactive/test_speech_act_inference.py
git commit -m "feat(proactive): infer_speech_act helper for source adapters

Maps source + payload + signals to one of the five canonical speech acts.
Per-source rules: email/calendar -> heads_up; attention_fire by origin;
system_b_web upgrades to heads_up on urgent signals; rest default
thought_youd_want.

Phase 1 of proactive brain redesign."
```

---

## Task 4: ProactiveDispatchTelemetry table + migration

**Files:**
- Modify: `db/models.py` (append new model)
- Create: `backend/db/migrations/versions/0023_proactive_dispatch_telemetry.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/proactive/test_dispatch_telemetry.py`:

```python
"""ProactiveDispatchTelemetry — schema + insertability."""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select

from db.models import ProactiveDispatchTelemetry, generate_uuid


@pytest.mark.asyncio
async def test_telemetry_row_can_be_inserted(db):
    """db fixture provides an async session bound to a fresh test database."""
    async with db() as session:
        row = ProactiveDispatchTelemetry(
            id=generate_uuid(),
            user_id="user_test",
            source="email",
            speech_act="heads_up",
            topic_key="thread_xyz",
            tier1_score=0.75,
            arbiter_decision="allowed",
            tier2_action="ping",
            tier2_draft="luca replied to the term sheet thread",
            tier3_invoked=True,
            tier3_outcome="ship",
            channel="whatsapp",
            counterfactual_legacy_outbound_count=1,
            counterfactual_fat_contract_outcome="ship",
            event_at=datetime.utcnow(),
        )
        session.add(row)
        await session.commit()

        fetched = (
            await session.execute(
                select(ProactiveDispatchTelemetry).where(
                    ProactiveDispatchTelemetry.id == row.id
                )
            )
        ).scalar_one()
        assert fetched.speech_act == "heads_up"
        assert fetched.counterfactual_fat_contract_outcome == "ship"
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest backend/tests/proactive/test_dispatch_telemetry.py -v
```
Expected: ImportError on `ProactiveDispatchTelemetry` or migration not applied.

- [ ] **Step 3: Append model to `db/models.py`**

After the existing `PendingProactiveNote` model:

```python
class ProactiveDispatchTelemetry(Base):
    """Per-event audit row for the proactive pipeline.

    Phase 1 use: log both legacy thin-directive Tier 3 outcomes AND the
    new fat-contract counterfactual side-by-side, so we can compare
    decisions and drafts before flipping anything live.

    Long-term: the canonical observability table for arbiter / Tier 2 /
    Tier 3 decisions. Replaces ad-hoc logging.
    """

    __tablename__ = "proactive_dispatch_telemetry"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    event_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    # Event identity
    source: Mapped[str] = mapped_column(String, nullable=False)
    speech_act: Mapped[str] = mapped_column(String, nullable=False)
    topic_key: Mapped[str] = mapped_column(String, nullable=False)

    # Tier 1
    tier1_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Arbiter
    arbiter_decision: Mapped[str | None] = mapped_column(String, nullable=True)
    arbiter_reason: Mapped[str | None] = mapped_column(String, nullable=True)

    # Tier 2
    tier2_action: Mapped[str | None] = mapped_column(String, nullable=True)
    tier2_register: Mapped[str | None] = mapped_column(String, nullable=True)
    tier2_draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    tier2_needs_tools: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    tier2_channel_hint: Mapped[str | None] = mapped_column(String, nullable=True)
    tier2_reclassify: Mapped[str | None] = mapped_column(String, nullable=True)

    # Tier 3 (legacy thin-directive path — what actually shipped today)
    tier3_invoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tier3_outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    channel: Mapped[str | None] = mapped_column(String, nullable=True)

    # Counterfactual fat-contract Phase-1 logging — what the NEW path WOULD do
    # Mirror-mode only: these fields capture the new pipeline's decision
    # without acting on it.
    counterfactual_legacy_outbound_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    counterfactual_fat_contract_outcome: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    counterfactual_fat_contract_draft: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    counterfactual_fat_contract_skip_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    counterfactual_fat_contract_elapsed_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    counterfactual_fat_contract_error: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )

    __table_args__ = (
        Index("idx_pdt_user_event_at", "user_id", "event_at"),
        Index("idx_pdt_speech_act", "speech_act"),
        Index("idx_pdt_topic_key", "topic_key"),
    )
```

- [ ] **Step 4: Create migration `backend/db/migrations/versions/0023_proactive_dispatch_telemetry.py`**

```python
"""Proactive dispatch telemetry — Phase 1 counterfactual logging.

Revision ID: 0023_proactive_dispatch_telemetry
Revises: 0022_user_days_calendar
Create Date: 2026-05-04 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "0023_proactive_dispatch_telemetry"
down_revision = "0022_user_days_calendar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "proactive_dispatch_telemetry",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "event_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("speech_act", sa.String(), nullable=False),
        sa.Column("topic_key", sa.String(), nullable=False),
        sa.Column("tier1_score", sa.Float(), nullable=True),
        sa.Column("arbiter_decision", sa.String(), nullable=True),
        sa.Column("arbiter_reason", sa.String(), nullable=True),
        sa.Column("tier2_action", sa.String(), nullable=True),
        sa.Column("tier2_register", sa.String(), nullable=True),
        sa.Column("tier2_draft", sa.Text(), nullable=True),
        sa.Column("tier2_needs_tools", sa.Boolean(), nullable=True),
        sa.Column("tier2_channel_hint", sa.String(), nullable=True),
        sa.Column("tier2_reclassify", sa.String(), nullable=True),
        sa.Column(
            "tier3_invoked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("tier3_outcome", sa.String(), nullable=True),
        sa.Column("channel", sa.String(), nullable=True),
        sa.Column(
            "counterfactual_legacy_outbound_count", sa.Integer(), nullable=True
        ),
        sa.Column(
            "counterfactual_fat_contract_outcome", sa.String(), nullable=True
        ),
        sa.Column(
            "counterfactual_fat_contract_draft", sa.Text(), nullable=True
        ),
        sa.Column(
            "counterfactual_fat_contract_skip_reason", sa.Text(), nullable=True
        ),
        sa.Column(
            "counterfactual_fat_contract_elapsed_ms", sa.Integer(), nullable=True
        ),
        sa.Column(
            "counterfactual_fat_contract_error", sa.Text(), nullable=True
        ),
    )
    op.create_index(
        "idx_pdt_user_event_at",
        "proactive_dispatch_telemetry",
        ["user_id", "event_at"],
    )
    op.create_index(
        "idx_pdt_speech_act",
        "proactive_dispatch_telemetry",
        ["speech_act"],
    )
    op.create_index(
        "idx_pdt_topic_key",
        "proactive_dispatch_telemetry",
        ["topic_key"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_pdt_topic_key", table_name="proactive_dispatch_telemetry"
    )
    op.drop_index(
        "idx_pdt_speech_act", table_name="proactive_dispatch_telemetry"
    )
    op.drop_index(
        "idx_pdt_user_event_at", table_name="proactive_dispatch_telemetry"
    )
    op.drop_table("proactive_dispatch_telemetry")
```

- [ ] **Step 5: Apply migration in test environment**

```
DATABASE_URL=$TEST_DATABASE_URL alembic -c alembic.ini upgrade head
```
Expected: applies cleanly through 0023.

- [ ] **Step 6: Run the test**

```
pytest backend/tests/proactive/test_dispatch_telemetry.py -v
```
Expected: 1 passed.

- [ ] **Step 7: Verify downgrade is clean**

```
DATABASE_URL=$TEST_DATABASE_URL alembic -c alembic.ini downgrade -1
DATABASE_URL=$TEST_DATABASE_URL alembic -c alembic.ini upgrade head
```
Expected: round-trip clean.

- [ ] **Step 8: Commit**

```bash
git add db/models.py backend/db/migrations/versions/0023_proactive_dispatch_telemetry.py backend/tests/proactive/test_dispatch_telemetry.py
git commit -m "feat(proactive): proactive_dispatch_telemetry table for Phase-1 counterfactual logging

One row per dispatched event. Captures arbiter decision, Tier 2 verdict,
and Tier 3 outcome, plus counterfactual fields for the new fat-contract
path running in mirror mode alongside the legacy thin-directive ship.

Phase 1 of proactive brain redesign."
```

---

## Task 5: Conditional fresh_signal pre-fetcher

**Files:**
- Create: `proactive/fresh_signal.py`
- Test: `backend/tests/proactive/test_fresh_signal.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/proactive/test_fresh_signal.py`:

```python
"""Fresh-signal pre-fetcher — conditional re-fetch by speech_act + age."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from proactive.events import ProactiveEvent
from proactive.fresh_signal import should_prefetch, fetch_for_event


def _event(speech_act, age_minutes=120, source="email"):
    return ProactiveEvent(
        user_id="u1",
        source=source,
        source_ref="r",
        topic_key="t",
        speech_act=speech_act,
        signals={"event_age_minutes": age_minutes},
    )


def test_dont_forget_does_not_prefetch():
    assert not should_prefetch(_event("dont_forget"))


def test_thought_youd_want_does_not_prefetch():
    assert not should_prefetch(_event("thought_youd_want"))


def test_i_noticed_does_not_prefetch():
    assert not should_prefetch(_event("i_noticed"))


def test_heads_up_recent_event_does_not_prefetch():
    assert not should_prefetch(_event("heads_up", age_minutes=30))


def test_heads_up_stale_event_prefetches():
    assert should_prefetch(_event("heads_up", age_minutes=120))


def test_now_the_moment_stale_event_prefetches():
    assert should_prefetch(_event("now_the_moment", age_minutes=120))


@pytest.mark.asyncio
async def test_fetch_for_event_falls_back_for_unknown_source():
    """Sources without a fetcher return a benign error result, not a raise."""
    e = _event("heads_up", source="pattern")
    result = await fetch_for_event(e)
    assert result["status"] == "no_fetcher"
    assert "result" not in result or not result.get("result")
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest backend/tests/proactive/test_fresh_signal.py -v
```
Expected: ImportError on `proactive.fresh_signal`.

- [ ] **Step 3: Create `proactive/fresh_signal.py`**

```python
"""Conditional pre-fetch of fresh signal for Tier 3 input contract.

Only fetches when speech_act ∈ {heads_up, now_the_moment} AND the event
is older than ``_STALE_THRESHOLD_MINUTES``. Other speech acts don't gain
from re-fetching: dont_forget reminders are time-anchored, thought_youd_want
hits are already fresh by construction, i_noticed is state-based not
event-based.

Per-source fetchers live here. Each returns a dict with at least:
    { "status": "ok" | "no_fetcher" | "degraded",
      "result": <source-specific>,
      "delta_from_original": <human readable>,
      "fetched_at": ISO timestamp }
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from proactive.events import ProactiveEvent


logger = logging.getLogger(__name__)

_STALE_THRESHOLD_MINUTES = 60
_PREFETCH_ACTS = {"heads_up", "now_the_moment"}


def should_prefetch(event: ProactiveEvent) -> bool:
    """True iff fresh signal should be re-fetched at Tier 3 context build."""
    if event.speech_act not in _PREFETCH_ACTS:
        return False
    age_minutes = float(event.signals.get("event_age_minutes") or 0.0)
    return age_minutes >= _STALE_THRESHOLD_MINUTES


async def fetch_for_event(event: ProactiveEvent) -> dict[str, Any]:
    """Return a fresh-signal payload for the given event.

    Caller MUST check ``should_prefetch(event)`` first; this function
    runs the actual fetch. Per-source fetchers are dispatched off
    ``event.source``.
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        if event.source == "email":
            return await _fetch_email(event, fetched_at)
        if event.source == "calendar":
            return await _fetch_calendar(event, fetched_at)
        if event.source == "system_b_web":
            return await _fetch_system_b(event, fetched_at)
        if event.source == "attention_fire":
            return await _fetch_attention(event, fetched_at)
        return {"status": "no_fetcher", "fetched_at": fetched_at}
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.exception("fresh_signal: fetch raised source=%s", event.source)
        return {
            "status": "degraded",
            "fetched_at": fetched_at,
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
        }


# --- Per-source stubs -------------------------------------------------------
# Each returns a placeholder result for Phase 1. Real implementations land
# alongside the System B fold-in (Phase 2) and the Tier 2 / cutover work.


async def _fetch_email(event: ProactiveEvent, fetched_at: str) -> dict[str, Any]:
    # Real impl in Phase 2: re-fetch the gmail thread state.
    return {
        "status": "ok",
        "fetched_at": fetched_at,
        "result": {"note": "stub — gmail re-fetch not yet wired"},
        "delta_from_original": "stub",
    }


async def _fetch_calendar(event: ProactiveEvent, fetched_at: str) -> dict[str, Any]:
    return {
        "status": "ok",
        "fetched_at": fetched_at,
        "result": {"note": "stub — calendar re-fetch not yet wired"},
        "delta_from_original": "stub",
    }


async def _fetch_system_b(event: ProactiveEvent, fetched_at: str) -> dict[str, Any]:
    return {
        "status": "ok",
        "fetched_at": fetched_at,
        "result": {"note": "stub — Exa re-search not yet wired"},
        "delta_from_original": "stub",
    }


async def _fetch_attention(event: ProactiveEvent, fetched_at: str) -> dict[str, Any]:
    return {
        "status": "ok",
        "fetched_at": fetched_at,
        "result": {"note": "stub — attention dry_run re-execution not yet wired"},
        "delta_from_original": "stub",
    }
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest backend/tests/proactive/test_fresh_signal.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add proactive/fresh_signal.py backend/tests/proactive/test_fresh_signal.py
git commit -m "feat(proactive): conditional fresh_signal pre-fetcher (stub fetchers)

Pre-fetches only when speech_act ∈ {heads_up, now_the_moment} AND event
age >= 60 min. Per-source dispatch with stub fetchers — real
implementations land in Phase 2 alongside System B fold-in.

Phase 1 of proactive brain redesign."
```

---

## Task 6: Tier 3 terminator tools — skip, kill_attention, reshape_attention

**Files:**
- Create: `donna_runtime/tools_tier3.py`
- Test: `backend/tests/runtime/test_tools_tier3.py`

- [ ] **Step 1: Write the failing test (terminators portion)**

Create `backend/tests/runtime/test_tools_tier3.py`:

```python
"""Tier 3 tool palette — terminators (skip, kill_attention, reshape_attention)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from donna_runtime.tools_tier3 import (
    skip,
    kill_attention,
    reshape_attention,
)


@pytest.mark.asyncio
async def test_skip_returns_outcome_with_reason():
    out = await skip(reason="moment is dead")
    assert out["action"] == "skip"
    assert out["reason"] == "moment is dead"


@pytest.mark.asyncio
async def test_skip_rejects_empty_reason():
    with pytest.raises(ValueError, match="reason"):
        await skip(reason="")


@pytest.mark.asyncio
async def test_kill_attention_returns_outcome():
    out = await kill_attention(
        attention_id="att_1",
        reason="user already did the thing",
    )
    assert out["action"] == "kill"
    assert out["attention_id"] == "att_1"
    assert out["reason"] == "user already did the thing"


@pytest.mark.asyncio
async def test_kill_attention_requires_reason():
    with pytest.raises(ValueError, match="reason"):
        await kill_attention(attention_id="att_1", reason="")


@pytest.mark.asyncio
async def test_reshape_attention_with_next_fire_at():
    fire_at = datetime(2026, 5, 5, 9, 0, tzinfo=timezone.utc)
    out = await reshape_attention(
        attention_id="att_1",
        next_fire_at=fire_at,
    )
    assert out["action"] == "reshape"
    assert out["attention_id"] == "att_1"
    assert out["reshape_kwargs"]["next_fire_at"] == fire_at.isoformat()


@pytest.mark.asyncio
async def test_reshape_attention_requires_at_least_one_change():
    with pytest.raises(ValueError, match="at least one"):
        await reshape_attention(attention_id="att_1")
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest backend/tests/runtime/test_tools_tier3.py -v
```
Expected: ImportError on `donna_runtime.tools_tier3`.

- [ ] **Step 3: Create `donna_runtime/tools_tier3.py` (terminators only — extend in next tasks)**

```python
"""Tier 3 tool palette — fat-contract editorial brain.

Six tools, narrowly scoped:
    Reads:  quick_check, read_external
    Writes: send_burst, reshape_attention, kill_attention, skip

Every Tier 3 turn must call exactly one of {send_burst, skip,
reshape_attention, kill_attention} as the terminator. The harness
forces skip(reason="max_turns_exceeded") if turn 3 doesn't terminate.

Phase 1 implementation: tool bodies return outcome dicts that the
dispatcher routes downstream. Side effects (DB writes, WhatsApp sends,
schedule cancels) live in the dispatcher's outcome handler — keeps
tools pure and testable.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal


# ---- terminators -----------------------------------------------------------


async def skip(reason: str) -> dict[str, Any]:
    """Explicit silence. First-class outcome.

    USE WHEN: fresh signal shows the moment is dead, the topic is
              already covered, or your editorial read is that this fire
              would degrade trust.
    DO NOT USE: when you'd rather hold (use send_burst with push=False).
    """
    if not reason or not reason.strip():
        raise ValueError("skip requires a reason (one short sentence)")
    return {"action": "skip", "reason": reason.strip()}


async def kill_attention(*, attention_id: str, reason: str) -> dict[str, Any]:
    """Terminate a live attention. Sets status=killed, cancels future
    schedule rows. Permanent.

    USE WHEN: fresh signal shows the user already did the thing, the
              moment is permanently gone, or the spec was wrong from
              the start.
    DO NOT USE: for transient stale (use reshape_attention with
                next_fire_at instead).
    """
    if not attention_id:
        raise ValueError("attention_id is required")
    if not reason or not reason.strip():
        raise ValueError("reason is required (one short sentence)")
    return {
        "action": "kill",
        "attention_id": attention_id,
        "reason": reason.strip(),
    }


async def reshape_attention(
    *,
    attention_id: str,
    next_fire_at: datetime | None = None,
    surface_level: Literal["DEFAULT", "DIGEST", "URGENT"] | None = None,
    cadence_change: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Modify the live attention spec without firing.

    USE WHEN: world changed but the spec is still useful (push to
              tomorrow, downgrade urgency, fold cadence).
    DO NOT USE: when the right action is to fire now (use send_burst), or
                when the spec is permanently moot (use kill_attention).
    """
    if not attention_id:
        raise ValueError("attention_id is required")
    if next_fire_at is None and surface_level is None and not cadence_change:
        raise ValueError(
            "reshape_attention needs at least one change: next_fire_at, "
            "surface_level, or cadence_change"
        )
    reshape_kwargs: dict[str, Any] = {}
    if next_fire_at is not None:
        reshape_kwargs["next_fire_at"] = next_fire_at.isoformat()
    if surface_level is not None:
        reshape_kwargs["surface_level"] = surface_level
    if cadence_change:
        reshape_kwargs["cadence_change"] = cadence_change
    return {
        "action": "reshape",
        "attention_id": attention_id,
        "reshape_kwargs": reshape_kwargs,
    }
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest backend/tests/runtime/test_tools_tier3.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add donna_runtime/tools_tier3.py backend/tests/runtime/test_tools_tier3.py
git commit -m "feat(tools): Tier 3 terminator tools — skip, kill_attention, reshape_attention

Three of the four required terminators for the fat-contract Tier 3 brain.
Tools return outcome dicts; dispatcher's outcome handler does the side
effects (DB writes, schedule cancels). Pure + testable.

Phase 1 of proactive brain redesign."
```

---

## Task 7: Tier 3 send_burst tool — 4-quadrant push/surface_at matrix

**Files:**
- Modify: `donna_runtime/tools_tier3.py`
- Modify: `backend/tests/runtime/test_tools_tier3.py`

- [ ] **Step 1: Write the failing test (append send_burst cases)**

Append to `backend/tests/runtime/test_tools_tier3.py`:

```python
from donna_runtime.tools_tier3 import send_burst


@pytest.mark.asyncio
async def test_send_burst_push_default_quadrant():
    out = await send_burst(messages=[{"type": "text", "body": "hi"}])
    assert out["action"] == "ship"
    assert out["push"] is True
    assert out["surface_at"] is None


@pytest.mark.asyncio
async def test_send_burst_ambient_quadrant():
    out = await send_burst(
        messages=[{"type": "text", "body": "fyi"}],
        push=False,
    )
    assert out["action"] == "ship"
    assert out["push"] is False
    assert out["surface_at"] is None


@pytest.mark.asyncio
async def test_send_burst_hold_for_next_touch():
    out = await send_burst(
        messages=[{"type": "text", "body": "later"}],
        push=False,
        surface_at="next_user_touch",
    )
    assert out["surface_at"] == "next_user_touch"


@pytest.mark.asyncio
async def test_send_burst_morning_brief():
    out = await send_burst(
        messages=[{"type": "text", "body": "tomorrow"}],
        push=False,
        surface_at="morning_brief",
    )
    assert out["surface_at"] == "morning_brief"


@pytest.mark.asyncio
async def test_send_burst_rejects_push_with_surface_at():
    with pytest.raises(ValueError, match="surface_at requires push=False"):
        await send_burst(
            messages=[{"type": "text", "body": "x"}],
            push=True,
            surface_at="morning_brief",
        )


@pytest.mark.asyncio
async def test_send_burst_requires_messages():
    with pytest.raises(ValueError, match="messages"):
        await send_burst(messages=[])
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest backend/tests/runtime/test_tools_tier3.py::test_send_burst_push_default_quadrant -v
```
Expected: ImportError on `send_burst`.

- [ ] **Step 3: Append `send_burst` to `donna_runtime/tools_tier3.py`**

```python
async def send_burst(
    *,
    messages: list[dict[str, Any]],
    push: bool = True,
    surface_at: Literal["next_user_touch", "morning_brief"] | None = None,
) -> dict[str, Any]:
    """Ship the proactive message. Channel is inline.

    Quadrants:
      push=True,  surface_at=None         -> WhatsApp ping + chat_messages
      push=False, surface_at=None         -> ambient (chat_messages only)
      push=False, surface_at="next_user_touch" -> pending_proactive_notes,
                                                 surfaces in next reactive turn
      push=False, surface_at="morning_brief"   -> pending note tagged for
                                                  tomorrow's morning brief

    USE: to actually ship (or hold).
    DO NOT USE: when fresh signal shows the moment is dead — use skip.

    NOTE: surface_at is meaningful only with push=False. push=True with
    surface_at set raises — pushing means the user gets it now, holding
    is a contradiction.
    """
    if not messages:
        raise ValueError("send_burst requires at least one message")
    if push and surface_at is not None:
        raise ValueError(
            "surface_at requires push=False (you can't push and hold at "
            "the same time)"
        )
    return {
        "action": "ship",
        "messages": messages,
        "push": push,
        "surface_at": surface_at,
    }
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest backend/tests/runtime/test_tools_tier3.py -v
```
Expected: 12 passed (6 from Task 6 + 6 new).

- [ ] **Step 5: Commit**

```bash
git add donna_runtime/tools_tier3.py backend/tests/runtime/test_tools_tier3.py
git commit -m "feat(tools): Tier 3 send_burst with push + surface_at quadrant matrix

Four meaningful combos:
  push=True              -> WhatsApp ping
  push=False             -> ambient on dashboard
  push=False, surface_at -> pending_proactive_note (next touch / morning)
push=True with surface_at is rejected (contradicts itself).

Phase 1 of proactive brain redesign."
```

---

## Task 8: Tier 3 read tools — quick_check + read_external

**Files:**
- Modify: `donna_runtime/tools_tier3.py`
- Modify: `backend/tests/runtime/test_tools_tier3.py`

- [ ] **Step 1: Write the failing test (append read tools cases)**

Append to `backend/tests/runtime/test_tools_tier3.py`:

```python
from donna_runtime.tools_tier3 import quick_check, read_external


@pytest.mark.asyncio
async def test_quick_check_requires_question():
    with pytest.raises(ValueError, match="question"):
        await quick_check(question="")


@pytest.mark.asyncio
async def test_quick_check_returns_results_shape(monkeypatch):
    """Stub the underlying exa search call."""
    async def _fake_search(*, query, num_results, **_kwargs):
        return [
            {"title": "A", "url": "https://a", "excerpt": "ex"},
            {"title": "B", "url": "https://b", "excerpt": "ex"},
        ]
    monkeypatch.setattr(
        "donna_runtime.tools_tier3._exa_search_for_quick_check",
        _fake_search,
    )

    out = await quick_check(question="is anthropic shipping today?")
    assert out["status"] == "ok"
    assert len(out["results"]) == 2
    assert out["results"][0]["url"] == "https://a"


@pytest.mark.asyncio
async def test_quick_check_caps_max_results():
    """max_results is hard-capped at 5 to prevent abuse."""
    with pytest.raises(ValueError, match="max_results"):
        await quick_check(question="x", max_results=99)


@pytest.mark.asyncio
async def test_read_external_unknown_source_raises():
    with pytest.raises(ValueError, match="source"):
        await read_external(source="bogus", ref="x")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_read_external_gmail_thread_returns_stub():
    out = await read_external(source="gmail_thread", ref="thread_xyz")
    assert out["status"] in {"ok", "degraded", "no_fetcher"}
    assert out["source"] == "gmail_thread"
    assert out["ref"] == "thread_xyz"
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest backend/tests/runtime/test_tools_tier3.py -v
```
Expected: ImportError on `quick_check` / `read_external`.

- [ ] **Step 3: Append read tools to `donna_runtime/tools_tier3.py`**

```python
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_QUICK_CHECK_MAX_RESULTS = 5


async def _exa_search_for_quick_check(
    *, query: str, num_results: int
) -> list[dict[str, Any]]:
    """Indirection for monkeypatching in tests + isolating the Exa client.

    Real implementation lazy-imports the Exa client; this stays importable
    without an Exa key for most callsites.
    """
    try:
        from backend.web.client import exa_search, have_exa_key
    except Exception:
        logger.exception("quick_check: exa client import failed")
        return []
    if not have_exa_key():
        logger.warning("quick_check: no EXA_API_KEY — returning empty")
        return []
    try:
        raw = await exa_search(query=query, num_results=num_results)
    except Exception:
        logger.exception("quick_check: exa_search raised")
        return []
    return [
        {
            "title": (item.get("title") or "")[:200],
            "url": item.get("url") or "",
            "excerpt": (item.get("text") or item.get("excerpt") or "")[:400],
        }
        for item in (raw or [])
    ]


async def quick_check(
    *,
    question: str,
    max_results: int = 3,
) -> dict[str, Any]:
    """One-shot web search to verify a specific claim or fetch a focused fact.

    USE WHEN: the event makes a factual claim that needs verification, OR
              thought_youd_want needs a freshness check.
    DO NOT USE: for general research or exploration. This is verification,
                not curiosity.
    HARD LIMIT: one call per turn. The harness rejects a second call.
    """
    if not question or not question.strip():
        raise ValueError("question is required")
    if max_results <= 0 or max_results > _QUICK_CHECK_MAX_RESULTS:
        raise ValueError(
            f"max_results must be 1..{_QUICK_CHECK_MAX_RESULTS}; got {max_results}"
        )
    results = await _exa_search_for_quick_check(
        query=question.strip(), num_results=max_results
    )
    return {
        "status": "ok" if results else "no_results",
        "question": question.strip(),
        "results": results,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


_READ_EXTERNAL_SOURCES = {
    "gmail_thread",
    "calendar_event",
    "exa_url",
    "person_recent_chat",
}


async def read_external(
    *,
    source: Literal[
        "gmail_thread", "calendar_event", "exa_url", "person_recent_chat"
    ],
    ref: str,
) -> dict[str, Any]:
    """Fresh state of one specific external resource by identifier.

    USE WHEN: need fresh state of something specifically referenced by id,
              and that exact resource isn't in the pre-fetched fresh_signal
              block.
    DO NOT USE: when pre-fetched fresh_signal already has what you need.
    """
    if source not in _READ_EXTERNAL_SOURCES:
        raise ValueError(
            f"source must be one of {_READ_EXTERNAL_SOURCES}; got {source!r}"
        )
    if not ref:
        raise ValueError("ref is required")
    # Phase 1: stub. Real per-source fetchers land alongside Phase 2.
    return {
        "status": "no_fetcher",
        "source": source,
        "ref": ref,
        "note": (
            "Phase 1 stub. Real fetcher lands with the System B fold-in."
        ),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest backend/tests/runtime/test_tools_tier3.py -v
```
Expected: 17 passed (12 prior + 5 new).

- [ ] **Step 5: Commit**

```bash
git add donna_runtime/tools_tier3.py backend/tests/runtime/test_tools_tier3.py
git commit -m "feat(tools): Tier 3 read tools — quick_check + read_external (stubs)

quick_check: one-shot Exa search, hard-capped max_results=5, monkeypatch
  hook in tests via _exa_search_for_quick_check.
read_external: stub for Phase 1 — returns 'no_fetcher' with the source/ref
  echoed. Real fetchers land with the System B fold-in (Phase 2).

Phase 1 of proactive brain redesign."
```

---

## Task 9: Tier 3 context builder — eleven blocks

**Files:**
- Create: `donna_runtime/context_builder_tier3.py`
- Test: `backend/tests/runtime/test_context_builder_tier3.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/runtime/test_context_builder_tier3.py`:

```python
"""Tier 3 fat-contract context builder — 11 blocks rendered into one prompt."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from proactive.events import ProactiveEvent
from proactive.judge import JudgeResult
from donna_runtime.context_builder_tier3 import build_tier3_user_message


def _judge() -> JudgeResult:
    return JudgeResult(
        action="ping",
        register="alert",
        draft="luca replied to the term sheet",
        tie_in=("luca",),
        needs_tools=True,
        reasoning="thread state may have moved",
        raw_response="{}",
    )


def _event() -> ProactiveEvent:
    return ProactiveEvent(
        user_id="u1",
        source="email",
        source_ref="msg_abc",
        topic_key="thread_xyz",
        speech_act="heads_up",
        payload={
            "from_address": "luca@x.com",
            "subject": "term sheet v2",
            "body_excerpt": "see attached",
        },
        signals={"score": 0.8, "event_age_minutes": 30},
    )


def test_build_tier3_user_message_includes_all_block_headers():
    msg = build_tier3_user_message(
        event=_event(),
        judge=_judge(),
        escalation_reason="needs_tools",
        user_model_block="USER MODEL: arnav, building donna",
        day_view_block="DAY VIEW: nothing yet today",
        prior_touches_block="PRIOR TOUCHES: none",
        user_state_block="USER STATE: focused, in engage window",
        pending_notes_block="PENDING NOTES: none",
        queued_thing_block="QUEUED THING: <attention spec>",
        fresh_signal_block=None,
    )
    for header in (
        "WHY YOU'RE AWAKE",
        "USER MODEL",
        "THE QUEUED THING",
        "THE EVENT PAYLOAD",
        "TIER 2",
        "DAY VIEW",
        "PRIOR TOUCHES",
        "USER STATE NOW",
        "PENDING NOTES",
    ):
        assert header in msg, f"missing block header: {header}"


def test_build_tier3_user_message_excludes_fresh_signal_when_none():
    msg = build_tier3_user_message(
        event=_event(),
        judge=_judge(),
        escalation_reason="needs_tools",
        user_model_block="x",
        day_view_block="x",
        prior_touches_block="x",
        user_state_block="x",
        pending_notes_block="x",
        queued_thing_block="x",
        fresh_signal_block=None,
    )
    assert "FRESH SIGNAL" not in msg


def test_build_tier3_user_message_includes_fresh_signal_when_present():
    msg = build_tier3_user_message(
        event=_event(),
        judge=_judge(),
        escalation_reason="needs_tools",
        user_model_block="x",
        day_view_block="x",
        prior_touches_block="x",
        user_state_block="x",
        pending_notes_block="x",
        queued_thing_block="x",
        fresh_signal_block="FRESH SIGNAL: thread has 2 new replies since trigger",
    )
    assert "FRESH SIGNAL" in msg
    assert "2 new replies" in msg


def test_build_tier3_user_message_renders_speech_act_and_reason():
    msg = build_tier3_user_message(
        event=_event(),
        judge=_judge(),
        escalation_reason="stakes_aware",
        user_model_block="x",
        day_view_block="x",
        prior_touches_block="x",
        user_state_block="x",
        pending_notes_block="x",
        queued_thing_block="x",
        fresh_signal_block=None,
    )
    assert "speech_act: heads_up" in msg
    assert "escalation_reason: stakes_aware" in msg
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest backend/tests/runtime/test_context_builder_tier3.py -v
```
Expected: ImportError.

- [ ] **Step 3: Create `donna_runtime/context_builder_tier3.py`**

```python
"""Tier 3 fat-contract context builder.

Renders the 11 blocks from the spec into one user-message string. The
LLM call lives elsewhere (donna_runtime/brain.py); this module is pure
formatting + composition over already-fetched data.

The block contents are computed by the dispatcher's pre-build step and
passed in as strings, so this module stays free of DB / network deps
and is trivially testable.
"""
from __future__ import annotations

from typing import Literal

from proactive.events import ProactiveEvent
from proactive.judge import JudgeResult


EscalationReason = Literal[
    "needs_tools",
    "empty_draft",
    "validator_fail",
    "stakes_aware",
    "hold_ambiguity",
    "tier2_failed",
]


def build_tier3_user_message(
    *,
    event: ProactiveEvent,
    judge: JudgeResult,
    escalation_reason: EscalationReason,
    user_model_block: str,
    queued_thing_block: str,
    day_view_block: str,
    prior_touches_block: str,
    user_state_block: str,
    pending_notes_block: str,
    fresh_signal_block: str | None,
) -> str:
    """Compose the Tier 3 USER message from pre-built blocks.

    Block 1 (why you're awake) and block 4 (event payload) are rendered
    inline from the event + escalation_reason. Block 5 (Tier 2 output)
    is rendered from JudgeResult. The rest come in as strings.
    """
    parts: list[str] = []

    # Block 1 — WHY YOU'RE AWAKE
    parts.append(
        f"# WHY YOU'RE AWAKE\n"
        f"escalation_reason: {escalation_reason}\n"
        f"speech_act: {event.speech_act}\n"
        f"source: {event.source}"
    )

    # Block 2 — USER MODEL (precomputed)
    parts.append(f"# USER MODEL\n{user_model_block.strip()}")

    # Block 3 — THE QUEUED THING (precomputed spec render)
    parts.append(f"# THE QUEUED THING\n{queued_thing_block.strip()}")

    # Block 4 — THE EVENT PAYLOAD (rendered from event)
    payload_lines = [f"source_ref: {event.source_ref}", f"topic_key: {event.topic_key}"]
    for k, v in (event.payload or {}).items():
        rendered = str(v)
        if len(rendered) > 600:
            rendered = rendered[:600] + " …"
        payload_lines.append(f"{k}: {rendered}")
    if event.signals:
        payload_lines.append("signals:")
        for k, v in event.signals.items():
            payload_lines.append(f"  {k}: {v}")
    parts.append("# THE EVENT PAYLOAD\n" + "\n".join(payload_lines))

    # Block 5 — TIER 2 (the hint, not the constraint)
    tier2_lines = [
        f"action: {judge.action}",
        f"register: {judge.register or 'n/a'}",
        f"draft: {judge.draft or '(none)'}",
        f"tie_in: {list(judge.tie_in) if judge.tie_in else '[]'}",
        f"needs_tools: {judge.needs_tools}",
        f"reasoning: {judge.reasoning or '(none)'}",
    ]
    if judge.channel_hint:
        tier2_lines.append(f"channel_hint: {judge.channel_hint}")
    if judge.reclassify_speech_act:
        tier2_lines.append(f"reclassify_speech_act: {judge.reclassify_speech_act}")
    parts.append("# TIER 2\n" + "\n".join(tier2_lines))

    # Block 6 — DAY VIEW (precomputed)
    parts.append(f"# DAY VIEW\n{day_view_block.strip()}")

    # Block 7 — PRIOR TOUCHES (precomputed)
    parts.append(f"# PRIOR TOUCHES\n{prior_touches_block.strip()}")

    # Block 8 — USER STATE NOW (precomputed)
    parts.append(f"# USER STATE NOW\n{user_state_block.strip()}")

    # Block 9 — PENDING NOTES (precomputed)
    parts.append(f"# PENDING NOTES\n{pending_notes_block.strip()}")

    # Block 10 — FRESH SIGNAL (conditional)
    if fresh_signal_block and fresh_signal_block.strip():
        parts.append(f"# FRESH SIGNAL\n{fresh_signal_block.strip()}")

    # Block 11 — TOOLS lives in the system prompt (not user msg).

    return "\n\n".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest backend/tests/runtime/test_context_builder_tier3.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add donna_runtime/context_builder_tier3.py backend/tests/runtime/test_context_builder_tier3.py
git commit -m "feat(runtime): Tier 3 fat-contract context builder

Renders the 11 blocks from the spec into one user-message string.
Pure formatting — block contents (USER MODEL, DAY view, prior touches,
user state, pending notes, queued thing, fresh signal) come in as
pre-built strings from the dispatcher, keeping this module free of
DB / network deps and trivially testable.

Phase 1 of proactive brain redesign."
```

---

## Task 10: Tier 3 system prompt + mode wiring

**Files:**
- Create: `donna_runtime/prompt_tier3.py`
- Modify: `donna_runtime/config.py` (extend `mode` literal + add `tier3_max_turns`)
- Modify: `donna_runtime/brain.py` (route `mode="proactive_tier3"` to Tier 3 system prompt + Tier 3 tools)
- Test: `backend/tests/runtime/test_prompt_tier3.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/runtime/test_prompt_tier3.py`:

```python
"""Tier 3 system prompt + DonnaAgentConfig mode wiring."""
from __future__ import annotations

import pytest

from donna_runtime.config import DonnaAgentConfig
from donna_runtime.prompt_tier3 import TIER3_SYSTEM_PROMPT


def test_tier3_system_prompt_states_editorial_default():
    p = TIER3_SYSTEM_PROMPT.lower()
    assert "editorial" in p
    assert "skip" in p
    assert "default" in p


def test_tier3_system_prompt_lists_terminators():
    p = TIER3_SYSTEM_PROMPT
    for tool in ("send_burst", "skip", "reshape_attention", "kill_attention"):
        assert tool in p


def test_tier3_system_prompt_warns_against_em_dashes():
    """Donna voice charter is preserved even in editorial mode."""
    p = TIER3_SYSTEM_PROMPT.lower()
    assert "em dash" in p or "em-dash" in p


def test_donna_agent_config_accepts_tier3_mode():
    cfg = DonnaAgentConfig(mode="proactive_tier3", tier3_max_turns=3)
    assert cfg.mode == "proactive_tier3"
    assert cfg.tier3_max_turns == 3


def test_donna_agent_config_default_tier3_max_turns_is_3():
    cfg = DonnaAgentConfig(mode="proactive_tier3")
    assert cfg.tier3_max_turns == 3
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest backend/tests/runtime/test_prompt_tier3.py -v
```
Expected: ImportError on `prompt_tier3` and config field.

- [ ] **Step 3: Create `donna_runtime/prompt_tier3.py`**

```python
"""Tier 3 system prompt — fat-contract editorial mode.

Distinct from reactive's mode="reactive" and from today's
mode="proactive". Tier 3 is invoked when Tier 2 escalates. The model
walks in knowing the queue + Tier 2 already decided this is worth
considering — its job is execute amazingly or skip cleanly.
"""
from __future__ import annotations


TIER3_SYSTEM_PROMPT = """You are donna in editorial mode.

the queue and tier 2 already decided that something is worth your
attention. your job is to execute it amazingly — or to recognize that
the moment is dead and skip cleanly.

you are NOT deciding from scratch whether to ping. the arbiter and
tier 2 have done that work. your job is to take what they handed you
and ship the BEST POSSIBLE version of this fire — or, if fresh signal
shows the moment moved, to reshape, kill, or hold.

default action: ship tier 2's draft (after one editorial pass).
skip is a first-class outcome — not a failure. silence is correct
when fresh signal shows the user already addressed this, the moment
has passed, or your tools reveal redundancy with a recent fire.

you have 3 turns. default = use the context. it has DAY view, prior
touches, fresh signal, and tier 2's read. most fires don't need fetches.

the speech act for this fire is in the user message under "WHY YOU'RE
AWAKE". apply its register:
  dont_forget       — brisk, direct, present-tense, <8 words ideal
  heads_up          — factual, lead with what changed
  i_noticed         — soft, question form, no diagnosis
  now_the_moment    — short, tied to the original intent, echo her language
  thought_youd_want — enthusiast not breathless, one-line gist + url

WHEN TO USE EACH TOOL
  send_burst         — to ship (specify push + surface_at)
  skip               — to end without sending
  reshape_attention  — when fresh signal shows spec is wrong but useful
  kill_attention     — when fresh signal shows spec is moot
  quick_check        — verify a factual claim, max 1 call per turn
  read_external      — fresh state of a specific external resource

DO NOT
- call quick_check or read_external when context is sufficient
- re-judge whether to fire from scratch (that's tier 2's job)
- draft from scratch when tier 2's draft is usable (polish, don't replace)
- use em dashes, semicolons, capital letters, or emojis
- end a turn without calling exactly one of:
  {send_burst, skip, reshape_attention, kill_attention}

donna voice: lowercase. no em dashes. no semicolons. blunt. high-agency.
no filler. never "i understand" or "great question." when she does not
know, say so.
"""
```

- [ ] **Step 4: Modify `donna_runtime/config.py`**

Search for the `class DonnaAgentConfig:` definition. Update the `mode` literal and add `tier3_max_turns`:

```python
@dataclass
class DonnaAgentConfig:
    max_turns: int = 6
    proactive_max_turns: int = 12
    tier3_max_turns: int = 3                                         # NEW
    # ... existing fields ...
    mode: Literal["reactive", "proactive", "proactive_tier3"] = (    # MODIFIED
        "reactive"
    )
```

Place `tier3_max_turns: int = 3` right under `proactive_max_turns: int = 12` so related fields cluster.

- [ ] **Step 5: Modify `donna_runtime/brain.py`**

Find where the system prompt + tool registration is selected by `cfg.mode`. Today's branch handles `"reactive"` and `"proactive"`. Add a parallel branch for `"proactive_tier3"`:

```python
# Pseudocode location — search brain.py for `cfg.mode` and where it picks
# system_prompt / tools. The branch should look like:

if cfg.mode == "proactive_tier3":
    from donna_runtime.prompt_tier3 import TIER3_SYSTEM_PROMPT
    from donna_runtime.tools_tier3 import (
        quick_check,
        read_external,
        reshape_attention,
        kill_attention,
        send_burst,
        skip,
    )
    system_prompt = TIER3_SYSTEM_PROMPT
    tools = [
        quick_check,
        read_external,
        reshape_attention,
        kill_attention,
        send_burst,
        skip,
    ]
    max_turns = cfg.tier3_max_turns
elif cfg.mode == "proactive":
    # existing proactive branch unchanged
    ...
else:
    # existing reactive branch unchanged
    ...
```

If `brain.py`'s actual structure differs (e.g. tools registered via a registry rather than passed inline), follow the existing pattern but gate on `mode="proactive_tier3"`. Do NOT modify the reactive or legacy proactive branches.

- [ ] **Step 6: Run the test**

```
pytest backend/tests/runtime/test_prompt_tier3.py -v
```
Expected: 5 passed.

- [ ] **Step 7: Smoke-import brain to catch syntax errors**

```
python -c "from donna_runtime.brain import donna_turn; print('ok')"
```
Expected: `ok`.

- [ ] **Step 8: Commit**

```bash
git add donna_runtime/prompt_tier3.py donna_runtime/config.py donna_runtime/brain.py backend/tests/runtime/test_prompt_tier3.py
git commit -m "feat(runtime): Tier 3 mode — system prompt + brain wiring

Adds mode='proactive_tier3' to DonnaAgentConfig, with
tier3_max_turns=3. Wires brain.py to use TIER3_SYSTEM_PROMPT and the
Tier 3 tool palette when this mode is active. Reactive and legacy
proactive paths unchanged.

Phase 1 of proactive brain redesign."
```

---

## Task 11: Wire fat-contract Tier 3 counterfactual into dispatcher (mirror-only)

**Files:**
- Modify: `proactive/dispatcher.py`
- Test: `backend/tests/proactive/test_dispatcher_tier3_mirror.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/proactive/test_dispatcher_tier3_mirror.py`:

```python
"""Dispatcher counterfactual logging — mirror-mode Phase 1.

Today's _escalate_to_brain ships via legacy donna_turn(mode="proactive")
and the THIN directive. This test asserts that the new fat-contract
counterfactual ALSO runs (in mirror mode), logs to
proactive_dispatch_telemetry, but does NOT change what's shipped to the
user.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import select

from db.models import ProactiveDispatchTelemetry
from proactive.dispatcher import _escalate_to_brain
from proactive.events import ProactiveEvent
from proactive.judge import JudgeResult


def _event() -> ProactiveEvent:
    return ProactiveEvent(
        user_id="user_test",
        source="email",
        source_ref="msg_x",
        topic_key="thread_x",
        speech_act="heads_up",
        payload={"from_address": "x@y.com", "subject": "hi", "body_excerpt": "..."},
        signals={"score": 0.7, "event_age_minutes": 30},
    )


def _judge() -> JudgeResult:
    return JudgeResult(
        action="ping",
        register="alert",
        draft="x replied",
        tie_in=(),
        needs_tools=True,
        reasoning="thread state may have moved",
        raw_response="{}",
    )


@pytest.mark.asyncio
async def test_counterfactual_runs_alongside_legacy_in_mirror_mode(
    db, monkeypatch
):
    """Both legacy donna_turn AND the fat-contract Tier 3 counterfactual
    should run. Legacy result is what the worker sees; counterfactual is
    logged."""
    legacy_calls = []
    fat_contract_calls = []

    async def fake_legacy(state, cfg):
        legacy_calls.append(cfg.mode)
        return {"_outbound": [{"type": "text", "body": "legacy draft"}]}

    async def fake_fat_contract(state, cfg):
        fat_contract_calls.append(cfg.mode)
        return {"_outbound": [], "_tier3_outcome": {"action": "skip", "reason": "stub"}}

    # Patch donna_turn so the dispatcher routes deterministically
    with patch("proactive.dispatcher.donna_turn", side_effect=[
        await_value(fake_legacy),  # placeholder
        await_value(fake_fat_contract),
    ]):
        outcome = await _escalate_to_brain(
            event=_event(),
            judge=_judge(),
            escalation_reason="needs_tools",
        )

    # Legacy must have been invoked (mode=proactive)
    assert "proactive" in legacy_calls
    # Counterfactual must have been invoked (mode=proactive_tier3)
    assert "proactive_tier3" in fat_contract_calls

    # Telemetry row was written
    async with db() as session:
        rows = (
            await session.execute(
                select(ProactiveDispatchTelemetry).where(
                    ProactiveDispatchTelemetry.topic_key == "thread_x"
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.tier3_invoked is True
        assert row.counterfactual_fat_contract_outcome == "skip"
```

> **Note:** The exact patching shape depends on `dispatcher.donna_turn` import path. The test author may adjust the `patch` target to match the actual import in `proactive/dispatcher.py`. The contract being tested is: legacy + counterfactual both run, telemetry row gets written.

- [ ] **Step 2: Run test to verify it fails**

```
pytest backend/tests/proactive/test_dispatcher_tier3_mirror.py -v
```
Expected: failure — counterfactual not yet wired.

- [ ] **Step 3: Modify `proactive/dispatcher.py`**

Find the existing `async def _escalate_to_brain(event, judge)` (~line 361). The function today builds the legacy thin prompt + calls `donna_turn(state, cfg)` with `mode="proactive"`. We are NOT removing that call — we add a counterfactual run alongside.

Replace the body of `_escalate_to_brain` to:

```python
async def _escalate_to_brain(
    event: ProactiveEvent,
    judge: JudgeResult | None,
    escalation_reason: str = "tier2_escalation",
) -> DispatchOutcome:
    """Fall through to the existing donna_turn proactive flow + run the
    fat-contract Tier 3 counterfactual alongside (mirror-only Phase 1).

    Legacy thin-directive ship still happens — that's what the worker
    delivers to the user. The fat-contract counterfactual runs separately,
    its outcome is logged to proactive_dispatch_telemetry, and is never
    shipped.
    """
    import time

    try:
        from donna_runtime.brain import donna_turn
        from donna_runtime.config import DonnaAgentConfig
    except Exception:
        logger.exception(
            "dispatcher: brain imports failed user=%s", event.user_id
        )
        return DispatchOutcome(
            action="errored",
            reason="brain_import_failed",
            judge=judge,
        )

    phone = event.payload.get("phone") if isinstance(event.payload, dict) else None
    if not phone:
        phone = await _user_phone(event.user_id)

    # ─── LEGACY PATH (unchanged behavior — what the worker sees) ───────────
    legacy_cfg = DonnaAgentConfig(
        mode="proactive",
        user_id=event.user_id,
        user_phone=phone,
        stateless_sessions=True,
    )
    legacy_prompt = _build_escalation_prompt(event, judge)
    legacy_state: dict[str, Any] = {
        "user_id": event.user_id,
        "raw_input": legacy_prompt,
        "user_message": legacy_prompt,
        "phone": phone,
        "trigger": {
            "source": event.source,
            "message_ref": event.source_ref,
            "topic_key": event.topic_key,
            "score": event.signals.get("score"),
            "signals": event.signals.get("signals"),
        },
    }
    if judge is not None:
        legacy_state["_tier2_proposal"] = {
            "action": judge.action,
            "register": judge.register,
            "draft": judge.draft,
            "tie_in": list(judge.tie_in),
            "reasoning": judge.reasoning,
            "needs_tools": judge.needs_tools,
            "failed": getattr(judge, "failed", False),
            "failure_reason": getattr(judge, "failure_reason", None),
        }
    legacy_result: dict | None = None
    legacy_error: str | None = None
    try:
        legacy_result = await donna_turn(legacy_state, legacy_cfg)
    except Exception as exc:
        logger.exception(
            "dispatcher: donna_turn (legacy) raised user=%s", event.user_id
        )
        legacy_error = f"{type(exc).__name__}: {str(exc)[:200]}"
    legacy_outbound = (
        legacy_result.get("_outbound") if isinstance(legacy_result, dict) else None
    )
    legacy_outbound_count = len(legacy_outbound or [])

    # ─── COUNTERFACTUAL PATH (Phase 1 mirror-only — fat-contract Tier 3) ───
    counterfactual_outcome: str | None = None
    counterfactual_draft: str | None = None
    counterfactual_skip_reason: str | None = None
    counterfactual_elapsed_ms: int | None = None
    counterfactual_error: str | None = None

    started = time.monotonic()
    try:
        await _run_counterfactual_tier3(
            event=event,
            judge=judge,
            escalation_reason=escalation_reason,
            phone=phone,
            on_outcome=lambda o, d, sr: _capture_counterfactual(
                o, d, sr, locals=locals()
            ),
        )
    except Exception as exc:
        logger.exception(
            "dispatcher: counterfactual fat-contract raised user=%s",
            event.user_id,
        )
        counterfactual_error = f"{type(exc).__name__}: {str(exc)[:200]}"
    counterfactual_elapsed_ms = int((time.monotonic() - started) * 1000)

    # ─── LOG TELEMETRY ───────────────────────────────────────────────────
    try:
        await _write_dispatch_telemetry(
            event=event,
            judge=judge,
            escalation_reason=escalation_reason,
            legacy_outbound_count=legacy_outbound_count,
            counterfactual_outcome=counterfactual_outcome,
            counterfactual_draft=counterfactual_draft,
            counterfactual_skip_reason=counterfactual_skip_reason,
            counterfactual_elapsed_ms=counterfactual_elapsed_ms,
            counterfactual_error=counterfactual_error,
        )
    except Exception:
        logger.exception(
            "dispatcher: telemetry write failed user=%s", event.user_id
        )

    # ─── RETURN LEGACY OUTCOME (counterfactual is silent) ────────────────
    if legacy_error is not None:
        return DispatchOutcome(
            action="errored",
            reason=f"brain_raised:{legacy_error}",
            judge=judge,
        )
    return DispatchOutcome(
        action="shipped" if legacy_outbound_count > 0 else "skipped",
        reason="tier3_legacy",
        judge=judge,
        ping_id=None,
        draft=None,
    )
```

Add the supporting helpers below `_escalate_to_brain`:

```python
async def _run_counterfactual_tier3(
    *,
    event: ProactiveEvent,
    judge: JudgeResult | None,
    escalation_reason: str,
    phone: str | None,
    on_outcome,
) -> None:
    """Run the fat-contract Tier 3 turn for telemetry only. Never ships."""
    if judge is None:
        return  # nothing to escalate from
    from donna_runtime.brain import donna_turn
    from donna_runtime.config import DonnaAgentConfig
    from donna_runtime.context_builder_tier3 import build_tier3_user_message

    # Phase 1 minimal block builders — real ones land in Phase 2/3. For now
    # we render the precomputable blocks as best we can from already-loaded
    # context, and pass empty placeholders for the rest. The point is that
    # the counterfactual call exercises the new prompt + tools surface.
    user_message = build_tier3_user_message(
        event=event,
        judge=judge,
        escalation_reason=escalation_reason,  # type: ignore[arg-type]
        user_model_block="(phase 1 — USER MODEL block not yet populated)",
        queued_thing_block="(phase 1 — queued spec block not yet populated)",
        day_view_block="(phase 1 — DAY view block not yet populated)",
        prior_touches_block="(phase 1 — prior touches block not yet populated)",
        user_state_block="(phase 1 — user state block not yet populated)",
        pending_notes_block="(phase 1 — pending notes block not yet populated)",
        fresh_signal_block=None,
    )

    cfg = DonnaAgentConfig(
        mode="proactive_tier3",
        user_id=event.user_id,
        user_phone=phone,
        stateless_sessions=True,
    )
    state: dict[str, Any] = {
        "user_id": event.user_id,
        "raw_input": user_message,
        "user_message": user_message,
        "phone": phone,
        "trigger": {
            "source": event.source,
            "speech_act": event.speech_act,
            "topic_key": event.topic_key,
            "escalation_reason": escalation_reason,
        },
    }
    result = await donna_turn(state, cfg)
    outcome = (
        result.get("_tier3_outcome")
        if isinstance(result, dict)
        else None
    ) or {}
    on_outcome(
        outcome.get("action"),
        outcome.get("messages"),
        outcome.get("reason"),
    )


def _capture_counterfactual(action, draft, skip_reason, *, locals):
    """Tiny indirection so closures over local vars in _escalate_to_brain
    work cleanly. Sets the three fields the telemetry write reads."""
    locals["counterfactual_outcome"] = action
    if isinstance(draft, list) and draft:
        first = draft[0]
        body = (first.get("body") if isinstance(first, dict) else None) or ""
        locals["counterfactual_draft"] = body[:500]
    if isinstance(skip_reason, str):
        locals["counterfactual_skip_reason"] = skip_reason[:500]


async def _write_dispatch_telemetry(
    *,
    event: ProactiveEvent,
    judge: JudgeResult | None,
    escalation_reason: str,
    legacy_outbound_count: int,
    counterfactual_outcome: str | None,
    counterfactual_draft: str | None,
    counterfactual_skip_reason: str | None,
    counterfactual_elapsed_ms: int | None,
    counterfactual_error: str | None,
) -> None:
    """Write one ProactiveDispatchTelemetry row. Best-effort."""
    try:
        from db.models import ProactiveDispatchTelemetry, generate_uuid
        from backend.db.session import async_session
    except Exception:
        logger.exception("dispatcher: telemetry imports failed")
        return
    async with async_session() as session:
        row = ProactiveDispatchTelemetry(
            id=generate_uuid(),
            user_id=event.user_id,
            source=event.source,
            speech_act=event.speech_act,
            topic_key=event.topic_key,
            tier1_score=(
                float(event.signals.get("score") or 0.0)
                if event.signals.get("score") is not None
                else None
            ),
            arbiter_decision=None,
            arbiter_reason=None,
            tier2_action=judge.action if judge else None,
            tier2_register=judge.register if judge else None,
            tier2_draft=judge.draft if judge else None,
            tier2_needs_tools=judge.needs_tools if judge else None,
            tier2_channel_hint=getattr(judge, "channel_hint", None),
            tier2_reclassify=getattr(judge, "reclassify_speech_act", None),
            tier3_invoked=True,
            tier3_outcome="legacy_thin_directive",
            channel="whatsapp" if legacy_outbound_count > 0 else None,
            counterfactual_legacy_outbound_count=legacy_outbound_count,
            counterfactual_fat_contract_outcome=counterfactual_outcome,
            counterfactual_fat_contract_draft=counterfactual_draft,
            counterfactual_fat_contract_skip_reason=counterfactual_skip_reason,
            counterfactual_fat_contract_elapsed_ms=counterfactual_elapsed_ms,
            counterfactual_fat_contract_error=counterfactual_error,
        )
        session.add(row)
        await session.commit()
```

> **Note for the implementer:** the existing `_escalate_to_brain` returns a `DispatchOutcome` with specific fields used downstream. Preserve the exact return shape your codebase expects. The diff above is illustrative — adapt to the existing `DispatchOutcome` constructor.

- [ ] **Step 4: Adjust the test if patching shape needs to change**

The test in Step 1 patches `proactive.dispatcher.donna_turn` — confirm that's the actual import in `dispatcher.py` (we lazy-import inside the function, so the patch target is the symbol AS IT EXISTS in the module, which after our refactor is `proactive.dispatcher.donna_turn` only if we hoist the import. Likely cleaner to patch `donna_runtime.brain.donna_turn`).

If patching `donna_runtime.brain.donna_turn` is needed, update the test:

```python
with patch("donna_runtime.brain.donna_turn", side_effect=[...]):
```

- [ ] **Step 5: Run the test**

```
pytest backend/tests/proactive/test_dispatcher_tier3_mirror.py -v
```
Expected: 1 passed.

- [ ] **Step 6: Smoke-run the existing dispatcher test suite to catch regressions**

```
pytest backend/tests/proactive/test_dispatcher.py -v
```
Expected: same pass count as before this PR.

- [ ] **Step 7: Commit**

```bash
git add proactive/dispatcher.py backend/tests/proactive/test_dispatcher_tier3_mirror.py
git commit -m "feat(proactive): wire fat-contract Tier 3 counterfactual in dispatcher (mirror-only)

Every _escalate_to_brain call now runs the legacy thin-directive
donna_turn (mode='proactive', unchanged) AND a counterfactual fat-contract
Tier 3 turn (mode='proactive_tier3'), logging both outcomes to
proactive_dispatch_telemetry. The counterfactual NEVER ships — only the
legacy outcome reaches the worker / WhatsApp.

Phase 1 of proactive brain redesign: enables A/B comparison before
flipping anything live."
```

---

## Task 12: Counterfactual eval script

**Files:**
- Create: `scripts/proactive_counterfactual_eval.py`

- [ ] **Step 1: Write the script**

Create `scripts/proactive_counterfactual_eval.py`:

```python
"""Counterfactual eval — compare legacy thin-directive vs fat-contract Tier 3.

Reads ``proactive_dispatch_telemetry`` rows from the last N days, prints a
per-speech-act and per-source breakdown of:
  - decision agreement (did both paths choose ship vs skip the same way?)
  - draft length deltas
  - elapsed_ms for the counterfactual path
  - error rate for the counterfactual path

Run:
    python -m scripts.proactive_counterfactual_eval --days 7
    python -m scripts.proactive_counterfactual_eval --user user_xxx
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select


async def _load_rows(*, days: int, user_id: str | None) -> list[Any]:
    from backend.db.session import async_session
    from db.models import ProactiveDispatchTelemetry

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    async with async_session() as session:
        q = select(ProactiveDispatchTelemetry).where(
            ProactiveDispatchTelemetry.event_at >= cutoff.replace(tzinfo=None)
        )
        if user_id:
            q = q.where(ProactiveDispatchTelemetry.user_id == user_id)
        q = q.order_by(ProactiveDispatchTelemetry.event_at.desc())
        rows = (await session.execute(q)).scalars().all()
    return list(rows)


def _summarize(rows: list[Any]) -> dict[str, Any]:
    total = len(rows)
    counterfactual_errors = sum(
        1 for r in rows if r.counterfactual_fat_contract_error
    )
    legacy_ships = sum(
        1 for r in rows if (r.counterfactual_legacy_outbound_count or 0) > 0
    )
    fat_ships = sum(
        1 for r in rows if r.counterfactual_fat_contract_outcome == "ship"
    )
    fat_skips = sum(
        1 for r in rows if r.counterfactual_fat_contract_outcome == "skip"
    )

    # Per-speech-act breakdown
    by_act: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "n": 0,
            "legacy_ships": 0,
            "fat_ships": 0,
            "fat_skips": 0,
            "errors": 0,
        }
    )
    for r in rows:
        a = by_act[r.speech_act or "unknown"]
        a["n"] += 1
        if (r.counterfactual_legacy_outbound_count or 0) > 0:
            a["legacy_ships"] += 1
        if r.counterfactual_fat_contract_outcome == "ship":
            a["fat_ships"] += 1
        if r.counterfactual_fat_contract_outcome == "skip":
            a["fat_skips"] += 1
        if r.counterfactual_fat_contract_error:
            a["errors"] += 1

    elapsed = [
        r.counterfactual_fat_contract_elapsed_ms
        for r in rows
        if r.counterfactual_fat_contract_elapsed_ms is not None
    ]
    p50 = sorted(elapsed)[len(elapsed) // 2] if elapsed else None
    p95 = sorted(elapsed)[int(len(elapsed) * 0.95) - 1] if elapsed else None

    return {
        "total": total,
        "legacy_ships": legacy_ships,
        "fat_ships": fat_ships,
        "fat_skips": fat_skips,
        "counterfactual_errors": counterfactual_errors,
        "by_speech_act": dict(by_act),
        "elapsed_ms_p50": p50,
        "elapsed_ms_p95": p95,
    }


def _print_report(summary: dict[str, Any], days: int) -> None:
    print(f"=== proactive counterfactual eval — last {days} days ===\n")
    print(f"total events:            {summary['total']}")
    print(f"counterfactual errors:   {summary['counterfactual_errors']}")
    print(f"legacy_ships:            {summary['legacy_ships']}")
    print(f"fat_ships:               {summary['fat_ships']}")
    print(f"fat_skips:               {summary['fat_skips']}")
    print(f"elapsed_ms p50 / p95:    {summary['elapsed_ms_p50']} / {summary['elapsed_ms_p95']}")
    print()
    print("per speech_act:")
    for act, stats in sorted(summary["by_speech_act"].items()):
        print(
            f"  {act:20} n={stats['n']:>4}  "
            f"legacy_ship={stats['legacy_ships']:>3}  "
            f"fat_ship={stats['fat_ships']:>3}  "
            f"fat_skip={stats['fat_skips']:>3}  "
            f"err={stats['errors']:>2}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Counterfactual eval for proactive brain Phase 1."
    )
    parser.add_argument(
        "--days", type=int, default=7, help="window in days (default 7)"
    )
    parser.add_argument(
        "--user", type=str, default=None, help="filter to one user_id"
    )
    args = parser.parse_args()

    async def _run() -> dict[str, Any]:
        rows = await _load_rows(days=args.days, user_id=args.user)
        return _summarize(rows)

    summary = asyncio.run(_run())
    _print_report(summary, days=args.days)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke-run the script (will print zeros if no rows yet)**

```
python -m scripts.proactive_counterfactual_eval --days 1
```
Expected: prints header and zero counts (no telemetry rows yet in dev).

- [ ] **Step 3: Commit**

```bash
git add scripts/proactive_counterfactual_eval.py
git commit -m "feat(scripts): proactive_counterfactual_eval — compare legacy vs fat-contract

Reads proactive_dispatch_telemetry rows over a window, prints a per-speech-act
breakdown of decision counts, error rate, and counterfactual elapsed_ms
(p50 / p95). Used during Phase 1 to evaluate the new pipeline's behavior
before flipping anything live.

Phase 1 of proactive brain redesign."
```

---

## Self-Review

After all 12 tasks complete, run this checklist:

- [ ] **Spec coverage:**
  - Task 1 → Section 'ProactiveEvent envelope (extended)'
  - Task 2 → Section 'Tier 2 — speech-act-aware judge-and-author' (schema additions)
  - Task 3 → Section 'speech_act is set at the source adapter'
  - Task 4 → Section 'Observability — proactive_dispatch_telemetry'
  - Task 5 → Section 'FRESH SIGNAL (CONDITIONAL)' in Tier 3 input contract
  - Task 6-8 → Section 'Tier 3 tool palette (6 tools)'
  - Task 9 → Section 'Tier 3 input contract — 11 blocks'
  - Task 10 → Section 'Tier 3 system prompt' + 'mode="proactive_tier3"'
  - Task 11 → Section 'mirror-mode counterfactual' in Phase 1
  - Task 12 → Section 'Migration — exit criterion: "fat-contract Tier 3 ships zero messages but logs every counterfactual"'

  Coverage: every Phase-1 spec requirement has a task. ✓

- [ ] **Placeholder scan:** no "TBD"/"TODO" in plan steps. The Phase-1 stub fetchers in Tasks 5 and 8 are intentionally placeholders inside the source code (real fetchers land in Phase 2 with System B fold-in) and are documented as such.

- [ ] **Type consistency:**
  - `SpeechAct` literal values are identical across Tasks 1, 2, 3, 9
  - `_JudgeOut.channel_hint` matches `JudgeResult.channel_hint`
  - `mode="proactive_tier3"` matches between Tasks 10 and 11
  - `surface_at` literal matches between Task 7 and the spec
  - Tool function names match between Tasks 6, 7, 8 and Task 10's tool registration

- [ ] **Run order:** Tasks 1-4 are independent of each other (do in any order). Tasks 5-8 depend on Tasks 1-2 (need types). Task 9 depends on Tasks 1+2. Task 10 depends on Tasks 6+7+8 (tool names). Task 11 depends on Tasks 9+10 + 4 (telemetry table). Task 12 depends on Task 4 only (reads the telemetry table).

  Recommended order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-04-proactive-brain-phase-1.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
