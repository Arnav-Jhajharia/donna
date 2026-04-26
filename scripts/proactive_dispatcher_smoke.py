"""Smoke test the Tier 2 proactive dispatcher and the autonomous spawners.

Usage:

    # Mirror mode (default) — Tier 2 logs but does not ship.
    python scripts/proactive_dispatcher_smoke.py

    # Gated mode — dispatcher actually ships drafts / writes pending notes.
    DONNA_PROACTIVE_TIERED=1 python scripts/proactive_dispatcher_smoke.py

    # Calendar spawner walk-through.
    DONNA_PROACTIVE_TIERED=1 \
      python scripts/proactive_dispatcher_smoke.py --spawn-calendar

    # Observation spawner walk-through.
    DONNA_PROACTIVE_TIERED=1 \
      python scripts/proactive_dispatcher_smoke.py --spawn-observation

The script:
  - Spins up an in-memory sqlite DB and seeds a user.
  - Stubs the Haiku call so no API key is required.
  - With ``--spawn-calendar``: ingests a synthetic exam event, runs the
    spawner, fires the schedule worker tick, drives the dispatcher.
  - With ``--spawn-observation``: writes a synthetic drinking
    observation, runs the spawner, fires the schedule worker tick,
    drives the dispatcher.
  - Default: builds a synthetic ``ProactiveEvent`` and walks it through
    ``proactive.dispatcher.dispatch``.
  - Prints the resulting WhatsApp messages so you can eyeball.

Prerequisite: just run inside the project venv. No external services touched.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

# Allow running as ``python scripts/proactive_dispatcher_smoke.py`` from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def _patch_db():
    """Set up an in-memory sqlite DB and patch the canonical session factories."""
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )
    from sqlalchemy.ext.compiler import compiles

    @compiles(JSONB, "sqlite")
    def _sqlite_jsonb(type_, compiler, **kw):  # type: ignore[no-untyped-def]
        return "JSON"

    from db.models import Base, User

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with sm() as s:
            s.add(
                User(
                    id="u1",
                    phone="+15555550100",
                    timezone="Asia/Singapore",
                    last_active_at=datetime.utcnow(),
                )
            )
            await s.commit()
        return sm

    sm = asyncio.get_event_loop().run_until_complete(setup())

    import backend.db.session as backend_session
    import db.session as root_session

    root_session.async_session = sm
    backend_session.async_session = sm
    return engine


def _isolate_attention_stores() -> None:
    """Point the file-backed AttentionStore + spawner ledger at temp files.

    Keeps the smoke run from polluting the dev ~/.donna/ directory.
    """
    import os

    tmp = Path(tempfile.mkdtemp(prefix="donna-smoke-"))
    os.environ["DONNA_ATTENTION_STORE"] = str(tmp / "attentions.json")
    os.environ["DONNA_SPAWNER_DEDUP_PATH"] = str(tmp / "spawner_dedup.json")


def _stub_haiku() -> list:
    """Stub the proactive judge's Haiku call. Returns the sent-message log."""
    from proactive import judge as judge_module
    from proactive.judge import JudgeOutput

    parsed = JudgeOutput(
        action="ping",
        register="alert",
        draft="luca replied. wants thursday 4pm or friday morning for the dd call.",
        tie_in=["antler-dd-call"],
        needs_tools=False,
        reasoning="active loop, person matters, requires same-day decision",
    )

    async def fake_call(*, system_prompt, user_message):
        return parsed, '{"action":"ping"}'

    judge_module._call_haiku = fake_call  # type: ignore[attr-defined]

    async def empty(_user_id):
        return ""

    judge_module._load_user_model_block = empty  # type: ignore[attr-defined]
    judge_module._load_today_block = empty  # type: ignore[attr-defined]
    judge_module._load_recent_chat = empty  # type: ignore[attr-defined]

    sent: list = []

    class FakeChannel:
        async def send_many(self, phone, messages):
            sent.append((phone, messages))
            return ["wamid-fake-1"]

    import delivery.whatsapp as wa

    wa.WhatsAppChannel = lambda: FakeChannel()  # type: ignore[assignment]
    return sent


async def _run_default(sent: list) -> None:
    msg = SimpleNamespace(
        gmail_message_id="m_fake_1",
        thread_id="t_fake_1",
        from_address="luca@antler.co",
        from_name="Luca",
        subject="thursday or friday?",
        body_text="hey, can we lock in thursday 4pm or friday morning for the dd call?",
        snippet="lock in dd call",
        is_important=True,
        is_starred=False,
        is_sent=False,
    )
    score = SimpleNamespace(score=0.7, signals=["biography_relationship"])

    from proactive.sources.email import make_event
    from proactive.dispatcher import dispatch, is_tiered_active

    event = make_event("u1", msg, score)
    print("---")
    print("event:", event)
    print("tiered mode:", is_tiered_active())
    print("---")

    outcome = await dispatch(event)
    print("---")
    print("outcome:", outcome)
    print("messages sent over WhatsApp:", sent)
    print("---")


