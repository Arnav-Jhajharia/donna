"""Judge: LLM-based pass/fail for a single stress-test reply.

Kept pure (prompt rendering + response parsing) so tests don't hit the
API. The actual Haiku call lives behind a Protocol so the runner can
inject a real client or a deterministic fake.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

from scripts._stress_matrix.cases import StressCase
from scripts._stress_matrix.trace import JudgeVerdict

_PROMPT_TEMPLATE = """You are grading a single reply from Donna (a WhatsApp-native personal AI).
The grading is binary: either the reply satisfies the rubric, or it doesn't.

CASE ID: {case_id}
SECTION: {section}
USER QUERY: {query}
RUBRIC (pass criteria): {pass_criteria}

EXPECTED BACKENDS (what storage lanes *should* have fired): {expected_backends}
ACTUAL BACKENDS HIT: {backends_hit}

REPLY BODY:
---
{reply_body}
---

Respond with ONLY a compact JSON object of the shape:
{{"passed": true | false, "reason": "<one short sentence>"}}

Rules:
- "passed" is true only if the reply satisfies the rubric as written.
- "reason" must cite the specific evidence you used (or what was missing).
- Do not grade on voice or tone here unless the rubric explicitly asks.
- Fabricated numbers, names, or times count as failure even if the shape looks right.
"""


class JudgeClient(Protocol):
    """Injectable grader. In production: a small Haiku call."""

    async def grade(self, prompt: str) -> str: ...


@dataclass(frozen=True)
class JudgeContext:
    case: StressCase
    reply_body: str
    backends_hit: tuple[str, ...]


def render_prompt(ctx: JudgeContext) -> str:
    return _PROMPT_TEMPLATE.format(
        case_id=ctx.case.id,
        section=ctx.case.section,
        query=ctx.case.query,
        pass_criteria=ctx.case.pass_criteria,
        expected_backends=", ".join(ctx.case.expected_backends) or "(none)",
        backends_hit=", ".join(ctx.backends_hit) or "(none)",
        reply_body=ctx.reply_body or "(empty)",
    )


def parse_verdict(raw: str, *, case: StressCase) -> JudgeVerdict:
    """Extract ``{"passed": bool, "reason": str}`` from the judge reply.

    Tolerates extra surrounding text by pulling the first JSON object.
    Falls back to ``passed=False`` with the raw text as the reason when
    parsing fails — better to treat ambiguity as failure than as success.
    """
    obj = _first_json_object(raw)
    if not isinstance(obj, dict):
        return JudgeVerdict(passed=False, reason=f"judge returned non-JSON: {raw[:160]}", rubric=case.pass_criteria)
    passed = bool(obj.get("passed"))
    reason = str(obj.get("reason") or "").strip() or "(no reason given)"
    return JudgeVerdict(passed=passed, reason=reason, rubric=case.pass_criteria)


async def grade(
    client: JudgeClient,
    ctx: JudgeContext,
) -> JudgeVerdict:
    prompt = render_prompt(ctx)
    raw = await client.grade(prompt)
    return parse_verdict(raw, case=ctx.case)


# -- Internals ---------------------------------------------------------------


_JSON_RE = re.compile(r"\{[\s\S]*?\}")


def _first_json_object(raw: str) -> Any:
    text = (raw or "").strip()
    if not text:
        return None
    # Fast path: the whole thing is JSON.
    try:
        return json.loads(text)
    except Exception:
        pass
    for match in _JSON_RE.finditer(text):
        try:
            return json.loads(match.group(0))
        except Exception:
            continue
    return None
