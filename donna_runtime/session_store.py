from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class UserSessionRecord:
    user_id: str
    session_id: str
    updated_at: str


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