async def _drive_one_due_schedule(sent: list) -> None:
    """Pull the most-due DonnaSchedule row and fire it through the worker."""
    from sqlalchemy import select

    from backend.db.models import DonnaSchedule
    from backend.db.session import async_session
    from backend.memory.jobs.schedule_worker import run_once

    async with async_session() as session:
        rows = (
            await session.execute(
                select(DonnaSchedule)
                .where(DonnaSchedule.fired.is_(False))
            )
        ).scalars().all()
        for r in rows:
            r.fire_at = datetime.utcnow() - timedelta(seconds=1)
        await session.commit()

    fired = await run_once()
    print(f"schedule_worker fired {fired} schedules")
    print("messages sent over WhatsApp:", sent)


async def _spawn_calendar_run(sent: list) -> None:
    from backend.integrations.calendar_ingest import ingest_calendar_event

    start_utc = datetime.now(timezone.utc) + timedelta(hours=20)
    event = {
        "id": "smoke-event-1",
        "summary": "midterm exam",
        "start": {"dateTime": start_utc.isoformat()},
        "end": {"dateTime": (start_utc + timedelta(hours=2)).isoformat()},
    }
    print("---")
    print(f"ingesting calendar event: {event['summary']} at {event['start']['dateTime']}")
    await ingest_calendar_event("u1", event)

    from sqlalchemy import select

    from backend.db.models import AttentionRow, DonnaSchedule
    from backend.db.session import async_session

    async with async_session() as s:
        attentions = (await s.execute(select(AttentionRow))).scalars().all()
        schedules = (
            await s.execute(select(DonnaSchedule).where(DonnaSchedule.fired.is_(False)))
        ).scalars().all()
    print(f"attentions persisted: {len(attentions)}")
    for a in attentions:
        print(f"  - {a.id} title={a.title!r} status={a.status} origin={a.origin}")
    print(f"pending schedules: {len(schedules)}")
    for s in schedules:
        print(f"  - {s.id} fire_at={s.fire_at} body={s.context!r}")

    print("---")
    print("forcing schedules due → invoking schedule_worker._fire_due")
    await _drive_one_due_schedule(sent)


async def _spawn_observation_run(sent: list) -> None:
    """Insert a drinking observation in the evening window, run spawner."""
    from backend.memory.tools.log_observation import log_observation

    print("---")
    print("logging drinking_event observation")
    res = await log_observation(
        user_id="u1",
        type="drinking_event",
        fields={"drinks": 5},
        raw="rough night, drank too much",
        event_time=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
    )
    print(f"observation result: {res}")

    obs_id = (res.get("payload") or {}).get("id") if isinstance(res, dict) else None
    if not obs_id:
        print("smoke: observation write failed, skipping spawner step")
        return

    # Manually drive the spawner. Patch the evening-window check to True
    # so the smoke is wall-clock independent.
    from sqlalchemy import select

    from backend.db.models import Observation
    from backend.db.session import async_session
    from proactive.spawners import observation as observation_spawner

    observation_spawner._is_evening = lambda *_a, **_kw: True  # type: ignore[assignment]

    async with async_session() as s:
        row = (
            await s.execute(select(Observation).where(Observation.id == obs_id))
        ).scalar_one()
    ids = await observation_spawner.maybe_spawn(row, "u1")
    print(f"spawner created attentions: {ids}")

    from backend.db.models import AttentionRow, DonnaSchedule

    async with async_session() as s:
        attentions = (await s.execute(select(AttentionRow))).scalars().all()
        schedules = (
            await s.execute(select(DonnaSchedule).where(DonnaSchedule.fired.is_(False)))
        ).scalars().all()
    print(f"attentions persisted: {len(attentions)}")
    for a in attentions:
        print(f"  - {a.id} title={a.title!r} status={a.status} origin={a.origin}")
    print(f"pending schedules: {len(schedules)}")
    for s in schedules:
        print(f"  - {s.id} fire_at={s.fire_at} body={s.context!r}")

    print("---")
    print("forcing schedules due → invoking schedule_worker._fire_due")
    await _drive_one_due_schedule(sent)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spawn-calendar",
        action="store_true",
        help="Run the calendar spawner end-to-end smoke instead of the default email path.",
    )
    parser.add_argument(
        "--spawn-observation",
        action="store_true",
        help="Run the observation spawner end-to-end smoke instead of the default email path.",
    )
    args = parser.parse_args()

    _isolate_attention_stores()
    _patch_db()
    sent = _stub_haiku()

    loop = asyncio.get_event_loop()
    if args.spawn_calendar:
        loop.run_until_complete(_spawn_calendar_run(sent))
    elif args.spawn_observation:
        loop.run_until_complete(_spawn_observation_run(sent))
    else:
        loop.run_until_complete(_run_default(sent))


if __name__ == "__main__":
    main()
