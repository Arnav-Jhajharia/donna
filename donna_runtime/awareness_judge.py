"""LLM-as-judge for the awareness arc.

Per-turn scoring against the `should_catch` / `should_ignore` hints in each
MultiTurn. Returns structured JSON the multiturn runner attaches to each
TurnResult and writes into the JSONL trace.

Uses Haiku 4.5 for judging (cheap, good enough for rubric-based grading).
Scale the rubric or swap to Sonnet if grading precision becomes a gap.

Schema per judged turn:
    {
      "turn_id": str,
      "awareness_score": 1-5,       # did she catch what she should have
      "discipline_score": 1-5,      # did she avoid over-reaching on ambient
      "voice_score": 1-5,           # did her reply match the user's register
      "caught": [str, ...],         # from should_catch, evidence of catching
      "missed": [str, ...],         # from should_catch, no evidence of catching
      "over_reached": [str, ...],   # from should_ignore, she acted anyway
      "notes": str,                 # one-line human-readable judgment
    }
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_JUDGE_MODEL = os.getenv("DONNA_JUDGE_MODEL", "claude-haiku-4-5-20251001")

_RUBRIC = """You are grading one turn of a conversation between a user and Donna,
a WhatsApp-native personal AI. Donna's voice is lowercase, clipped, no em dashes,
no empathy theater. She calls tools to log observations, track open loops,
schedule reminders, recall memory. She ends every turn with a send_burst.

You're evaluating three dimensions for this single turn:

1. AWARENESS (1-5): did Donna catch the data, entities, and identity signals
   buried in the user's message? The fixture lists `should_catch` items — the
   evidence can appear in: (a) a tool call with matching args, or (b) the
   reply text acknowledging the signal.

2. DISCIPLINE (1-5): did she avoid over-reaching? The fixture lists
   `should_ignore` items — things that are vents, tangents, or ambient
   chatter that should NOT trigger a log/track/schedule. Over-reaching is
   calling a tool on something the fixture explicitly marks as ambient.

3. VOICE (1-5): did her reply register match the user's? Lowercase + clipped
   on casual turns, minimal on ambient ("k" / "noted"), one-line wit on
   tangents. Wrong: long paragraphs, "I understand", "Great question",
   empathy theater, corporate flatten, em dashes, semicolons.

Return STRICT JSON only, no prose before or after:
{
  "awareness_score": 1-5,
  "discipline_score": 1-5,
  "voice_score": 1-5,
  "caught": ["which should_catch items were demonstrably caught"],
  "missed": ["which should_catch items have no evidence"],
  "over_reached": ["which should_ignore items she wrongly acted on"],
  "notes": "one concise line"
}

A 5 means "clearly right across the board." A 3 means "partial / ambiguous."
A 1 means "clearly wrong." If a dimension has no evidence to grade (e.g.
no should_catch items), return 5 by default and say so in notes.
"""


@dataclass
class JudgeVerdict:
    turn_id: str
    awareness_score: int
    discipline_score: int
    voice_score: int
    caught: list[str]
    missed: list[str]
    over_reached: list[str]
    notes: str
    raw: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "awareness_score": self.awareness_score,
            "discipline_score": self.discipline_score,
            "voice_score": self.voice_score,
            "caught": self.caught,
            "missed": self.missed,
            "over_reached": self.over_reached,
            "notes": self.notes,
        }


def _build_turn_prompt(turn_result: dict[str, Any], fixture_turn: Any) -> str:
    """Render one turn's evaluation context for the judge."""
    tool_calls_summary = "\n".join(
        f"  {c.get('tool')}({json.dumps(c.get('inputs'), default=str)[:200]})"
        for c in turn_result.get("tool_call_inputs", [])
    ) or "  (none)"
    reply_text = " | ".join(turn_result.get("reply_bodies", [])) or "(empty)"
    should_catch = "\n".join(f"  - {s}" for s in fixture_turn.should_catch) or "  (none)"
    should_ignore = "\n".join(f"  - {s}" for s in fixture_turn.should_ignore) or "  (none)"

    return (
        f"TURN ID: {fixture_turn.turn_id}\n"
        f"CATEGORY: {fixture_turn.category}\n"
        f"USER MESSAGE: {fixture_turn.message}\n"
        f"FIXTURE NOTES: {fixture_turn.notes}\n\n"
        f"SHOULD CATCH:\n{should_catch}\n\n"
        f"SHOULD IGNORE:\n{should_ignore}\n\n"
        f"DONNA'S TOOL CALLS:\n{tool_calls_summary}\n\n"
        f"DONNA'S REPLY:\n{reply_text}\n"
    )


