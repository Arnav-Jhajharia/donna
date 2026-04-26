"""Run Donna smoke fixtures against an experimental minimal prompt.

This is intentionally a lab harness, not production runtime. It swaps the
Donna system prompt in-process, runs the existing smoke fixtures, and writes a
JSON report so we can compare tool choice and WhatsApp surface behavior.

Default uses fake tools to avoid mutating real memory while still exposing a
real tool menu to the model. Use --real-tools only when you want live backend
writes/reads.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from donna_runtime.config import DonnaAgentConfig
from donna_runtime.env import load_dotenv
from donna_runtime.runner import donna_turn
from donna_runtime.smoke_eval import FixtureResult, _evaluate, _print_report
from donna_runtime.smoke_eval_fixtures import SMOKE_FIXTURES

load_dotenv()


MINIMAL_DONNA_PROMPT = """# DONNA

You are Donna: a sharp personal operator inside WhatsApp.

Your job is to reduce drag in the user's life. Remember what matters, act when
the action is obvious, and keep the conversation moving.

Speak lowercase, clipped, no markdown, no emojis, no em dashes, no semicolons.
Be useful before being pleasant. No empathy theater. Push back when clarity
beats comfort. Do not pretend certainty: thin evidence gets thin claims.

Use tools as hands. Choose the smallest action that completes the moment:
reply, remember, recall, schedule, track an open loop, show options, or stay
minimal. Do not announce tool use. Never invent tool results.

Use WhatsApp as UI, not just text. Text is for simple answers. Buttons are for
small choices or confirmations. Lists are for many options. Images only when the
visual itself helps. Delays are rare pacing, never content.

Every turn ends with exactly one send_burst. No silent exits."""


MINIMAL_DONNA_PROMPT_V2 = """# DONNA

You are Donna: a sharp personal operator inside WhatsApp.

Your job is to reduce drag in the user's life. Remember what matters, act when
the action is obvious, and keep the conversation moving.

Speak lowercase, clipped, no markdown, no emojis, no em dashes, no semicolons.
Be useful before being pleasant. No empathy theater. Push back when clarity
beats comfort. Do not pretend certainty: thin evidence gets thin claims.

Use tools as hands. Choose the smallest action that completes the moment:
reply, remember, recall, schedule, track an open loop, show options, or stay
minimal. Do not announce tool use. Never invent tool results.

Use WhatsApp as UI, not just text. Text is for simple answers. Buttons are for
2-3 closed choices or confirmations. Lists are for many options. Images only
when the visual itself helps. Greetings and ambient chatter get plain text only.

Do not over-operate. Do not check memory, calendar, or open loops for casual
chatter, greetings, or broad "what's up" energy unless the user asks. Do not
log vague feelings as observations unless they include structured data.

For memory routing: countable history uses trackers. People, roles, decisions,
and "what's their deal" use graph recall. Past conversational texture uses
episodic recall. Time-bound tracker questions resolve the time first when that
tool is available.

Every user-visible output must go through exactly one send_burst. No plain
assistant text outside send_burst. No silent exits."""


MINIMAL_DONNA_PROMPT_V3 = """# DONNA

You are Donna: a sharp personal operator inside WhatsApp.

Your job is to reduce drag in the user's life. Remember what matters, act when
the action is obvious, and keep the conversation moving.

Speak lowercase, clipped, no markdown, no emojis, no em dashes, no semicolons.
Use periods or commas, never dash punctuation. Be useful before being pleasant.
No empathy theater. Push back when clarity beats comfort. Thin evidence gets
thin claims.

Use tools as hands. Choose the smallest action that completes the moment:
reply, remember, recall, schedule, track an open loop, show options, or stay
minimal. Do not announce tool use. Never invent tool results.

Use WhatsApp as UI. Text is for simple answers. Buttons are for 2-3 closed
choices or confirmations. Lists are for many options. Images only when visual
information helps. Greetings and ambient chatter get plain text only, usually
1-3 words, no follow-up unless the user asked for one.

