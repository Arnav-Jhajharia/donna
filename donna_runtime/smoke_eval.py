"""Smoke eval runner.

Runs the 15-item smoke fixtures against Donna's live BRAIN loop and reports
pass/fail per fixture. Intended for manual invocation + baseline tracking,
not pytest (the live LLM call is slow and needs ANTHROPIC_API_KEY).

Usage:
    python -m donna_runtime.smoke_eval [--user-id UID] [--ids id1,id2]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from donna_runtime.config import DonnaAgentConfig
from donna_runtime.runner import donna_turn
from donna_runtime.smoke_eval_fixtures import SMOKE_FIXTURES, SmokeFixture
from donna_runtime.tracing import TurnTrace

logger = logging.getLogger(__name__)


@dataclass
class FixtureResult:
    fixture_id: str
    passed: bool
    reasons: list[str] = field(default_factory=list)
    terminal_tool: str | None = None
    tool_calls: list[str] = field(default_factory=list)
    reply_bodies: list[str] = field(default_factory=list)
    media_types: list[str] = field(default_factory=list)
    category: str = "voice"

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "passed": self.passed,
            "reasons": self.reasons,
            "terminal_tool": self.terminal_tool,
            "tool_calls": self.tool_calls,
            "reply_bodies": self.reply_bodies,
            "media_types": self.media_types,
            "category": self.category,
        }


def _call_name(call: dict[str, Any]) -> str:
    return str(call.get("tool") or call.get("name") or "")


def _terminal_tool(trace: TurnTrace) -> str | None:
    for call in reversed(trace.to_dict().get("tool_calls", [])):
        name = _call_name(call)
        if name.endswith("send_burst"):
            return "send_burst"
    return None


def _tool_names(trace: TurnTrace) -> list[str]:
    return [_call_name(c) for c in trace.to_dict().get("tool_calls", [])]


def _extract_reply_bodies(trace: TurnTrace) -> list[str]:
    bodies: list[str] = []
    for call in trace.to_dict().get("tool_calls", []):
        if not _call_name(call).endswith("send_burst"):
            continue
        messages = call.get("inputs", {}).get("messages", [])
        for m in messages:
            if isinstance(m, str):
                bodies.append(m)
            elif isinstance(m, dict):
                body = m.get("body") or m.get("caption")
                if isinstance(body, str):
                    bodies.append(body)
    return bodies


def _extract_media_types(trace: TurnTrace) -> list[str]:
    """Widget types emitted by send_burst in the order they appear."""
    types: list[str] = []
    for call in trace.to_dict().get("tool_calls", []):
        if not _call_name(call).endswith("send_burst"):
            continue
        messages = call.get("inputs", {}).get("messages", [])
        for m in messages:
            if isinstance(m, str):
                types.append("text")
            elif isinstance(m, dict):
                t = m.get("type")
                if isinstance(t, str):
                    types.append(t)
    return types


def _evaluate(fixture: SmokeFixture, trace: TurnTrace) -> FixtureResult:
    result = FixtureResult(fixture_id=fixture.id, passed=True, category=fixture.category)
    result.terminal_tool = _terminal_tool(trace)
    result.tool_calls = _tool_names(trace)
    result.reply_bodies = _extract_reply_bodies(trace)
    result.media_types = _extract_media_types(trace)

    if result.terminal_tool != fixture.expected_terminal:
        result.passed = False
        result.reasons.append(
            f"expected terminal {fixture.expected_terminal}, got {result.terminal_tool}"
        )

    for required in fixture.expected_tools:
        if not any(required in name for name in result.tool_calls):
            result.passed = False
            result.reasons.append(f"missing expected tool {required}")

    for banned in fixture.banned_tools:
        if any(banned in name for name in result.tool_calls):
            result.passed = False
            result.reasons.append(f"called banned tool {banned}")

    joined = " ".join(result.reply_bodies)
    for phrase in fixture.banned_phrases:
        if phrase.lower() in joined.lower():
            result.passed = False
            result.reasons.append(f"banned phrase in reply: {phrase!r}")

    word_count = sum(len(b.split()) for b in result.reply_bodies)
    if word_count > fixture.max_reply_words:
        result.passed = False
        result.reasons.append(
            f"reply too long: {word_count} > {fixture.max_reply_words}"
        )

    for required_type in fixture.expected_media:
        if required_type not in result.media_types:
            result.passed = False
            result.reasons.append(
                f"expected media {required_type!r} not in burst (got {result.media_types})"
            )

    for forbidden_type in fixture.forbidden_media:
        if forbidden_type in result.media_types:
            result.passed = False
            result.reasons.append(
                f"forbidden media {forbidden_type!r} appeared in burst"
            )

    return result


async def run_single(
    fixture: SmokeFixture, user_id: str, config: DonnaAgentConfig
) -> FixtureResult:
    cfg = config.__class__(
        **{**config.__dict__, "user_id": user_id, "chat_already_persisted": True}
    )
    trace = await donna_turn(fixture.message, config=cfg)
    return _evaluate(fixture, trace)


async def run_all(
    user_id: str, ids: tuple[str, ...] | None = None
) -> list[FixtureResult]:
    config = DonnaAgentConfig()
    fixtures = [
        f for f in SMOKE_FIXTURES if not ids or f.id in ids
    ]
    results: list[FixtureResult] = []
    for fx in fixtures:
        logger.info("running fixture %s: %s", fx.id, fx.message[:60])
        try:
            results.append(await run_single(fx, user_id, config))
        except Exception as exc:
            logger.exception("fixture %s crashed", fx.id)
            r = FixtureResult(fixture_id=fx.id, passed=False)
            r.reasons.append(f"crash: {exc}")
            results.append(r)
    return results


def _print_report(results: list[FixtureResult]) -> int:
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print(f"\n=== smoke eval: {passed}/{total} passed ===\n")

    by_category: dict[str, list[FixtureResult]] = {}
    for r in results:
        by_category.setdefault(r.category, []).append(r)
    print("by category:")
    for cat, cat_results in sorted(by_category.items()):
        cat_pass = sum(1 for r in cat_results if r.passed)
        print(f"  {cat:<16} {cat_pass}/{len(cat_results)}")
    print()

    for r in results:
        mark = "PASS" if r.passed else "FAIL"
        print(f"[{mark}] {r.fixture_id}")
        if not r.passed:
            for reason in r.reasons:
                print(f"    - {reason}")
            if r.terminal_tool:
                print(f"    terminal: {r.terminal_tool}")
            if r.tool_calls:
                print(f"    tools: {r.tool_calls}")
            if r.media_types:
                print(f"    media: {r.media_types}")
    return 0 if passed == total else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Donna smoke eval")
    parser.add_argument("--user-id", default="smoke-eval-user")
    parser.add_argument(
        "--ids", default="", help="Comma-separated fixture ids to run (default: all)"
    )
    parser.add_argument(
        "--output", default="", help="Optional JSON output path for results"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ids = tuple(s.strip() for s in args.ids.split(",") if s.strip())
    results = asyncio.run(run_all(args.user_id, ids or None))

    if args.output:
        Path(args.output).write_text(
            json.dumps([r.to_dict() for r in results], indent=2, default=str)
        )

    return _print_report(results)


if __name__ == "__main__":
    raise SystemExit(main())
