"""File-backed JSON store for Attention records + tick history.

Path defaults to ~/.donna/attentions.json; override via DONNA_ATTENTION_STORE.
Single-process CLI use only — no file locking.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from donna.attention.schema import Attention, AttentionStatus


def _default_path() -> Path:
    env = os.environ.get("DONNA_ATTENTION_STORE")
    if env:
        return Path(env)
    return Path.home() / ".donna" / "attentions.json"


@dataclass(frozen=True)
class AttentionTick:
    at: str
    rendered_markdown: str
    warnings: tuple[str, ...]
    source_counts: dict[str, int]


class AttentionStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _default_path()

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"attentions": [], "ticks": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # -- CRUD ---------------------------------------------------------------

    def save(self, attention: Attention) -> Attention:
        data = self._read()
        payload = attention.model_dump(mode="json")
        replaced = False
        for i, existing in enumerate(data["attentions"]):
            if existing["id"] == payload["id"]:
                data["attentions"][i] = payload
                replaced = True
                break
        if not replaced:
            data["attentions"].append(payload)
        self._write(data)
        return attention

    def get(self, attention_id: UUID | str) -> Attention | None:
        aid = str(attention_id)
        for row in self._read()["attentions"]:
            if row["id"] == aid:
                return Attention.model_validate(row)
        return None

    def list(
        self, user_id: str | None = None, status: AttentionStatus | None = None
    ) -> list[Attention]:
        out: list[Attention] = []
        for row in self._read()["attentions"]:
            a = Attention.model_validate(row)
            if user_id and str(a.user_id) != str(user_id):
                continue
            if status and a.status is not status:
                continue
            out.append(a)
        return out

    def update_status(
        self, attention_id: UUID | str, status: AttentionStatus
    ) -> Attention | None:
        a = self.get(attention_id)
        if a is None:
            return None
        updated = a.model_copy(update={"status": status})
        self.save(updated)
        return updated

    # -- Ticks --------------------------------------------------------------

    def append_tick(self, attention_id: UUID | str, tick: AttentionTick) -> None:
        data = self._read()
        key = str(attention_id)
        data["ticks"].setdefault(key, []).append(
            {
                "at": tick.at,
                "rendered_markdown": tick.rendered_markdown,
                "warnings": list(tick.warnings),
                "source_counts": tick.source_counts,
            }
        )
        # Bump update_count + last_update_at on the Attention itself.
        for i, row in enumerate(data["attentions"]):
            if row["id"] == key:
                row["update_count"] = int(row.get("update_count", 0)) + 1
                row["last_update_at"] = tick.at
                data["attentions"][i] = row
                break
        self._write(data)

    def ticks(self, attention_id: UUID | str) -> list[AttentionTick]:
        data = self._read()
        rows = data["ticks"].get(str(attention_id), [])
        return [
            AttentionTick(
                at=r["at"],
                rendered_markdown=r["rendered_markdown"],
                warnings=tuple(r.get("warnings", [])),
                source_counts=r.get("source_counts", {}),
            )
            for r in rows
        ]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