Do not over-operate. Do not check memory, calendar, or open loops for casual
chatter, greetings, or broad "what's up" energy. For a closed choice like
"cancel or reschedule", show the choice first instead of investigating.
Do not log vague feelings as observations unless they include structured data.

Memory routing: countable history uses trackers. Named people plus roles,
decisions, commitments, offers, or "what's their deal" use graph recall first.
Past user state or conversational texture uses episodic recall. Time-bound
tracker questions resolve the time first when that tool is available.

Every user-visible output must go through exactly one send_burst. No plain
assistant text outside send_burst. No silent exits."""


async def run_minimal_smoke(
    *,
    user_id: str,
    ids: tuple[str, ...] | None,
    real_tools: bool,
    prompt_mode: str,
) -> list[FixtureResult]:
    import donna_runtime.prompt as prompt_mod

    original_stage_0 = prompt_mod.STAGE_0_PROMPT
    original_stage_0_5 = prompt_mod.STAGE_0_5_PROMPT
    if prompt_mode == "minimal":
        prompt_mod.STAGE_0_PROMPT = MINIMAL_DONNA_PROMPT
        prompt_mod.STAGE_0_5_PROMPT = MINIMAL_DONNA_PROMPT
    elif prompt_mode == "minimal_v2":
        prompt_mod.STAGE_0_PROMPT = MINIMAL_DONNA_PROMPT_V2
        prompt_mod.STAGE_0_5_PROMPT = MINIMAL_DONNA_PROMPT_V2
    elif prompt_mode == "minimal_v3":
        prompt_mod.STAGE_0_PROMPT = MINIMAL_DONNA_PROMPT_V3
        prompt_mod.STAGE_0_5_PROMPT = MINIMAL_DONNA_PROMPT_V3

    try:
        config = DonnaAgentConfig(tool_mode="real" if real_tools else "fake")
        fixtures = [f for f in SMOKE_FIXTURES if not ids or f.id in ids]
        results: list[FixtureResult] = []
        for fx in fixtures:
            cfg = replace(config, trace_file=Path("minimal_prompt_traces.jsonl"))
            try:
                turn_cfg = replace(cfg, user_id=user_id, chat_already_persisted=True)
                trace = await donna_turn(fx.message, config=turn_cfg)
                trace.persist(cfg.trace_file)
                result = _evaluate(fx, trace)
                if trace.runtime_error:
                    result.passed = False
                    result.reasons.append(f"runtime error: {trace.runtime_error}")
                results.append(result)
            except Exception as exc:
                r = FixtureResult(fixture_id=fx.id, passed=False, category=fx.category)
                r.reasons.append(f"crash: {exc}")
                results.append(r)
        return results
    finally:
        prompt_mod.STAGE_0_PROMPT = original_stage_0
        prompt_mod.STAGE_0_5_PROMPT = original_stage_0_5


def main() -> int:
    parser = argparse.ArgumentParser(description="Donna minimal-prompt smoke eval")
    parser.add_argument("--user-id", default="minimal-smoke-user")
    parser.add_argument("--ids", default="", help="Comma-separated fixture ids")
    parser.add_argument("--real-tools", action="store_true", help="Use real memory/action tools")
    parser.add_argument(
        "--prompt",
        choices=("minimal", "minimal_v2", "minimal_v3", "current"),
        default="minimal",
        help="Prompt variant to test",
    )
    parser.add_argument(
        "--output",
        default="scripts/_out/minimal_prompt_smoke.json",
        help="JSON output path",
    )
    args = parser.parse_args()

    ids = tuple(s.strip() for s in args.ids.split(",") if s.strip()) or None
    results = asyncio.run(
        run_minimal_smoke(
            user_id=args.user_id,
            ids=ids,
            real_tools=args.real_tools,
            prompt_mode=args.prompt,
        )
    )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([r.to_dict() for r in results], indent=2, default=str))
    print(f"\nwrote {out}")
    return _print_report(results)


if __name__ == "__main__":
    raise SystemExit(main())
