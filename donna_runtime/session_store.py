"""Claude Agent SDK session-id persistence.

Two backends live side-by-side:

- **File backend** (`resolve_session_id`, `save_user_session`, `load_user_sessions`)
  for the local CLI in donna.py. Sync, single-process, no DB dependency.
- **DB backend** (`resolve_session_id_db`, `save_user_session_db`) used by the
  WhatsApp production path in donna_runtime.brain. Async, Postgres-backed,
  survives redeploys and shares across replicas.

The SDK resumes a conversation from its session_id; this store just remembers
which session_id to resume for a given user_id. No message history is stored
here — that lives inside the SDK session.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UserSessionRecord:
    user_id: str
    session_id: str
    updated_at: str


# ── File backend (CLI) ───────────────────────────────────────────────────────
def load_user_sessions(path: Path) -> dict[str, UserSessionRecord]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    return {
        user_id: UserSessionRecord(
            user_id=user_id,
            session_id=record["session_id"],
            updated_at=record["updated_at"],
        )
        for user_id, record in raw.items()
    }


def resolve_session_id(
    *,
    explicit_session_id: str | None,
    user_id: str | None,
    store_path: Path,
    new_session: bool = False,
) -> str | None:
    if new_session:
        return None
    if explicit_session_id:
        return explicit_session_id
    if not user_id:
        return None
    return load_user_sessions(store_path).get(user_id, UserSessionRecord(user_id, "", "")).session_id or None


def save_user_session(path: Path, user_id: str, session_id: str) -> None:
    sessions = load_user_sessions(path)
    sessions[user_id] = UserSessionRecord(
        user_id=user_id,
        session_id=session_id,
        updated_at=datetime.now().isoformat(),
    )
    path.write_text(json.dumps({key: asdict(value) for key, value in sessions.items()}, indent=2) + "\n")


# ── DB backend (production / WhatsApp path) ──────────────────────────────────
def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def resolve_session_id_db(
    *,
    explicit_session_id: str | None,
    user_id: str | None,
    new_session: bool = False,
) -> str | None:
    """Look up the last Claude session_id for this user_id in Postgres."""
    if new_session:
        return None
    if explicit_session_id:
        return explicit_session_id
    if not user_id:
        return None
    try:
        from sqlalchemy import select

        from db.models import UserSession
        from db.session import async_session

        async with async_session() as session:
            result = await session.execute(
                select(UserSession.session_id).where(UserSession.user_id == user_id)
            )
            row = result.scalar_one_or_none()
            return row or None
    except Exception:
        logger.exception("resolve_session_id_db failed for user=%s", (user_id or "")[:8])
        return None


async def save_user_session_db(user_id: str, session_id: str) -> None:
    """Upsert user_id → session_id in Postgres. Safe to call from any replica."""
    if not user_id or not session_id:
        return
    try:
        from sqlalchemy.dialects.postgresql import insert

        from db.models import UserSession
        from db.session import async_session

        now = _utcnow()
        stmt = insert(UserSession).values(
            user_id=user_id, session_id=session_id, updated_at=now,
        ).on_conflict_do_update(
            index_elements=[UserSession.user_id],
            set_={"session_id": session_id, "updated_at": now},
        )
        async with async_session() as session:
            await session.execute(stmt)
            await session.commit()
    except Exception:
        logger.exception("save_user_session_db failed for user=%s", (user_id or "")[:8])
