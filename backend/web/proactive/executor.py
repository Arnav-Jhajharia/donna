"""Executor — dispatches a ``ProactiveMove`` to the right Exa endpoint.

The reasoner picks the lane (search / find_similar / research / webset /
monitor); the executor knows how to call each lane and shape the response
into a uniform ``ProactiveResult``.

Contract:
- Never raises. All failures collapse to ``status="degraded"`` with the
  reason carried in ``skipped_reason``.
- Honors the move's ``params`` dict where the lane supports it
  (category / domains / livecrawl / maxAgeHours).
- ``research`` returns immediately after ``create``; the result is the
  task id. Polling lives outside this module — proactive turns shouldn't
  block on multi-minute research tasks.
- ``webset`` and ``monitor`` are persistence operations; the result
  carries the new resource id, not search hits.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from backend.web.client import (
    exa_find_similar,
    exa_monitor_create,
    exa_research_create,
    exa_search,
    exa_webset_create,
    have_exa_key,
)
from backend.web.proactive.types import ProactiveMove, ProactiveResult

logger = logging.getLogger(__name__)

_DEFAULT_NUM_RESULTS = 5
_DEFAULT_WEBSET_COUNT = 10
_DEFAULT_MONITOR_CADENCE = "daily"


async def execute_move(move: ProactiveMove) -> ProactiveResult:
    """Run a single move. Returns ``ProactiveResult`` (never raises)."""
    if not have_exa_key():
        return ProactiveResult(
            move=move,
            status="skipped",
            skipped_reason="no exa api key",
        )

    started = time.monotonic()
    try:
        if move.tool == "search":
            payload = await _do_search(move)
        elif move.tool == "find_similar":
            payload = await _do_find_similar(move)
        elif move.tool == "research":
            payload = await _do_research(move)
        elif move.tool == "webset":
            payload = await _do_webset(move)
        elif move.tool == "monitor":
            payload = await _do_monitor(move)
        else:
            return ProactiveResult(
                move=move,
                status="skipped",
                skipped_reason=f"unknown tool: {move.tool}",
                elapsed_ms=_elapsed_ms(started),
            )
    except Exception as exc:
        logger.warning("execute_move %s failed: %s", move.tool, exc)
        return ProactiveResult(
            move=move,
            status="degraded",
            skipped_reason=str(exc)[:200],
            elapsed_ms=_elapsed_ms(started),
        )

    if _is_empty(payload):
        return ProactiveResult(
            move=move,
            status="no_hits",
            payload=payload,
            elapsed_ms=_elapsed_ms(started),
        )
    return ProactiveResult(
        move=move,
        status="ok",
        payload=payload,
        elapsed_ms=_elapsed_ms(started),
    )


async def execute_moves(moves: list[ProactiveMove]) -> list[ProactiveResult]:
    """Dispatch each move sequentially. Order preserved.

    Sequential, not parallel, by design: the proactive loop fires a small
    number of moves (<= 3) and we'd rather pace Exa than burst it. Switch
    to ``asyncio.gather`` only if cadence justifies it.
    """
    out: list[ProactiveResult] = []
    for m in moves:
        out.append(await execute_move(m))
    return out


# ---------------------------------------------------------------------------
# per-tool dispatchers
# ---------------------------------------------------------------------------


async def _do_search(move: ProactiveMove) -> dict[str, Any]:
    p = move.params or {}
    return await exa_search(
        move.query,
        num_results=int(p.get("numResults", _DEFAULT_NUM_RESULTS)),
        search_type=str(p.get("type", "auto")),
        category=p.get("category"),
        include_domains=_str_list(p.get("includeDomains")),
        exclude_domains=_str_list(p.get("excludeDomains")),
        start_published_date=_str_or_none(p.get("startPublishedDate")),
        end_published_date=_str_or_none(p.get("endPublishedDate")),
        livecrawl=_str_or_none(p.get("livecrawl")),
        max_age_hours=_int_or_none(p.get("maxAgeHours")),
    )


async def _do_find_similar(move: ProactiveMove) -> dict[str, Any]:
    p = move.params or {}
    return await exa_find_similar(
        move.query,  # for find_similar the "query" is the seed URL
        num_results=int(p.get("numResults", _DEFAULT_NUM_RESULTS)),
        exclude_source_domain=bool(p.get("excludeSourceDomain", False)),
    )


async def _do_research(move: ProactiveMove) -> dict[str, Any]:
    p = move.params or {}
    schema = p.get("outputSchema")
    schema_arg = schema if isinstance(schema, dict) else None
    return await exa_research_create(move.query, output_schema=schema_arg)


async def _do_webset(move: ProactiveMove) -> dict[str, Any]:
    p = move.params or {}
    return await exa_webset_create(
        move.query,
        count=int(p.get("count", _DEFAULT_WEBSET_COUNT)),
        entity_type=_str_or_none(p.get("entityType")),
        criteria=_dict_list(p.get("criteria")),
        enrichments=_dict_list(p.get("enrichments")),
    )


async def _do_monitor(move: ProactiveMove) -> dict[str, Any]:
    p = move.params or {}
    webset_id = _str_or_none(p.get("websetId"))
    if not webset_id:
        raise ValueError("monitor requires params.websetId")
    return await exa_monitor_create(
        webset_id=webset_id,
        cadence=_str_or_none(p.get("cadence")) or _DEFAULT_MONITOR_CADENCE,
        behavior=_str_or_none(p.get("behavior")) or "search",
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _is_empty(payload: dict[str, Any] | None) -> bool:
    if not payload:
        return True
    if isinstance(payload, dict):
        results = payload.get("results")
        if isinstance(results, list):
            return len(results) == 0
    return False


def _str_or_none(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _int_or_none(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _str_list(v: Any) -> list[str] | None:
    if not isinstance(v, list):
        return None
    out = [str(x).strip() for x in v if str(x).strip()]
    return out or None


def _dict_list(v: Any) -> list[dict[str, Any]] | None:
    if not isinstance(v, list):
        return None
    out = [x for x in v if isinstance(x, dict)]
    return out or None
