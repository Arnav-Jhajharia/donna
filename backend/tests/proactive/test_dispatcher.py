"""Dispatcher branches: mirror, suppressed, drop, hold, ping-direct, ping-escalate."""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from proactive.events import ProactiveEvent
from proactive.judge import JudgeResult


def _event(**kw):
    base = dict(
        user_id="u1",
        source="email",
        source_ref="m1",
        topic_key="thread-A",
        payload={
            "from_address": "luca@antler.co",
            "from_name": "Luca",
            "subject": "thursday or friday?",
            "body_excerpt": "lock in dd call",
        },
        signals={"score": 0.7, "signals": ["biography_relationship"]},
    )
    base.update(kw)
    return ProactiveEvent(**base)


def _judge(
    action="ping",
    register="alert",
    draft="luca replied. wants thursday 4pm or friday morning.",
    needs_tools=False,
    failed=False,
    failure_reason=None,
):
    return JudgeResult(
        action=action,
        register=register,
        draft=draft,
        tie_in=("antler-dd-call",),
        needs_tools=needs_tools,
        reasoning="active loop, person matters",
        raw_response="{}",
        failed=failed,
        failure_reason=failure_reason,
    )


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
    monkeypatch.setattr(
        "proactive.dispatcher.can_fire_proactive",
        _can,
        raising=False,
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
def _mirror_mode(monkeypatch):
    monkeypatch.delenv("DONNA_PROACTIVE_TIERED", raising=False)


@pytest.fixture
def _gated_mode(monkeypatch):
    monkeypatch.setenv("DONNA_PROACTIVE_TIERED", "1")


@pytest.fixture
def _stub_judge(monkeypatch):
    """Replace ``judge_event`` with a controllable stub. Returns a setter."""

    state = {"result": _judge()}

    async def _fake(_event):
        return state["result"]

    monkeypatch.setattr("proactive.dispatcher.judge_event", _fake)

    def _set(result):
        state["result"] = result

    return _set


@pytest.mark.asyncio
async def test_mirror_mode_logs_and_does_not_ship(
    db, _no_quiet_hours, _mirror_mode, _stub_judge
):
    from sqlalchemy import select

    from db.models import ChatMessage, PendingProactiveNote, ProactivePing
    from proactive.dispatcher import dispatch

    outcome = await dispatch(_event())
    assert outcome.action == "mirror_logged"
    assert outcome.judge is not None
    assert outcome.judge.action == "ping"

    async with db() as s:
        chats = (await s.execute(select(ChatMessage))).scalars().all()
        pings = (await s.execute(select(ProactivePing))).scalars().all()
        notes = (
            await s.execute(select(PendingProactiveNote))
        ).scalars().all()
    assert chats == []
    assert pings == []
    assert notes == []


@pytest.mark.asyncio
async def test_suppressed_in_mirror_mode_no_ping_row(
    db, _mirror_mode, _stub_judge, monkeypatch
):
    from sqlalchemy import select

    from backend.integrations.proactive_rate_limit import FireDecision
    from db.models import ProactivePing
    from proactive.dispatcher import dispatch

    async def _deny(user_id, source, *, topic_key=None, now=None):  # noqa: ANN001
        return FireDecision(allowed=False, reason="cooldown:60s")

    monkeypatch.setattr(
        "backend.integrations.proactive_rate_limit.can_fire_proactive",
        _deny,
    )

    outcome = await dispatch(_event())
    assert outcome.action == "suppressed"
    assert outcome.reason == "cooldown:60s"
    async with db() as s:
        rows = (await s.execute(select(ProactivePing))).scalars().all()
    # mirror mode: do not write a suppression row.
    assert rows == []


@pytest.mark.asyncio
async def test_suppressed_in_gated_mode_writes_ping_row(
    db, _gated_mode, _stub_judge, monkeypatch
):
    from sqlalchemy import select

    from backend.integrations.proactive_rate_limit import FireDecision
    from db.models import ProactivePing
    from proactive.dispatcher import dispatch

    async def _deny(user_id, source, *, topic_key=None, now=None):  # noqa: ANN001
        return FireDecision(allowed=False, reason="cooldown:60s")

    monkeypatch.setattr(
        "backend.integrations.proactive_rate_limit.can_fire_proactive",
        _deny,
    )

    outcome = await dispatch(_event())
    assert outcome.action == "suppressed"
    async with db() as s:
        rows = (await s.execute(select(ProactivePing))).scalars().all()
    assert len(rows) == 1
    assert rows[0].suppressed_reason == "cooldown:60s"
    assert rows[0].topic_key == "thread-A"


@pytest.mark.asyncio
async def test_drop_in_gated_mode_writes_suppressed_ping(
    db, _allow, _no_quiet_hours, _gated_mode, _stub_judge
):
    from sqlalchemy import select

    from db.models import ProactivePing
    from proactive.dispatcher import dispatch

    _stub_judge(_judge(action="drop", register=None, draft=None))

    outcome = await dispatch(_event())
    assert outcome.action == "dropped"
    async with db() as s:
        rows = (await s.execute(select(ProactivePing))).scalars().all()
    assert len(rows) == 1
    assert rows[0].suppressed_reason is not None
    assert rows[0].suppressed_reason.startswith("tier2_drop:")


@pytest.mark.asyncio
async def test_hold_in_gated_mode_inserts_pending_note(
    db, _allow, _no_quiet_hours, _gated_mode, _stub_judge
):
    from sqlalchemy import select

    from db.models import PendingProactiveNote
    from proactive.dispatcher import dispatch

    _stub_judge(_judge(
        action="hold",
        register=None,
        draft="stripe payout 4.2k landing tomorrow.",
    ))

    outcome = await dispatch(_event())
    assert outcome.action == "held"
    assert outcome.note_id is not None

    async with db() as s:
        rows = (await s.execute(select(PendingProactiveNote))).scalars().all()
    assert len(rows) == 1
    note = rows[0]
    assert note.status == "pending"
    assert note.topic_key == "thread-A"
    assert note.draft == "stripe payout 4.2k landing tomorrow."
    assert note.expires_at > note.created_at


@pytest.mark.asyncio
async def test_hold_supersedes_existing_pending_on_same_topic(
    db, _allow, _no_quiet_hours, _gated_mode, _stub_judge
):
    from sqlalchemy import select

    from db.models import PendingProactiveNote
    from proactive.dispatcher import dispatch

    _stub_judge(_judge(
        action="hold", register=None, draft="first version of the note."
    ))
    await dispatch(_event())

    _stub_judge(_judge(
        action="hold", register=None, draft="updated version of the note."
    ))
    await dispatch(_event(source_ref="m2"))

    async with db() as s:
        rows = (await s.execute(select(PendingProactiveNote))).scalars().all()
    statuses = sorted(r.status for r in rows)
    assert statuses == ["pending", "superseded"]
    pending = next(r for r in rows if r.status == "pending")
    assert "updated" in pending.draft


@pytest.mark.asyncio
async def test_ping_direct_in_gated_mode_ships_and_records(
    db, _allow, _no_quiet_hours, _gated_mode, _stub_judge, monkeypatch
):
    from sqlalchemy import select

    from db.models import ChatMessage, ProactivePing
    from proactive.dispatcher import dispatch

    sent = []

    class FakeChannel:
        async def send_many(self, phone, messages):
            sent.append((phone, messages))
            return ["wamid-1"]

    monkeypatch.setattr(
        "delivery.whatsapp.WhatsAppChannel",
        lambda: FakeChannel(),
    )

    _stub_judge(_judge(action="ping", register="alert"))

    outcome = await dispatch(_event())
    assert outcome.action == "shipped"
    assert outcome.ping_id is not None
    assert sent and sent[0][0] == "+1"
    assert "luca replied" in sent[0][1][0].body

    async with db() as s:
        chats = (await s.execute(select(ChatMessage))).scalars().all()
        pings = (await s.execute(select(ProactivePing))).scalars().all()
    assert len(chats) == 1
    assert chats[0].is_proactive is True
    assert chats[0].role == "assistant"
    assert len(pings) == 1
    assert pings[0].suppressed_reason is None
    assert pings[0].topic_key == "thread-A"


@pytest.mark.asyncio
async def test_ping_escalate_when_needs_tools(
    db, _allow, _no_quiet_hours, _gated_mode, _stub_judge, monkeypatch
):
    from proactive.dispatcher import dispatch

    invoked = {}

    async def fake_donna_turn(state, cfg=None):
        # Phase 2A: dispatcher runs both legacy (mode=proactive) and
        # counterfactual Tier 3 (mode=proactive_tier3) calls. Capture
        # only the legacy state so this test still asserts on the
        # _tier2_proposal hint that the legacy prompt path attaches.
        if cfg is not None and getattr(cfg, "mode", None) == "proactive":
            invoked["state"] = state
            invoked["cfg"] = cfg
        return state

    # The dispatcher imports donna_turn lazily inside _escalate_to_brain.
    # Patch the module attribute for the test.
    import donna_runtime.brain as brain
    monkeypatch.setattr(brain, "donna_turn", fake_donna_turn)

    _stub_judge(_judge(action="ping", register="alert", needs_tools=True))

    outcome = await dispatch(_event())
    assert outcome.action == "escalated"
    assert "_tier2_proposal" in invoked["state"]
    proposal = invoked["state"]["_tier2_proposal"]
    assert proposal["action"] == "ping"
    assert proposal["draft"]


@pytest.mark.asyncio
async def test_judge_failure_falls_back_to_brain_in_gated(
    db, _allow, _no_quiet_hours, _gated_mode, _stub_judge, monkeypatch
):
    from proactive.dispatcher import dispatch

    invoked = {}

    async def fake_donna_turn(state, cfg=None):
        invoked["called"] = True
        return state

    import donna_runtime.brain as brain
    monkeypatch.setattr(brain, "donna_turn", fake_donna_turn)

    _stub_judge(_judge(failed=True, failure_reason="timeout"))

    outcome = await dispatch(_event())
    assert outcome.action == "escalated"
    assert invoked.get("called") is True


@pytest.mark.asyncio
async def test_judge_failure_in_mirror_mode_logs_only(
    db, _allow, _no_quiet_hours, _mirror_mode, _stub_judge
):
    from sqlalchemy import select

    from db.models import ChatMessage
    from proactive.dispatcher import dispatch

    _stub_judge(_judge(failed=True, failure_reason="timeout"))

    outcome = await dispatch(_event())
    assert outcome.action == "mirror_logged"
    async with db() as s:
        chats = (await s.execute(select(ChatMessage))).scalars().all()
    assert chats == []


@pytest.mark.asyncio
async def test_voice_violation_em_dash_strips_and_ships(
    db, _allow, _no_quiet_hours, _gated_mode, _stub_judge, monkeypatch
):
    from sqlalchemy import select

    from db.models import ChatMessage
    from proactive.dispatcher import dispatch

    sent = []

    class FakeChannel:
        async def send_many(self, phone, messages):
            sent.append((phone, messages))
            return ["wamid-1"]

    monkeypatch.setattr(
        "delivery.whatsapp.WhatsAppChannel",
        lambda: FakeChannel(),
    )

    _stub_judge(_judge(
        action="ping",
        register="soft",
        draft="luca replied — wants friday morning.",
    ))

    outcome = await dispatch(_event())
    assert outcome.action == "shipped"
    assert sent
    body = sent[0][1][0].body
    assert "—" not in body
    assert "luca replied" in body

    async with db() as s:
        chats = (await s.execute(select(ChatMessage))).scalars().all()
    assert chats[0].content == body
