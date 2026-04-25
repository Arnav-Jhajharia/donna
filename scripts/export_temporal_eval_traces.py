from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.memory.jobs.temporal_refresh import select_active_user_ids
from backend.memory.synthesis.temporal_brief import TemporalEvidence, collect_temporal_evidence

_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.\w+\b")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_PHONE_RE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{6,}\d(?!\w)")
_HANDLE_RE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{2,}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export anonymized temporal-memory traces for future eval construction."
    )
    parser.add_argument("--active-days", type=int, default=14)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--include-sandbox", action="store_true")
    parser.add_argument("--out", required=True, help="JSONL output path.")
    parser.add_argument(
        "--content-mode",
        choices=("redact", "hash", "raw"),
        default="redact",
        help="Default redacts obvious PII. raw should only be used locally for manual review.",
    )
    args = parser.parse_args()

    if args.content_mode == "raw":
        print("warning: exporting raw content. keep this file local.", file=sys.stderr)

    rows = asyncio.run(
        export_temporal_eval_traces(
            active_within_days=args.active_days,
            limit=args.limit,
            include_sandbox=args.include_sandbox,
            content_mode=args.content_mode,
        )
    )
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + ("\n" if rows else ""))
    print(f"exported {len(rows)} temporal traces to {path}")


async def export_temporal_eval_traces(
    *,
    active_within_days: int = 14,
    limit: int = 50,
    include_sandbox: bool = False,
    content_mode: str = "redact",
) -> list[dict[str, Any]]:
    user_ids = await select_active_user_ids(
        active_within_days=active_within_days,
        limit=limit,
        include_sandbox=include_sandbox,
    )
    rows: list[dict[str, Any]] = []
    for user_id in user_ids:
        evidence = await collect_temporal_evidence(user_id)
        rows.append(evidence_to_record(evidence, content_mode=content_mode))
    return rows


def evidence_to_record(evidence: TemporalEvidence, *, content_mode: str = "redact") -> dict[str, Any]:
    return {
        "schema": "donna.temporal_eval_trace.v1",
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "user_hash": anonymize_user_id(evidence.user_id),
        "timezone": evidence.timezone,
        "now": evidence.now.isoformat(timespec="seconds"),
        "facts_keys": sorted((evidence.facts or {}).keys()),
        "living_profile_keys": sorted((evidence.living_profile or {}).keys()),
        "items": [
            {
                "kind": item.kind,
                "at": item.at.isoformat(timespec="seconds") if item.at else None,
                "role": item.role,
                "status": item.status,
                "text": encode_text(item.text, mode=content_mode),
            }
            for item in (
                list(evidence.chat_messages)
                + list(evidence.observations)
                + list(evidence.open_loops)
                + list(evidence.calendar)
                + list(evidence.schedules)
            )
        ],
    }


def anonymize_user_id(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:16]


def encode_text(text: str, *, mode: str = "redact") -> str:
    if mode == "raw":
        return text
    if mode == "hash":
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    return redact_text(text)


def redact_text(text: str) -> str:
    redacted = _EMAIL_RE.sub("<email>", text)
    redacted = _URL_RE.sub("<url>", redacted)
    redacted = _PHONE_RE.sub("<phone>", redacted)
    redacted = _HANDLE_RE.sub("<handle>", redacted)
    return redacted


if __name__ == "__main__":
    main()
