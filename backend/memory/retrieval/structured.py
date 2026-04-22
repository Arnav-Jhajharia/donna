"""Minimal Anthropic structured-output helper.

Replaces the perceive.structured.call_structured dependency with an inline
tool-use call against Haiku. Returns None when SDK/key missing, on timeout,
or on parse failure — callers must fall back gracefully.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Type, TypeVar

from pydantic import BaseModel

from backend.config import get_settings

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


async def call_structured(
    *,
    model: str,
    system_prompt: str,
    user_message: str,
    schema: Type[T],
    max_tokens: int = 400,
    cache: bool = False,
    timeout: float = 8.0,
) -> T | None:
    settings = get_settings()
    if not settings.anthropic_api_key:
        return None
    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        logger.warning("anthropic SDK missing — structured call returns None")
        return None

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    tool_name = "emit_" + schema.__name__.lower().lstrip("_")
    tool = {
        "name": tool_name,
        "description": f"Emit a {schema.__name__} instance.",
        "input_schema": schema.model_json_schema(),
    }
    try:
        resp = await asyncio.wait_for(
            client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
                tools=[tool],
                tool_choice={"type": "tool", "name": tool_name},
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("call_structured: timeout")
        return None
    except Exception:
        logger.exception("call_structured: api call failed")
        return None

    for block in resp.content:
        if getattr(block, "type", "") == "tool_use" and block.name == tool_name:
            try:
                return schema.model_validate(block.input)
            except Exception:
                logger.exception("call_structured: parse failed payload=%s", json.dumps(block.input)[:200])
                return None
    return None
