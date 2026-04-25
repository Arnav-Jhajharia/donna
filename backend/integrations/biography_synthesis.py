"""Biography synthesis — four LLM extraction passes plus a synthesis pass.

Output written to users.living_profile.biography via update_living_profile.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from backend.integrations.composio_client import NormalizedGmailMessage
from backend.memory.tools.update_living_profile import update_living_profile
from config import settings
from donna_runtime.config import MODEL_NAME

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"

_PASSES = [
    ("relationships", "biography_relationships.md"),
    ("work", "biography_work.md"),
    ("interests", "biography_interests.md"),
    ("life_signals", "biography_life_signals.md"),
]

_LLM_MAX_TOKENS = 1500
_LLM_TIMEOUT_S = 30.0


async def _call_llm(prompt: str, model: str = MODEL_NAME) -> str:
    """Issue a single text-completion call to Sonnet 4.6. Pluggable for tests."""
    if not settings.anthropic_api_key:
        return ""
    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        logger.warning("biography_synthesis: anthropic SDK missing")
        return ""

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        resp = await client.messages.create(
            model=model,
            max_tokens=_LLM_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
            timeout=_LLM_TIMEOUT_S,
        )
    except Exception:
        logger.exception("biography_synthesis: LLM call failed")
        return ""

    parts = [
        getattr(block, "text", "")
        for block in resp.content
        if getattr(block, "type", "") == "text"
    ]
    return "".join(parts).strip()


def _format_messages(msgs: Iterable[NormalizedGmailMessage]) -> str:
    chunks = []
    for m in msgs:
        body = (m.body_text or "")[:1500]
        chunks.append(
            f"From: {m.from_name or ''} <{m.from_address}>\n"
            f"Date: {m.internal_date.isoformat()}\n"
            f"Subject: {m.subject or ''}\n\n{body}\n---"
        )
    return "\n".join(chunks)


def _format_aggregates(aggs: list[dict]) -> str:
    return "\n".join(
        f"{a['from_address']} — {a['count']} msgs — sample: "
        f"{', '.join(a.get('sample_subjects', []))}"
        for a in aggs
    )


async def _run_pass(
    pass_name: str,
    prompt_file: str,
    messages_block: str,
    aggregates_block: str,
) -> dict:
    prompt = (_PROMPTS_DIR / prompt_file).read_text()
    rendered = (
        f"{prompt}\n\n## EMAILS\n{messages_block}\n\n"
        f"## FREQUENT SENDERS\n{aggregates_block}"
    )
    raw = await _call_llm(rendered)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.exception("biography pass %s: bad JSON", pass_name)
        return {}


async def synthesize_biography(
    user_id: str,
    full_messages: list[NormalizedGmailMessage],
    sender_aggregates: list[dict],
) -> dict:
    if not full_messages and not sender_aggregates:
        return {}

    messages_block = _format_messages(full_messages)
    aggregates_block = _format_aggregates(sender_aggregates)

    pass_outputs: dict[str, dict] = {}
    for name, prompt_file in _PASSES:
        pass_outputs[name] = await _run_pass(
            name, prompt_file, messages_block, aggregates_block
        )

    synthesis_prompt = (
        (_PROMPTS_DIR / "biography_synthesis.md").read_text()
        + "\n\n## RELATIONSHIPS\n"
        + json.dumps(pass_outputs.get("relationships", {}))
        + "\n\n## WORK\n"
        + json.dumps(pass_outputs.get("work", {}))
        + "\n\n## INTERESTS\n"
        + json.dumps(pass_outputs.get("interests", {}))
        + "\n\n## LIFE\n"
        + json.dumps(pass_outputs.get("life_signals", {}))
    )
    synth_raw = await _call_llm(synthesis_prompt)
    try:
        synthesis = json.loads(synth_raw)
    except json.JSONDecodeError:
        synthesis = {"overview": ""}

    work_pass = pass_outputs.get("work", {})
    relationships_pass = pass_outputs.get("relationships", {})
    interests_pass = pass_outputs.get("interests", {})
    life_pass = pass_outputs.get("life_signals", {})

    biography = {
        "overview": synthesis.get("overview", ""),
        "work": work_pass.get("work", work_pass),
        "relationships": relationships_pass.get(
            "relationships", relationships_pass
        ),
        "interests": interests_pass.get("interests", []),
        "rhythms": life_pass.get("rhythms", {}),
        "evidence_window": {
            "today_messages": sum(
                1 for m in full_messages if m.is_important is False
            ),
            "important_30d_messages": sum(
                1 for m in full_messages if m.is_important
            ),
            "aggregated_90d_senders": len(sender_aggregates),
        },
        "last_bootstrapped_at": datetime.now(timezone.utc).isoformat(),
    }

    await update_living_profile(
        user_id=user_id, patch={"biography": biography}
    )
    return biography
