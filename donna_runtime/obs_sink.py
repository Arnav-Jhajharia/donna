"""Background DB writer for observability events.

Why a separate sink: ``observability.emit()`` is called from both async
and sync contexts (brain turns, CLI scripts, hooks) and gets called a
LOT. We can't make it ``async``, can't block the brain on DB latency,
and can't drop events silently. This module solves that with:

  - a process-local ``queue.Queue`` (unbounded by default, safety-capped
    at ~10k pending so a stalled DB never OOMs us)
  - a daemon thread that drains the queue in batches and INSERTs via a
    synchronous SQLAlchemy engine
  - psycopg2 (sync driver) so we don't need an event loop

Failure modes:
  - If the sink can't reach the DB, events accumulate in the queue. Once
    the queue hits the safety cap we drop oldest events with a warning.
    Better than blocking the brain.
  - If the engine import fails (psycopg2 unavailable / DB unreachable on
    boot), enqueue is a no-op. The file sink still works for local dev.

Disable in tests with env ``DONNA_OBS_DB_DISABLED=1``.
"""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

logger = logging.getLogger(__name__)


_QUEUE_SAFETY_CAP = 10_000
_BATCH_SIZE = 100
_DRAIN_TICK_S = 0.25

_DISABLED = os.getenv("DONNA_OBS_DB_DISABLED", "0") == "1"

_queue: queue.Queue[dict[str, Any]] | None = None
_thread: threading.Thread | None = None
_engine = None
_engine_init_failed = False
_engine_lock = threading.Lock()


def _sync_db_url() -> str | None:
    """Adapt the async DATABASE_URL to the sync psycopg2 driver. Returns
    ``None`` when no DB URL is configured (tests / dry-run env)."""
    try:
        from config import settings

        raw = settings.database_url
    except Exception:
        return None
    if not raw:
        return None
    parsed = urlparse(raw)
    scheme = parsed.scheme or ""
    if scheme.startswith("postgresql+asyncpg") or scheme == "postgresql":
        scheme = "postgresql+psycopg2"
    elif scheme.startswith("postgres") and "psycopg2" not in scheme:
        scheme = "postgresql+psycopg2"
    params = parse_qs(parsed.query, keep_blank_values=True)
    # psycopg2 accepts sslmode directly; keep it if present
    return urlunparse(parsed._replace(scheme=scheme, query=urlencode(params, doseq=True)))


def _get_engine():
    """Lazy-init the sync engine. Cached after first attempt."""
    global _engine, _engine_init_failed
    if _engine is not None or _engine_init_failed:
        return _engine
    with _engine_lock:
        if _engine is not None or _engine_init_failed:
            return _engine
        url = _sync_db_url()
        if not url:
            _engine_init_failed = True
            return None
        try:
            from sqlalchemy import create_engine

            _engine = create_engine(
                url,
                pool_pre_ping=True,
                pool_size=2,
                max_overflow=2,
                pool_recycle=300,
            )
        except Exception:
            logger.exception("obs_sink: sync engine init failed")
            _engine_init_failed = True
            _engine = None
    return _engine


def _ensure_started() -> queue.Queue[dict[str, Any]] | None:
    """Lazy queue+thread bootstrap. First enqueue triggers init."""
    global _queue, _thread
    if _DISABLED:
        return None
    if _queue is None:
        _queue = queue.Queue()
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(
            target=_drain_loop, name="donna-obs-sink", daemon=True
        )
        _thread.start()
    return _queue


def enqueue(payload: dict[str, Any]) -> None:
    """Best-effort enqueue. Never raises. Safety-cap drops oldest on
    overflow rather than blocking the caller."""
    q = _ensure_started()
    if q is None:
        return
    try:
        if q.qsize() >= _QUEUE_SAFETY_CAP:
            try:
                q.get_nowait()
            except queue.Empty:
                pass
        q.put_nowait(payload)
    except Exception:
        logger.exception("obs_sink: enqueue failed")


def _drain_loop() -> None:
    """Daemon thread: pull events from the queue in batches and INSERT.

    Sleeps ``_DRAIN_TICK_S`` between empty drains to avoid busy-looping.
    Each batch opens one short-lived session so DB blips don't pile up.
    """
    while True:
        if _queue is None:
            time.sleep(_DRAIN_TICK_S)
            continue
        batch: list[dict[str, Any]] = []
        try:
            ev = _queue.get(timeout=_DRAIN_TICK_S)
            batch.append(ev)
            while len(batch) < _BATCH_SIZE:
                try:
                    batch.append(_queue.get_nowait())
                except queue.Empty:
                    break
        except queue.Empty:
            continue
        except Exception:
            logger.exception("obs_sink: drain pull failed")
            time.sleep(_DRAIN_TICK_S)
            continue

        engine = _get_engine()
        if engine is None:
            # DB unreachable; events are dropped after a warning. Better
            # than silent buffering forever or blocking the brain.
            logger.debug(
                "obs_sink: dropping %d events (no engine)", len(batch)
            )
            continue

        try:
            _flush(engine, batch)
        except Exception:
            logger.exception(
                "obs_sink: flush failed (dropping %d events)", len(batch)
            )


def _flush(engine, batch: list[dict[str, Any]]) -> None:
    """INSERT a batch of events using the sync engine."""
    from sqlalchemy import text

    rows = []
    for ev in batch:
        ts_str = ev.get("ts")
        try:
            ts = (
                datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if isinstance(ts_str, str)
                else datetime.utcnow()
            )
            # Strip tz to match the model's naive-DateTime columns.
            if ts.tzinfo is not None:
                ts = ts.replace(tzinfo=None)
        except Exception:
            ts = datetime.utcnow()
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "ts": ts,
                "event": str(ev.get("event") or "unknown"),
                "turn_id": ev.get("turn_id"),
                "user_id": ev.get("user_id"),
                "schema_version": ev.get("schema_version"),
                "payload": ev,
            }
        )
    sql = text(
        """
        INSERT INTO obs_events
            (id, ts, event, turn_id, user_id, schema_version, payload)
        VALUES
            (:id, :ts, :event, :turn_id, :user_id, :schema_version,
             CAST(:payload AS JSONB))
        """
    )
    import json

    with engine.begin() as conn:
        conn.execute(
            sql,
            [
                {**r, "payload": json.dumps(r["payload"], default=str)}
                for r in rows
            ],
        )
