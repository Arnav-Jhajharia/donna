"""Per-case trace record + JSONL writer.

Matches the shape specified in docs/memory-stress-test-plan.md Phase 4.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class JudgeVerdict:
    passed: bool
    reason: str
    rubric: str = ""


@dataclass(frozen=True)
class StressTrace:
    """One row in ``scripts/_out/memory_stress_<run_id>.jsonl``."""

    query_id: str
    section: str
    query: str
    reply_body: str
    tools_called: tuple[str, ...]
    backends_hit: tuple[str, ...]
    expected_backends: tuple[str, ...]
    latency_ms: dict[str, int]
    tokens: dict[str, Any]
    judge: JudgeVerdict
    error: str | None = None
    trace_file: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["judge"] = asdict(self.judge)
        payload["tools_called"] = list(self.tools_called)
        payload["backends_hit"] = list(self.backends_hit)
        payload["expected_backends"] = list(self.expected_backends)
        return payload


def write_jsonl(path: Path, rows: list[StressTrace]) -> None:
    """Write traces as newline-delimited JSON. Overwrites existing file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row.to_json_dict(), sort_keys=True))
            f.write("\n")


def summarize(rows: list[StressTrace]) -> dict[str, Any]:
    """Roll up pass/fail + backend-hit rate per section for the run banner."""
    by_section: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = by_section.setdefault(row.section, {"passed": 0, "failed": 0, "error": 0})
        if row.error:
            bucket["error"] += 1
        elif row.judge.passed:
            bucket["passed"] += 1
        else:
            bucket["failed"] += 1
    total_passed = sum(b["passed"] for b in by_section.values())
    total_failed = sum(b["failed"] for b in by_section.values())
    total_error = sum(b["error"] for b in by_section.values())
    return {
        "total": len(rows),
        "passed": total_passed,
        "failed": total_failed,
        "error": total_error,
        "by_section": by_section,
    }
