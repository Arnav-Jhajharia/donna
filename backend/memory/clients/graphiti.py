"""Graphiti (Zep) client — ported from backend-v2/graph_memory/client.py.

Preserves the two pitfalls from spec §12:
  - _route_to_user_db(g, group_id) called before every query
  - group_id = user_id.replace("-", "") normalization

Degrades gracefully when Graphiti/FalkorDB are unavailable: functions log and
return empty lists / no-ops.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from backend.config import get_settings

logger = logging.getLogger(__name__)

_graphiti = None


async def _init_graphiti():
    settings = get_settings()
    try:
        from graphiti_core import Graphiti
        from graphiti_core.llm_client.anthropic_client import AnthropicClient
        from graphiti_core.llm_client.config import LLMConfig
        from graphiti_core.driver.falkordb_driver import FalkorDriver
    except ImportError:
        logger.warning("graphiti_core not installed — graph tools will return degraded")
        return None

    if settings.anthropic_api_key:
        os.environ.setdefault("ANTHROPIC_API_KEY", settings.anthropic_api_key)
    if settings.openai_api_key:
        os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)

    try:
        driver = FalkorDriver(
            host=settings.falkordb_host,
            port=settings.falkordb_port,
            username=settings.falkordb_username or None,
            password=settings.falkordb_password or None,
        )
        llm_client = AnthropicClient(
            config=LLMConfig(
                api_key=settings.anthropic_api_key,
                model="claude-haiku-4-5-20251001",
            )
        )
        g = Graphiti(graph_driver=driver, llm_client=llm_client)
        try:
            await g.build_indices_and_constraints()
        except Exception as e:
            logger.warning("graphiti: build_indices_and_constraints: %s", e)
        logger.info(
            "graphiti: initialized (FalkorDB %s:%s)",
            settings.falkordb_host,
            settings.falkordb_port,
        )
        return g
    except Exception:
        logger.exception("graphiti init failed")
        return None


async def get_graphiti():
    global _graphiti
    if _graphiti is not None:
        return _graphiti
    _graphiti = await _init_graphiti()
    return _graphiti


def _safe_group_id(user_id: str) -> str:
    return user_id.replace("-", "")


def _route_to_user_db(g, group_id: str) -> None:
    if g.driver._database != group_id:
        g.driver = g.driver.clone(database=group_id)
        g.clients.driver = g.driver


def _reset_singleton() -> None:
    global _graphiti
    _graphiti = None


async def ingest_episode(
    user_id: str,
    content: str,
    reference_time: datetime | None = None,
    metadata: dict | None = None,
) -> bool:
    """Ingest episode. Returns True on success, False on degraded/failure."""
    g = await get_graphiti()
    if g is None:
        return False
    try:
        from graphiti_core.nodes import EpisodeType
    except ImportError:
        return False

    ref_time = reference_time or datetime.now(timezone.utc)
    group_id = _safe_group_id(user_id)
    try:
        await g.add_episode(
            name=f"ep_{ref_time.strftime('%Y%m%d_%H%M%S')}",
            episode_body=content,
            source=EpisodeType.text,
            source_description="Donna conversation",
            reference_time=ref_time,
            group_id=group_id,
        )
        logger.info(
            "graphiti: ingested episode user=%s (%d chars)", user_id[:8], len(content)
        )
        return True
    except Exception as exc:
        if "onnection" in str(exc):
            _reset_singleton()
        logger.exception("graphiti ingest failed")
        return False


async def search_facts(user_id: str, query: str, limit: int = 10) -> list[dict]:
    g = await get_graphiti()
    if g is None:
        return []
    group_id = _safe_group_id(user_id)
    try:
        _route_to_user_db(g, group_id)
        results = await g.search(query, group_ids=[group_id], num_results=limit)
    except Exception:
        logger.exception("graphiti search failed")
        return []

    facts = []
    for edge in results:
        facts.append(
            {
                "fact": edge.fact,
                "valid_at": str(edge.valid_at) if edge.valid_at else None,
                "invalid_at": str(edge.invalid_at) if edge.invalid_at else None,
                "created_at": str(edge.created_at) if edge.created_at else None,
                "uuid": str(edge.uuid) if hasattr(edge, "uuid") else "",
                "episodes": edge.episodes[:3]
                if hasattr(edge, "episodes") and edge.episodes
                else [],
            }
        )
    return facts[:limit]


async def reset_user_graph(user_id: str) -> None:
    g = await get_graphiti()
    if g is None:
        return
    try:
        group_id = _safe_group_id(user_id)
        _route_to_user_db(g, group_id)
        await g.driver.execute_query("MATCH (n) DETACH DELETE n")
        _reset_singleton()
    except Exception:
        logger.exception("graphiti reset failed")
        _reset_singleton()


async def close() -> None:
    global _graphiti
    if _graphiti is not None:
        try:
            await _graphiti.close()
        except Exception:
            pass
        _graphiti = None
