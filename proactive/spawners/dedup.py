"""File-backed dedup ledger for spawned attentions.

Each spawn records ``(dedup_key, attention_id, created_at_iso)``. Before
spawning, callers check ``has_spawned(dedup_key)`` — if True, skip.

Why a file rather than a postgres table: the existing AttentionStore is
file-backed and rewriting attention descriptions is unreliable for
dedup matching. Adding a postgres table would require a migration
which is explicitly out of scope. A small JSON file in the same
directory mirrors the existing AttentionStore behaviour and is
trivially monkeypatchable in tests.

Path defaults to ~/.donna/spawner_dedup.json; override via
``DONNA_SPAWNER_DEDUP_PATH`` env or by passing ``path=`` directly.
Single-process; no file locking. Acceptable for v1 — spawners run
inline with calendar ingest / observation writes which are already
serialised on the writer side.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def _default_path() -> Path:
    env = os.environ.get("DONNA_SPAWNER_DEDUP_PATH")
    if env:
        return Path(env)
    return Path.home() / ".donna" / "spawner_dedup.json"


@dataclass(frozen=True)
class DedupEntry:
    dedup_key: str
    attention_id: str | None
    created_at: str


class SpawnerDedupLedger:
    """File-backed ledger of spawn dedup keys.

    ``record`` and ``has_spawned`` are the only entry points the
    spawners use. ``forget`` exists for tests / admin replays.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _default_path()
        self._lock = threading.Lock()

    def _read(self) -> dict[str, dict[str, str]]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8")) or {}
        except json.JSONDecodeError:
            return {}

    def _write(self, data: dict[str, dict[str, str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def has_spawned(self, dedup_key: str) -> bool:
        if not dedup_key:
            return False
        with self._lock:
            return dedup_key in self._read()

    def record(self, dedup_key: str, attention_id: str | None) -> None:
        if not dedup_key:
            return
        with self._lock:
            data = self._read()
            data[dedup_key] = {
                "attention_id": attention_id or "",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._write(data)

    def forget(self, dedup_keys: Iterable[str]) -> None:
        keys = [k for k in dedup_keys if k]
        if not keys:
            return
        with self._lock:
            data = self._read()
            for k in keys:
                data.pop(k, None)
            self._write(data)

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._read().keys())
