"""Minimal Anthropic structured-output helper.

Replaces the perceive.structured.call_structured dependency with an inline
tool-use call against Haiku. Returns None when SDK/key missing, on timeout,
or on parse failure — callers must fall back gracefully.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Type, TypeVar, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from backend.config import get_settings

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


# Pattern for `<item>...</item>` list elements emitted by Haiku when it
# falls back to XML-style serialization inside a tool_use string field.
_ITEM_RE = re.compile(r"<item>(.*?)</item>", re.DOTALL)
# Pattern for `<parameter name="key">value</parameter>` dict entries.
_PARAM_RE = re.compile(
    r'<parameter\s+name="([^"]+)">(.*?)</parameter>',
    re.DOTALL,
)


def _strip(value: str) -> str:
    return value.strip()


def _parse_xml_list(raw: str) -> list[str] | None:
    """Pull `<item>...</item>` chunks out of a string, return list of stripped
    contents. Returns None when no items are found so callers can decide
    whether to leave the value alone or fall back."""
    matches = _ITEM_RE.findall(raw)
    if not matches:
        return None
    return [_strip(m) for m in matches if _strip(m)]


def _parse_xml_dict(raw: str) -> dict[str, Any] | None:
    """Pull `<parameter name="k">v</parameter>` chunks into a dict. Returns
    None when no parameters are found."""
    matches = _PARAM_RE.findall(raw)
    if not matches:
        return None
    return {k: _strip(v) for k, v in matches}


def _is_list_type(annotation: Any) -> bool:
    origin = get_origin(annotation)
    return origin is list or annotation is list


def _is_basemodel_type(annotation: Any) -> bool:
    try:
        return isinstance(annotation, type) and issubclass(annotation, BaseModel)
    except TypeError:
        return False


def _coerce_value(field_annotation: Any, value: Any) -> Any:
    """Best-effort coerce a tool_use string back into the shape Pydantic
    expects. Handles two common Haiku failure modes:

    - list field returned as a string of `<item>...</item>` tags
    - BaseModel/dict field returned as a string of `<parameter name="...">`
      tags

    Idempotent on already-correct values: lists pass through, dicts pass
    through, BaseModels pass through. Returns the value unchanged when no
    coercion applies."""
    if value is None:
        return value

    # list[X] field but model handed back a string — try XML-list parsing.
    if _is_list_type(field_annotation) and isinstance(value, str):
        parsed = _parse_xml_list(value)
        if parsed is None:
            return value
        # If the inner type is a BaseModel, try to JSON-parse each item
        # so nested dict-shaped items survive. Plain str items pass through.
        inner_args = get_args(field_annotation)
        inner = inner_args[0] if inner_args else str
        if _is_basemodel_type(inner):
            coerced: list[Any] = []
            for item in parsed:
                # Each <item> may itself contain JSON or <parameter> tags.
                try:
                    coerced.append(json.loads(item))
                    continue
                except Exception:
                    pass
                inner_dict = _parse_xml_dict(item)
                coerced.append(inner_dict if inner_dict is not None else item)
            return coerced
        return parsed

    # BaseModel field but model handed back a string — try XML-dict parsing.
    if _is_basemodel_type(field_annotation) and isinstance(value, str):
        parsed_dict = _parse_xml_dict(value)
        if parsed_dict is not None:
            return parsed_dict
        # Some payloads come back as raw JSON inside a string.
        try:
            loaded = json.loads(value)
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            pass

    return value


def _coerce_payload(schema: Type[BaseModel], payload: Any) -> Any:
    """Walk a Pydantic schema's declared fields and coerce any string-valued
    fields back into list/dict shapes when the schema expects those. Leaves
    other values alone. Returns a new dict."""
    if not isinstance(payload, dict):
        return payload
    out: dict[str, Any] = dict(payload)
    fields: dict[str, FieldInfo] = schema.model_fields
    for name, info in fields.items():
        if name not in out:
            continue
        out[name] = _coerce_value(info.annotation, out[name])
    return out


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
            payload = block.input
            try:
                return schema.model_validate(payload)
            except Exception:
                # Haiku occasionally hands back string fields containing
                # XML-style tags (`<item>...</item>` for lists,
                # `<parameter name="...">...</parameter>` for nested
                # objects) instead of proper JSON arrays/dicts. Coerce
                # before giving up.
                coerced = _coerce_payload(schema, payload)
                if coerced is not payload:
                    try:
                        return schema.model_validate(coerced)
                    except Exception:
                        pass
                logger.exception(
                    "call_structured: parse failed payload=%s",
                    json.dumps(payload, default=str)[:400],
                )
                return None
    return None