def _parse_verdict_json(raw: str) -> dict[str, Any]:
    """Best-effort JSON extraction from a possibly-markdown-wrapped response."""
    raw = raw.strip()
    if raw.startswith("```"):
        first_nl = raw.find("\n")
        raw = raw[first_nl + 1 :] if first_nl != -1 else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                pass
        return {}


async def _judge_one(
    client: Any, turn_result: dict[str, Any], fixture_turn: Any
) -> JudgeVerdict:
    prompt = _build_turn_prompt(turn_result, fixture_turn)
    resp = await client.messages.create(
        model=_JUDGE_MODEL,
        max_tokens=600,
        system=_RUBRIC,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_text = ""
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            raw_text += block.text
    parsed = _parse_verdict_json(raw_text)
    return JudgeVerdict(
        turn_id=fixture_turn.turn_id,
        awareness_score=int(parsed.get("awareness_score") or 0),
        discipline_score=int(parsed.get("discipline_score") or 0),
        voice_score=int(parsed.get("voice_score") or 0),
        caught=list(parsed.get("caught") or []),
        missed=list(parsed.get("missed") or []),
        over_reached=list(parsed.get("over_reached") or []),
        notes=str(parsed.get("notes") or ""),
        raw=raw_text,
    )


async def judge_multiturn_result(
    result: Any, fixture: Any
) -> list[JudgeVerdict]:
    """Judge every turn in the result against its fixture MultiTurn.

    Best-effort — any individual judging failure returns a zero-score
    verdict with the error in `notes`. Does not raise.
    """
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic()

    by_turn_id = {t.turn_id: t for t in fixture.turns}
    verdicts: list[JudgeVerdict] = []

    # Concurrent with mild cap so we don't rate-limit.
    sem = asyncio.Semaphore(4)

    async def _one(turn_result_dict: dict[str, Any]) -> JudgeVerdict:
        turn_id = turn_result_dict.get("turn_id") or ""
        fixture_turn = by_turn_id.get(turn_id)
        if fixture_turn is None:
            return JudgeVerdict(
                turn_id=turn_id,
                awareness_score=0, discipline_score=0, voice_score=0,
                caught=[], missed=[], over_reached=[],
                notes="no matching fixture turn",
                raw="",
            )
        async with sem:
            try:
                return await _judge_one(client, turn_result_dict, fixture_turn)
            except Exception as exc:
                logger.exception("judge failed for %s", turn_id)
                return JudgeVerdict(
                    turn_id=turn_id,
                    awareness_score=0, discipline_score=0, voice_score=0,
                    caught=[], missed=[], over_reached=[],
                    notes=f"judge error: {exc}",
                    raw="",
                )

    tasks = [_one(r.to_dict()) for r in result.turn_results]
    verdicts = await asyncio.gather(*tasks)
    return verdicts


def summarize_verdicts(verdicts: list[JudgeVerdict]) -> dict[str, Any]:
    if not verdicts:
        return {"count": 0}
    def _avg(key: str) -> float:
        nums = [getattr(v, key) for v in verdicts if getattr(v, key) > 0]
        return round(sum(nums) / len(nums), 2) if nums else 0.0
    return {
        "count": len(verdicts),
        "avg_awareness": _avg("awareness_score"),
        "avg_discipline": _avg("discipline_score"),
        "avg_voice": _avg("voice_score"),
        "total_caught": sum(len(v.caught) for v in verdicts),
        "total_missed": sum(len(v.missed) for v in verdicts),
        "total_over_reached": sum(len(v.over_reached) for v in verdicts),
    }


def print_judge_report(verdicts: list[JudgeVerdict]) -> None:
    summary = summarize_verdicts(verdicts)
    print("\n=== awareness judge report ===")
    print(f"turns scored: {summary.get('count', 0)}")
    print(f"  avg awareness  {summary.get('avg_awareness', 0):.2f} / 5")
    print(f"  avg discipline {summary.get('avg_discipline', 0):.2f} / 5")
    print(f"  avg voice      {summary.get('avg_voice', 0):.2f} / 5")
    print(f"  missed total:       {summary.get('total_missed', 0)}")
    print(f"  over-reached total: {summary.get('total_over_reached', 0)}")
    print()
    weakest = sorted(
        verdicts,
        key=lambda v: (
            v.awareness_score + v.discipline_score + v.voice_score
        ) / 3,
    )[:10]
    print("weakest 10 turns:")
    for v in weakest:
        avg = (v.awareness_score + v.discipline_score + v.voice_score) / 3
        print(
            f"  [{avg:.1f}] {v.turn_id:<28} "
            f"aw={v.awareness_score} dis={v.discipline_score} vc={v.voice_score}"
        )
        if v.missed:
            print(f"       missed: {', '.join(v.missed)[:140]}")
        if v.over_reached:
            print(f"       over:   {', '.join(v.over_reached)[:140]}")
        if v.notes:
            print(f"       note:   {v.notes[:140]}")
