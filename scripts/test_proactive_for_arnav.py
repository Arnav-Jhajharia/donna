"""End-to-end proactive surface test against Arnav's real user.

Runs each of the six proactive surfaces in sequence, against the live DB,
calling real Haiku + real Composio + real WhatsApp where applicable.
Prints PASS / SUPPRESSED / FAIL / SKIP with telemetry for each.

Usage:
    DONNA_PROACTIVE_TIERED=1 DONNA_PROACTIVE_OFFER_ACTIVE=1 \\
    DONNA_SPAWNERS=1 LANGSMITH_TRACING=true \\
    python scripts/test_proactive_for_arnav.py

The in-turn capture test (#6) stubs WhatsApp to avoid a real outbound;
all others ship through whatever the dispatcher decides. Each test is
idempotent enough to re-run, but proactive_pings rows accumulate.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

USER_ID = "986cbc94-ef35-4eb4-9d1f-7efbc76949e9"
PHONE = "919875486045"


def _h(title: str) -> None:
    print()
    print("=" * 64)
    print(f"  {title}")
    print("=" * 64)


def _v(label: str, value) -> None:
    print(f"  {label}: {value}")


def _verdict(tag: str, *lines: str) -> None:
    print(f"  >>> {tag}")
    for line in lines:
        print(f"      {line}")


async def test_1_email_path() -> None:
    _h("TEST 1 — gmail email through dispatcher")
    from backend.integrations.composio_client import NormalizedGmailMessage
    from backend.integrations.proactive_email_trigger import maybe_surface_email

    msg = NormalizedGmailMessage(
        gmail_message_id=f"test-email-{uuid.uuid4().hex[:12]}",
        thread_id=f"t-test-{uuid.uuid4().hex[:8]}",
        from_address="founder-test@example.com",
        from_name="Test Founder",
        subject="fundraise update — quick decision needed",
        snippet="we need to lock in the term sheet before friday",
        body_text=(
            "hey arnav, the term sheet from antler is ready. "
            "can we hop on a call thursday 4pm or friday morning to lock it in? "
            "valuation is where we wanted it, terms are clean."
        ),
        labels=["IMPORTANT", "INBOX"],
        is_important=True,
        is_starred=False,
        is_sent=False,
        to_addresses=[PHONE],
        cc_addresses=[],
        internal_date=int(time.time() * 1000),
    )
    _v("from", f"{msg.from_name} <{msg.from_address}>")
    _v("subject", msg.subject)
    _v("scoring signals", "is_important=True (+0.5), expected score >= 0.5")
    try:
        await maybe_surface_email(USER_ID, msg)
        _verdict(
            "DISPATCHED",
            f"message_id={msg.gmail_message_id}",
            f"thread_id={msg.thread_id}",
            "check proactive_pings for fired/suppressed verdict",
        )
    except Exception as exc:
        _verdict("FAIL", f"{type(exc).__name__}: {exc}")


async def test_2_scheduled_attention_fire() -> None:
    _h("TEST 2 — scheduled attention fire through dispatcher")
    from sqlalchemy import select

    from backend.db.session import async_session
    from db.models import DonnaSchedule

    sched_id = f"test-sched-{uuid.uuid4().hex[:12]}"
    fake_attention_id = f"test-attn-{uuid.uuid4().hex[:12]}"
    fire_at = datetime.utcnow() - timedelta(seconds=1)
    async with async_session() as s:
        s.add(
            DonnaSchedule(
                id=sched_id,
                user_id=USER_ID,
                phone=PHONE,
                fire_at=fire_at,
                origin="donna",
                attention_id=fake_attention_id,
                recurrence_meta={
                    "cadence_type": "one_shot",
                    "cadence_params": {},
                    "user_tz": "Asia/Singapore",
                    "question": "stretch break, you've been at the desk a while",
                },
                context={
                    "messages": [
                        {"type": "text", "body": "stretch break"},
                    ],
                    "timezone": "Asia/Singapore",
                    "attention_id": fake_attention_id,
                },
                fired=False,
                status="pending",
            )
        )
        await s.commit()
    _v("inserted schedule", sched_id)
    _v("attention_id (fabricated)", fake_attention_id)
    _v("fire_at", fire_at.isoformat() + " (already due)")

    from backend.memory.jobs import schedule_worker

    attempted = await schedule_worker.run_once(batch_size=5)
    async with async_session() as s:
        row = (
            await s.execute(
                select(DonnaSchedule).where(DonnaSchedule.id == sched_id)
            )
        ).scalar_one()
    _verdict(
        "RAN",
        f"attempted={attempted}",
        f"row.status={row.status} fired={row.fired}",
        f"last_error={row.last_error or '-'}",
    )


async def test_3_shadow_offered_active_push() -> None:
    _h("TEST 3 — shadow → offered active push (dispatcher path)")
    from proactive.dispatcher import dispatch
    from proactive.events import ProactiveEvent

    event = ProactiveEvent(
        user_id=USER_ID,
        source="attention_offer",
        source_ref=f"test-offer-{uuid.uuid4().hex[:12]}",
        topic_key=f"test-offer-topic-{uuid.uuid4().hex[:8]}",
        payload={
            "title": "track sleep",
            "card": "tally",
            "subject_name": "sleep",
            "rationale": "you've mentioned waking up tired three times this week",
            "phone": PHONE,
        },
        signals={"promotion_hits": 2, "source_counts": {}},
    )
    _v("source", event.source)
    _v("topic_key", event.topic_key)
    try:
        outcome = await dispatch(event)
        _verdict(
            "DISPATCHED",
            f"action={outcome.action}",
            f"reason={outcome.reason}",
            f"draft={(outcome.draft or '')[:120] or '-'}",
        )
    except Exception as exc:
        _verdict("FAIL", f"{type(exc).__name__}: {exc}")


async def test_4_calendar_spawner() -> None:
    _h("TEST 4 — calendar event → spawner → LIVE attentions")
    from types import SimpleNamespace

    event_id = f"test-cal-{uuid.uuid4().hex[:12]}"
    starts = datetime.now(timezone.utc) + timedelta(hours=18)
    event = SimpleNamespace(
        id=event_id,
        user_id=USER_ID,
        title="midterm exam — algorithms",
        location="lecture hall 3b",
        category=None,
        google_event_id=event_id,
        start_time=starts.replace(tzinfo=None),
        end_time=(starts + timedelta(hours=2)).replace(tzinfo=None),
    )
    _v("synthetic CalendarEntry", event_id)
    _v("title", "midterm exam — algorithms")
    _v("start_time", starts.isoformat())

    try:
        from proactive.spawners import calendar as calendar_spawner

        spawned = await calendar_spawner.maybe_spawn(event, USER_ID)
        _verdict(
            "RAN",
            f"attentions spawned: {len(spawned) if spawned else 0}",
            f"ids: {spawned}" if spawned else "none (event may have been below stakes threshold)",
        )
    except Exception as exc:
        _verdict("FAIL", f"{type(exc).__name__}: {exc}")


async def test_5_observation_spawner() -> None:
    _h("TEST 5 — observation → spawner → LIVE attention")
    from types import SimpleNamespace

    # Pick a UTC time that maps to evening in user-local Asia/Singapore
    # (UTC+8). 14:00 UTC = 22:00 SGT, well inside the drinking_event window.
    obs_time = datetime.utcnow().replace(hour=14, minute=0, second=0, microsecond=0)
    obs_id = f"test-obs-{uuid.uuid4().hex[:12]}"
    obs = SimpleNamespace(
        id=obs_id,
        user_id=USER_ID,
        type="drinking_event",
        event_time=obs_time,
        tags={},
        fields={"amount": "heavy", "context": "founder dinner"},
    )
    _v("synthetic Observation", obs_id)
    _v("type", obs.type)
    _v("event_time (UTC)", obs_time.isoformat())

    try:
        from proactive.spawners import observation as obs_spawner

        spawned = await obs_spawner.maybe_spawn(obs, USER_ID)
        _verdict(
            "RAN",
            f"attentions spawned: {len(spawned) if spawned else 0}",
            f"ids: {spawned}" if spawned else "none",
        )
    except Exception as exc:
        _verdict("FAIL", f"{type(exc).__name__}: {exc}")


async def test_6_in_turn_capture() -> None:
    _h("TEST 6 — in-turn intention capture via brain")
    # Stub WhatsApp so the brain's send_burst doesn't actually ping Arnav
    # (this test is about the prompt-driven attend call, not delivery).
    sent = []

    class FakeChannel:
        async def send_many(self, phone, messages):
            sent.append((phone, messages))
            return ["wamid-test"]

    import delivery.whatsapp as wa
    original_cls = wa.WhatsAppChannel
    wa.WhatsAppChannel = lambda: FakeChannel()  # type: ignore[assignment]
    try:
        from donna_runtime.brain import donna_turn
        from donna_runtime.config import DonnaAgentConfig

        utterance = "I have a midterm exam tomorrow at 11am, please make sure I'm up by 8"
        _v("utterance", utterance)
        cfg = DonnaAgentConfig(mode="reactive", user_id=USER_ID, user_phone=PHONE)
        state = {
            "user_id": USER_ID,
            "raw_input": utterance,
            "user_message": utterance,
            "phone": PHONE,
            "_user_timezone": "Asia/Singapore",
        }
        result = await donna_turn(state, cfg)
        outbound = result.get("_outbound") or []
        trace = result.get("_turn_trace")
        tool_calls = []
        if trace is not None:
            for tc in getattr(trace, "tool_calls", []) or []:
                name = getattr(tc, "name", None) or (tc.get("name") if isinstance(tc, dict) else None)
                if name:
                    tool_calls.append(name)
        attend_calls = [n for n in tool_calls if n == "attend"]
        _verdict(
            "RAN",
            f"tool_calls={tool_calls}",
            f"attend tool calls: {len(attend_calls)} (expected >= 1 if prompt change is in effect)",
            f"outbound bursts (stubbed): {len(outbound)}",
        )
        if outbound:
            for m in outbound[:2]:
                body = getattr(m, "body", str(m))[:140]
                print(f"      reply: {body}")
    except Exception as exc:
        _verdict("FAIL", f"{type(exc).__name__}: {exc}")
    finally:
        wa.WhatsAppChannel = original_cls  # type: ignore[assignment]


async def test_proactive_status_dump() -> None:
    _h("FINAL — proactive_status snapshot for Arnav")
    # Re-use the existing CLI script's logic by importing it.
    from scripts.proactive_status import main as status_main

    await status_main(USER_ID, hours=1)


async def _print_env_snapshot() -> None:
    flags = [
        "DONNA_PROACTIVE_TIERED",
        "DONNA_PROACTIVE_OFFER_ACTIVE",
        "DONNA_SPAWNERS",
        "LANGSMITH_TRACING",
    ]
    print("env flag snapshot:")
    for f in flags:
        print(f"  {f}={os.environ.get(f, '<unset>')}")
    print(f"target user_id: {USER_ID}")
    print(f"target phone:   {PHONE}")
    print()


async def main() -> None:
    await _print_env_snapshot()
    await test_1_email_path()
    await test_2_scheduled_attention_fire()
    await test_3_shadow_offered_active_push()
    await test_4_calendar_spawner()
    await test_5_observation_spawner()
    await test_6_in_turn_capture()
    await test_proactive_status_dump()


if __name__ == "__main__":
    asyncio.run(main())
