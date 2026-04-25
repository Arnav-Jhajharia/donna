"""Haiku 4.5 judge implementation.

Per CLAUDE.md: Haiku is permitted only for "offline eval / awareness
scoring" — which is exactly what the judge does. Kept thin: render the
prompt (in judge.py), make one Anthropic call, return the raw text.
``parse_verdict`` upstream handles JSON extraction + ambiguity.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS = 200
DEFAULT_TIMEOUT_S = 12.0


@dataclass(frozen=True)
class HaikuJudge:
    """JudgeClient Protocol implementation backed by Anthropic's API.

    Construction is cheap; the SDK client is built per call so a stale
    process doesn't hold a connection across long stress runs.
    """

    api_key: str
    model: str = DEFAULT_MODEL
    max_tokens: int = DEFAULT_MAX_TOKENS
    timeout_s: float = DEFAULT_TIMEOUT_S

    async def grade(self, prompt: str) -> str:
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:
            raise RuntimeError("anthropic SDK not installed") from exc

        client = AsyncAnthropic(api_key=self.api_key)
        try:
            resp = await asyncio.wait_for(
                client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                ),
                timeout=self.timeout_s,
            )
        except asyncio.TimeoutError as exc:
            raise RuntimeError(f"haiku judge timeout after {self.timeout_s}s") from exc

        return _extract_text(resp)


def build_judge_from_env(env: dict[str, str] | None = None) -> HaikuJudge | None:
    """Construct a HaikuJudge from ANTHROPIC_API_KEY.

    Returns ``None`` (with a warning) when the key is absent so the
    runner can degrade to ``judge skipped`` instead of crashing.
    Optional ``DONNA_JUDGE_MODEL`` overrides the model.
    """
    source = env if env is not None else os.environ
    api_key = (source.get("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY missing — judge will be skipped")
        return None
    model = (source.get("DONNA_JUDGE_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    return HaikuJudge(api_key=api_key, model=model)


def _extract_text(response: object) -> str:
    """Pull the first text block out of a Messages API response.

    Tolerates the SDK shape: ``response.content`` is a list of blocks;
    a text block exposes ``.text`` (and ``type == 'text'``).
    """
    content = getattr(response, "content", None) or []
    parts: list[str] = []
    for block in content:
        if getattr(block, "type", "") != "text":
            continue
        text = getattr(block, "text", "")
        if text:
            parts.append(str(text))
    return "\n".join(parts).strip()
