"""Phase 3 wiring: attention_fire + attention_offer source adapters.

Covers:
  - ``make_event`` for both adapters with realistic inputs
  - Topic-key dedup across attention sources (cooldown on same attention_id)
  - Hold action on attention_fire (e.g., reminder fires while user is in a
    calendar event)
  - Mirror-mode fallback (when dispatcher returns ``mirror_logged``, the
    legacy ``fire_attention_via_brain`` path still runs)
  - Promote-cycle dispatch gated correctly on the flag combination
  - End-to-end integration: a fabricated DonnaSchedule row →
    schedule_worker.run_once → dispatcher → row state at the end

The Haiku judge call is replaced with a stub so no network or production
DB is touched. The brain (``donna_turn``) is replaced too. Everything
else uses the in-memory sqlite from ``conftest.py``.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from proactive.events import ProactiveEvent
from proactive.judge import JudgeResult


# -- Fixtures ---------------------------------------------------------------


@pytest.fixture
def _allow(monkeypatch):
    """Default arbiter response: allow."""
    from backend.integrations.proactive_rate_limit import FireDecision

    async def _can(user_id, source, *, topic_key=None, now=None):  # noqa: ANN001
        return FireDecision(allowed=True, reason="ok")

    monkeypatch.setattr(
        "backend.integrations.proactive_rate_limit.can_fire_proactive",
        _can,
    )


@pytest.fixture
def _no_quiet_hours(monkeypatch):
    async def _none(_user_id):  # noqa: ANN001
        return (None, None)

    monkeypatch.setattr(
        "backend.integrations.proactive_rate_limit._load_user_quiet_hours",
        _none,
    )

    async def _no_tz(_user_id):  # noqa: ANN001
        return None

    monkeypatch.setattr(
        "backend.integrations.proactive_rate_limit._load_user_timezone",
        _no_tz,
    )


@pytest.fixture
def _gated_mode(monkeypatch):
    monkeypatch.setenv("DONNA_PROACTIVE_TIERED", "1")


@pytest.fixture
def _mirror_mode(monkeypatch):
    monkeypatch.delenv("DONNA_PROACTIVE_TIERED", raising=False)


@pytest.fixture
def _stub_judge(monkeypatch):
    """Replace ``judge_event`` with a controllable stub. Returns a setter."""

    state = {"result": _judge_ping()}

    async def _fake(_event):
        return state["result"]

    monkeypatch.setattr("proactive.dispatcher.judge_event", _fake)

    def _set(result):
        state["result"] = result

    return _set


# -- Helpers ----------------------------------------------------------------


def _row(
    *,
    attention_id="att-1",
    user_id="u1",
    phone="+1",
    fire_at=None,
    cadence_type="one_shot",
    question="did you take your meds",
):
    fire = fire_at or datetime(2026, 4, 26, 20, 0)
    return SimpleNamespace(
        id="sched-1",
        user_id=user_id,
        phone=phone,
        fire_at=fire,
        attention_id=attention_id,
        recurrence_meta={
            "cadence_type": cadence_type,
            "cadence_params": {},
            "user_tz": "Asia/Singapore",
            "question": question,
        },
        context={"messages": [{"type": "text", "body": question}]},
    )


def _attention_stub(
    *,
    title="evening meds",
    description="ping at 8pm to confirm meds",
    card_value="ping",
    subject_name="evening_meds",
    aid="att-1",
    user_id="u1",
    promotion_hits=2,
    tick_count=3,
):
    spec = SimpleNamespace(
        title=title,
        description=description,
        card=SimpleNamespace(value=card_value),
        subject=SimpleNamespace(name=subject_name),
    )
    shadow = SimpleNamespace(
        promotion_hits=promotion_hits,
        tick_count=tick_count,
    )
    return SimpleNamespace(
        id=aid,
        user_id=user_id,
        spec=spec,
        shadow_state=shadow,
    )


def _judge_ping(
    draft="meds. did you take them.",
    register="alert",
    needs_tools=False,
):
    return JudgeResult(
        action="ping",
        register=register,
        draft=draft,
        tie_in=("evening-meds",),
        needs_tools=needs_tools,
        reasoning="concrete one-shot reminder",
        raw_response="{}",
    )


def _judge_hold(draft="stretch when the design review wraps."):
    return JudgeResult(
        action="hold",
        register=None,
        draft=draft,
        tie_in=("stretch-cadence",),
        needs_tools=False,
        reasoning="cadence fired during meeting",
        raw_response="{}",
    )


def _judge_drop():
    return JudgeResult(
        action="drop",
        register=None,
        draft=None,
        tie_in=(),
        needs_tools=False,
        reasoning="redundant",
        raw_response="{}",
    )


# -- attention_fire.make_event ---------------------------------------------


def test_attention_fire_make_event_with_hydrated_attention():
    from proactive.sources.attention_fire import make_event

    row = _row()
    attention = _attention_stub()
    event = make_event(row, attention)

    assert isinstance(event, ProactiveEvent)
    assert event.source == "attention_fire"
    assert event.source_ref == "att-1"
    assert event.topic_key == "att-1"
    assert event.user_id == "u1"
    assert event.payload["question"] == "did you take your meds"
    assert event.payload["cadence_type"] == "one_shot"
    assert event.payload["subject"] == "evening_meds"
    assert event.payload["card"] == "ping"
    assert "8pm" in event.payload["rationale"]
    assert event.signals["cadence_type"] == "one_shot"
    assert event.signals["is_recurring"] is False


def test_attention_fire_make_event_without_attention_is_tolerant():
    from proactive.sources.attention_fire import make_event

    row = _row()
    event = make_event(row, None)

    assert event.source == "attention_fire"
    assert event.payload["question"] == "did you take your meds"
    # Optional fields are omitted when attention is None.
    assert "subject" not in event.payload
    assert "card" not in event.payload
    assert "rationale" not in event.payload


def test_attention_fire_make_event_marks_recurring_for_scheduled_cadence():
    from proactive.sources.attention_fire import make_event

    row = _row(cadence_type="scheduled")
    event = make_event(row, None)
    assert event.signals["is_recurring"] is True


def test_attention_fire_make_event_caps_long_rationale():
    from proactive.sources.attention_fire import make_event

    long_desc = "x" * 2000
    attention = _attention_stub(description=long_desc)
    event = make_event(_row(), attention)
    assert len(event.payload["rationale"]) <= 410  # 400 + " ..."


# -- attention_offer.make_event --------------------------------------------


def test_attention_offer_make_event_basic():
    from proactive.sources.attention_offer import make_event

    attention = _attention_stub(
        title="watch nvidia earnings",
        description="user mentioned nvda 3x this week",
        card_value="brief",
        subject_name="nvidia",
    )
    event = make_event(attention)

    assert event.source == "attention_offer"
    assert event.source_ref == "att-1"
    assert event.topic_key == "att-1"
    assert event.payload["title"] == "watch nvidia earnings"
    assert event.payload["card"] == "brief"
    assert event.payload["subject"] == "nvidia"
    assert event.signals["promotion_hits"] == 2
    assert event.signals["tick_count"] == 3


def test_attention_offer_attach_recent_source_counts_returns_new_event():
    from proactive.sources.attention_offer import (
        attach_recent_source_counts,
        make_event,
    )

    attention = _attention_stub()
    event = make_event(attention)
    enriched = attach_recent_source_counts(event, {"google_news": 4})

    assert enriched is not event
    assert enriched.signals["source_counts"] == {"google_news": 4}
    # Original event unchanged.
    assert "source_counts" not in event.signals


def test_attention_offer_attach_recent_source_counts_noop_on_empty():
    from proactive.sources.attention_offer import (
        attach_recent_source_counts,
        make_event,
    )

    event = make_event(_attention_stub())
    out = attach_recent_source_counts(event, None)
    assert out is event


# -- Topic-key dedup --------------------------------------------------------


@pytest.mark.asyncio
async def test_attention_fire_topic_dedup_via_arbiter(
    db, _no_quiet_hours, _gated_mode, _stub_judge, monkeypatch
):
    """Two fires on the same attention within cooldown → second is suppressed.

    Real arbiter logic kicks in: the first dispatch records a ProactivePing
    with the topic_key; the second dispatch's ``can_fire_proactive`` sees
    the topic_cooldown and denies.
    """
    from sqlalchemy import select

    from db.models import ProactivePing
    from proactive.dispatcher import dispatch
    from proactive.sources.attention_fire import make_event

    # Stub the WhatsApp send so the gated ship path is observable.
    sent = []

    class FakeChannel:
        async def send_many(self, phone, messages):
            sent.append((phone, messages))
            return ["wamid"]

    monkeypatch.setattr("delivery.whatsapp.WhatsAppChannel", lambda: FakeChannel())

    _stub_judge(_judge_ping())

    row = _row()
    event = make_event(row, _attention_stub())

    out1 = await dispatch(event)
    assert out1.action == "shipped"

    # Second dispatch on same attention_id within cooldown: suppressed.
    out2 = await dispatch(event)
    assert out2.action == "suppressed"
    assert "topic_cooldown" in out2.reason or "cooldown" in out2.reason

    async with db() as s:
        rows = (await s.execute(select(ProactivePing))).scalars().all()
    # One real ping + one suppression row.
    statuses = sorted(
        ("suppressed" if r.suppressed_reason else "fired") for r in rows
    )
    assert statuses == ["fired", "suppressed"]


# -- Hold action on attention_fire -----------------------------------------


@pytest.mark.asyncio
async def test_attention_fire_hold_inserts_pending_note(
    db, _allow, _no_quiet_hours, _gated_mode, _stub_judge
):
    """Reminder fires while user is mid-meeting → Tier 2 holds → pending row."""
    from sqlalchemy import select

    from db.models import PendingProactiveNote
    from proactive.dispatcher import dispatch
    from proactive.sources.attention_fire import make_event

    _stub_judge(_judge_hold(draft="stretch when the design review wraps."))

    event = make_event(_row(), _attention_stub())
    outcome = await dispatch(event)

    assert outcome.action == "held"
    assert outcome.note_id is not None
    assert outcome.draft == "stretch when the design review wraps."

    async with db() as s:
        rows = (await s.execute(select(PendingProactiveNote))).scalars().all()
    assert len(rows) == 1
    note = rows[0]
    assert note.status == "pending"
    assert note.source == "attention_fire"
    assert note.topic_key == "att-1"
    assert note.draft == "stretch when the design review wraps."


# -- Mirror-mode fallback for schedule worker ------------------------------


@pytest.mark.asyncio
async def test_fire_attention_mirror_mode_calls_legacy_brain(
    _mirror_mode, monkeypatch
):
    """Without DONNA_PROACTIVE_TIERED, the worker uses fire_attention_via_brain."""
    from backend.memory.jobs import schedule_worker

    invoked = {}

    async def fake_legacy(row):
        invoked["row"] = row
        return ["legacy-buffer-item"]

    monkeypatch.setattr(
        "donna.attention.firing.fire_attention_via_brain", fake_legacy
    )

    out = await schedule_worker._fire_attention(_row())
    assert invoked["row"] is not None
    assert out == ["legacy-buffer-item"]


@pytest.mark.asyncio
async def test_fire_attention_dispatcher_error_falls_back_to_legacy(
    _gated_mode, monkeypatch
):
    """Dispatcher raises → worker falls back to fire_attention_via_brain."""
    from backend.memory.jobs import schedule_worker

    async def fake_dispatch(_event):
        raise RuntimeError("boom")

    monkeypatch.setattr("proactive.dispatcher.dispatch", fake_dispatch)

    invoked = {}

    async def fake_legacy(row):
        invoked["row"] = row
        return ["fallback-item"]

    monkeypatch.setattr(
        "donna.attention.firing.fire_attention_via_brain", fake_legacy
    )

    # AttentionStore.get is best-effort; force a benign None.
    async def fake_hydrate(_aid):
        return None

    monkeypatch.setattr(schedule_worker, "_hydrate_attention", fake_hydrate)

    out = await schedule_worker._fire_attention(_row())
    assert out == ["fallback-item"]
    assert invoked


@pytest.mark.asyncio
async def test_fire_attention_gated_held_returns_empty_and_writes_chat(
    db, _allow, _no_quiet_hours, _gated_mode, _stub_judge, monkeypatch
):
    from sqlalchemy import select

    from backend.memory.jobs import schedule_worker
    from db.models import ChatMessage, PendingProactiveNote

    _stub_judge(_judge_hold(draft="stretch when the design review wraps."))

    async def fake_hydrate(_aid):
        return None

    monkeypatch.setattr(schedule_worker, "_hydrate_attention", fake_hydrate)

    out = await schedule_worker._fire_attention(_row())
    assert out == []

    async with db() as s:
        notes = (
            await s.execute(select(PendingProactiveNote))
        ).scalars().all()
        chats = (await s.execute(select(ChatMessage))).scalars().all()
    assert len(notes) == 1
    assert len(chats) == 1
    assert chats[0].is_proactive is True
    assert chats[0].content.startswith("[held]")


@pytest.mark.asyncio
async def test_fire_attention_gated_dropped_returns_empty(
    db, _allow, _no_quiet_hours, _gated_mode, _stub_judge, monkeypatch
):
    from backend.memory.jobs import schedule_worker

    _stub_judge(_judge_drop())

    async def fake_hydrate(_aid):
        return None

    monkeypatch.setattr(schedule_worker, "_hydrate_attention", fake_hydrate)

    out = await schedule_worker._fire_attention(_row())
    assert out == []


# -- Promote-cycle dispatch gating -----------------------------------------


def test_promote_cycle_does_not_dispatch_without_flags(monkeypatch):
    """Default behavior (no flags): promotion does not trigger dispatcher."""
    from donna.attention import promote

    # Both flags off.
    monkeypatch.delenv("DONNA_PROACTIVE_TIERED", raising=False)
    monkeypatch.delenv("DONNA_PROACTIVE_OFFER_ACTIVE", raising=False)

    called = {"n": 0}

    def _trip(_promoted):  # noqa: ANN001
        called["n"] += 1

    monkeypatch.setattr(promote, "_dispatch_offer_events", _trip)

    assert promote._offer_dispatch_enabled() is False


def test_promote_cycle_does_not_dispatch_when_only_tiered_flag_on(monkeypatch):
    from donna.attention import promote

    monkeypatch.setenv("DONNA_PROACTIVE_TIERED", "1")
    monkeypatch.delenv("DONNA_PROACTIVE_OFFER_ACTIVE", raising=False)
    assert promote._offer_dispatch_enabled() is False


def test_promote_cycle_does_not_dispatch_when_only_offer_flag_on(monkeypatch):
    from donna.attention import promote

    monkeypatch.delenv("DONNA_PROACTIVE_TIERED", raising=False)
    monkeypatch.setenv("DONNA_PROACTIVE_OFFER_ACTIVE", "1")
    assert promote._offer_dispatch_enabled() is False


def test_promote_cycle_dispatches_when_both_flags_on(monkeypatch):
    from donna.attention import promote

    monkeypatch.setenv("DONNA_PROACTIVE_TIERED", "1")
    monkeypatch.setenv("DONNA_PROACTIVE_OFFER_ACTIVE", "1")
    assert promote._offer_dispatch_enabled() is True


def test_run_shadow_cycle_with_flags_on_calls_dispatch(tmp_path, monkeypatch):
    """Full run_shadow_cycle path: a promotion fires _dispatch_offer_events."""
    from datetime import datetime, timezone
    from uuid import uuid4

    from donna.attention import promote
    from donna.attention.dry_run import DryRunResult, SourcePreview
    from donna.attention.examples.gold_specs import GOLD_EXAMPLES
    from donna.attention.schema import (
        Attention,
        AttentionOrigin,
        AttentionStatus,
        ShadowState,
    )
    from donna.attention.store import AttentionStore
    from donna.attention.vocabulary import SourceType

    monkeypatch.setenv("DONNA_PROACTIVE_TIERED", "1")
    monkeypatch.setenv("DONNA_PROACTIVE_OFFER_ACTIVE", "1")

    spec = next(g for g in GOLD_EXAMPLES if g.example_id == "poke_watch").spec
    store = AttentionStore(path=tmp_path / "attentions.json")
    user_id = uuid4()
    store.save(
        Attention(
            user_id=user_id,
            spec=spec,
            origin=AttentionOrigin.SHADOW_INFERRED,
            status=AttentionStatus.SHADOW,
            created_at=datetime.now(timezone.utc),
            shadow_state=ShadowState(max_ticks=3),
        )
    )

    def hit_preview(spec, user_id=None):
        return DryRunResult(
            spec_title=spec.title,
            card=spec.card,
            source_previews=(
                SourcePreview(
                    source_type=SourceType.WHATSAPP_MENTIONS_ENTITY,
                    item_count=1,
                    sample=[{"id": "x"}],
                ),
            ),
            rendered_markdown="hit",
        )

    monkeypatch.setattr("donna.attention.promote.dry_run", hit_preview)

    captured = {"n": 0}

    def _spy(promoted):
        captured["n"] += 1
        captured["promoted"] = promoted

    monkeypatch.setattr(promote, "_dispatch_offer_events", _spy)

    # First cycle: 1 hit → SHADOW (no promotion yet).
    promote.run_shadow_cycle(store=store)
    assert captured["n"] == 0

    # Second cycle: 2 hits → promoted. Dispatch should fire.
    promote.run_shadow_cycle(store=store)
    assert captured["n"] == 1
    assert len(captured["promoted"]) == 1
    promoted_attention, source_counts = captured["promoted"][0]
    assert promoted_attention.status is AttentionStatus.OFFERED
    assert source_counts


def test_run_shadow_cycle_with_flags_off_skips_dispatch(tmp_path, monkeypatch):
    """No flags: promotion is silent (passive surfacing only)."""
    from datetime import datetime, timezone
    from uuid import uuid4

    from donna.attention import promote
    from donna.attention.dry_run import DryRunResult, SourcePreview
    from donna.attention.examples.gold_specs import GOLD_EXAMPLES
    from donna.attention.schema import (
        Attention,
        AttentionOrigin,
        AttentionStatus,
        ShadowState,
    )
    from donna.attention.store import AttentionStore
    from donna.attention.vocabulary import SourceType

    monkeypatch.delenv("DONNA_PROACTIVE_TIERED", raising=False)
    monkeypatch.delenv("DONNA_PROACTIVE_OFFER_ACTIVE", raising=False)

    spec = next(g for g in GOLD_EXAMPLES if g.example_id == "poke_watch").spec
    store = AttentionStore(path=tmp_path / "attentions.json")
    store.save(
        Attention(
            user_id=uuid4(),
            spec=spec,
            origin=AttentionOrigin.SHADOW_INFERRED,
            status=AttentionStatus.SHADOW,
            created_at=datetime.now(timezone.utc),
            shadow_state=ShadowState(max_ticks=3),
        )
    )

    def hit_preview(spec, user_id=None):
        return DryRunResult(
            spec_title=spec.title,
            card=spec.card,
            source_previews=(
                SourcePreview(
                    source_type=SourceType.WHATSAPP_MENTIONS_ENTITY,
                    item_count=1,
                    sample=[{"id": "x"}],
                ),
            ),
            rendered_markdown="hit",
        )

    monkeypatch.setattr("donna.attention.promote.dry_run", hit_preview)

    captured = {"n": 0}

    def _spy(promoted):
        captured["n"] += 1

    monkeypatch.setattr(promote, "_dispatch_offer_events", _spy)

    # Two cycles → promotion. Dispatch must NOT fire.
    promote.run_shadow_cycle(store=store)
    promote.run_shadow_cycle(store=store)
    assert captured["n"] == 0


# -- End-to-end integration through schedule_worker.run_once ---------------


@pytest.mark.asyncio
async def test_run_once_attention_ship_path_marks_row_fired(
    db, _allow, _no_quiet_hours, _gated_mode, _stub_judge, monkeypatch
):
    """Fabricated DonnaSchedule → run_once → Tier 2 ships → row fired."""
    from sqlalchemy import select

    from backend.memory.jobs import schedule_worker
    from backend.memory.time import utcnow_naive
    from db.models import ChatMessage, DonnaSchedule, ProactivePing

    sent = []

    class FakeChannel:
        async def send_many(self, phone, messages):
            sent.append((phone, messages))
            return ["wamid"]

    monkeypatch.setattr(
        "delivery.whatsapp.WhatsAppChannel", lambda: FakeChannel()
    )

    async def fake_hydrate(_aid):
        return _attention_stub()

    monkeypatch.setattr(schedule_worker, "_hydrate_attention", fake_hydrate)

    # Skip the recurrence + last_surfaced_at hooks (the file-backed
    # attention store + postgres store are out of scope).
    async def _noop(_row):
        return None

    monkeypatch.setattr(
        schedule_worker, "_maybe_record_attention_surface", _noop
    )
    monkeypatch.setattr(schedule_worker, "_maybe_enqueue_next_fire", _noop)

    _stub_judge(_judge_ping())

    fire_at = utcnow_naive() - timedelta(minutes=1)
    async with db() as s:
        s.add(
            DonnaSchedule(
                id="sched-int-1",
                user_id="u1",
                phone="+1",
                fire_at=fire_at,
                origin="user",
                attention_id="att-int-1",
                recurrence_meta={
                    "cadence_type": "one_shot",
                    "cadence_params": {},
                    "user_tz": "UTC",
                    "question": "did you take your meds",
                },
                context={"messages": [{"type": "text", "body": "meds"}]},
                fired=False,
                status="pending",
            )
        )
        await s.commit()

    attempted = await schedule_worker.run_once()
    assert attempted == 1

    async with db() as s:
        row = (
            await s.execute(
                select(DonnaSchedule).where(DonnaSchedule.id == "sched-int-1")
            )
        ).scalar_one()
        chats = (await s.execute(select(ChatMessage))).scalars().all()
        pings = (await s.execute(select(ProactivePing))).scalars().all()
    assert row.fired is True
    assert row.status == "done"
    # Tier 2 ship: dispatcher wrote one chat row + one ping row + sent
    # exactly one WhatsApp burst with the judge's draft. Worker must NOT
    # add a second send (its constructed buffer is empty in this branch).
    assert len(sent) == 1
    assert sent[0][0] == "+1"
    assert sent[0][1][0].body == "meds. did you take them."
    assert len(chats) == 1
    assert chats[0].is_proactive is True
    assert len(pings) == 1
    assert pings[0].topic_key == "att-int-1"


@pytest.mark.asyncio
async def test_run_once_attention_held_marks_row_fired(
    db, _allow, _no_quiet_hours, _gated_mode, _stub_judge, monkeypatch
):
    """Tier 2 holds → row still marked fired, pending row exists."""
    from sqlalchemy import select

    from backend.memory.jobs import schedule_worker
    from backend.memory.time import utcnow_naive
    from db.models import DonnaSchedule, PendingProactiveNote

    class FakeChannel:
        async def send_many(self, phone, messages):
            return ["wamid"]

    monkeypatch.setattr(
        "delivery.whatsapp.WhatsAppChannel", lambda: FakeChannel()
    )

    async def fake_hydrate(_aid):
        return None

    monkeypatch.setattr(schedule_worker, "_hydrate_attention", fake_hydrate)

    async def _noop(_row):
        return None

    monkeypatch.setattr(
        schedule_worker, "_maybe_record_attention_surface", _noop
    )
    monkeypatch.setattr(schedule_worker, "_maybe_enqueue_next_fire", _noop)

    _stub_judge(_judge_hold())

    fire_at = utcnow_naive() - timedelta(minutes=1)
    async with db() as s:
        s.add(
            DonnaSchedule(
                id="sched-int-2",
                user_id="u1",
                phone="+1",
                fire_at=fire_at,
                origin="user",
                attention_id="att-int-2",
                recurrence_meta={
                    "cadence_type": "scheduled",
                    "cadence_params": {},
                    "user_tz": "UTC",
                    "question": "stretch break",
                },
                context={"messages": [{"type": "text", "body": "stretch"}]},
                fired=False,
                status="pending",
            )
        )
        await s.commit()

    await schedule_worker.run_once()

    async with db() as s:
        row = (
            await s.execute(
                select(DonnaSchedule).where(DonnaSchedule.id == "sched-int-2")
            )
        ).scalar_one()
        notes = (
            await s.execute(select(PendingProactiveNote))
        ).scalars().all()
    assert row.fired is True
    assert row.status == "done"
    assert len(notes) == 1
    assert notes[0].source == "attention_fire"


@pytest.mark.asyncio
async def test_run_once_attention_mirror_mode_uses_legacy_buffer(
    db, _mirror_mode, monkeypatch
):
    """Mirror mode: legacy fire_attention_via_brain runs and worker ships."""
    from sqlalchemy import select

    from backend.memory.jobs import schedule_worker
    from backend.memory.time import utcnow_naive
    from db.models import ChatMessage, DonnaSchedule

    sent = []

    class FakeChannel:
        async def send_many(self, phone, messages):
            sent.append((phone, messages))
            return ["wamid"]

    monkeypatch.setattr(
        "delivery.whatsapp.WhatsAppChannel", lambda: FakeChannel()
    )

    from delivery.messages import TextMessage

    async def fake_legacy(row):
        return [TextMessage(body="legacy reminder body")]

    monkeypatch.setattr(
        "donna.attention.firing.fire_attention_via_brain", fake_legacy
    )

    async def _noop(_row):
        return None

    monkeypatch.setattr(
        schedule_worker, "_maybe_record_attention_surface", _noop
    )
    monkeypatch.setattr(schedule_worker, "_maybe_enqueue_next_fire", _noop)

    fire_at = utcnow_naive() - timedelta(minutes=1)
    async with db() as s:
        s.add(
            DonnaSchedule(
                id="sched-int-3",
                user_id="u1",
                phone="+1",
                fire_at=fire_at,
                origin="user",
                attention_id="att-int-3",
                recurrence_meta={
                    "cadence_type": "one_shot",
                    "cadence_params": {},
                    "user_tz": "UTC",
                    "question": "meds",
                },
                context={"messages": [{"type": "text", "body": "meds"}]},
                fired=False,
                status="pending",
            )
        )
        await s.commit()

    await schedule_worker.run_once()

    async with db() as s:
        row = (
            await s.execute(
                select(DonnaSchedule).where(DonnaSchedule.id == "sched-int-3")
            )
        ).scalar_one()
        chats = (await s.execute(select(ChatMessage))).scalars().all()
    assert row.fired is True
    assert sent and sent[0][1][0].body == "legacy reminder body"
    # Legacy path writes the chat row via fired_reminder_chat_rows.
    assert len(chats) == 1
    assert chats[0].content == "legacy reminder body"
