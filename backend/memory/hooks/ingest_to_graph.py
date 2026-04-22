"""Gated Graphiti ingestion (spec §6 + §7).

Runs the three-layer selectivity gate; only ingests when the verdict is
worth_ingesting=True. This is the fix for the commented-out reactive-ingest
bug in the legacy runtime.
"""
from __future__ import annotations

import logging
from typing import Any, Mapping

from backend.memory.clients import graphiti as graphiti_client
from backend.memory.gates.graph_ingest_gate import GateInput, should_ingest_to_graph

logger = logging.getLogger(__name__)


def _format_episode(inbound: str, outbound: list[str]) -> str:
    parts: list[str] = []
    if inbound.strip():
        parts.append(f"USER: {inbound.strip()}")
    for msg in outbound:
        text = (msg or "").strip()
        if text:
            parts.append(f"DONNA: {text}")
    return "\n".join(parts)


async def run(ctx: Mapping[str, Any]) -> None:
    user_id = ctx.get("user_id")
    inbound = ctx.get("inbound") or ""
    outbound = list(ctx.get("outbound") or [])
    tool_names = list(ctx.get("tool_names") or [])
    terminator = ctx.get("terminator") or "send_burst"
    if not user_id:
        return

    g = GateInput(
        inbound=inbound,
        outbound=outbound,
        tool_names=tool_names,
        terminator=terminator,
    )
    verdict = await should_ingest_to_graph(g)
    if not verdict.worth_ingesting:
        return

    body = _format_episode(inbound, outbound)
    if not body:
        return

    try:
        await graphiti_client.ingest_episode(user_id=user_id, content=body)
    except Exception:
        logger.exception("ingest_to_graph: ingest_episode failed")
