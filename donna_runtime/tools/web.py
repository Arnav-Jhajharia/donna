from __future__ import annotations

import logging

from claude_agent_sdk import tool

from ..langsmith_tracing import traceable
from ..tool_logic import text_content
from ._shared import _current_user_id

logger = logging.getLogger(__name__)

def _render_web_hits(hits: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for hit in hits:
        title = str(hit.get("title") or "").strip()
        url = str(hit.get("url") or "").strip()
        snippet = str(hit.get("snippet") or "").strip()
        head = f"- {title} ({url})" if title else f"- {url}"
        if snippet:
            head += f" — {snippet}"
        lines.append(head)
    return "\n".join(lines)


def _render_agentic_answer(payload: dict[str, Any]) -> str:
    answer = str(payload.get("answer") or "").strip()
    sources = payload.get("sources") or []
    lines: list[str] = []
    if answer:
        lines.append(f"answer: {answer}")
    if sources:
        lines.append("sources:")
        for src in sources:
            title = str(src.get("title") or "").strip()
            url = str(src.get("url") or "").strip()
            if not url:
                continue
            lines.append(f"- {title} ({url})" if title else f"- {url}")
    return "\n".join(lines) if lines else "no web answer."


@tool(
    "web_search",
    (
        "Single-shot external web search. Returns 3-5 hits as "
        "'- title (url) — snippet' lines. "
        "Use for a fresh factual lookup Donna cannot know from memory: "
        "current events, prices, openings, definitions, references, "
        "people or companies the user just mentioned by name. "
        "Do NOT use for questions about the user (use recall). "
        "Do NOT use for facts already in the situation brief or chat. "
        "Do NOT use for comparison or synthesis across multiple sources "
        "(use agentic_web_search). "
        "Do NOT use for self-harm, medical emergency, or sensitive topics "
        "where safety floors apply. "
        "Do NOT chain multiple web_search calls in one turn, use "
        "agentic_web_search instead. "
        "The result is raw material, not a reply. Read it, pick the one "
        "thing that answers the question, synthesize in Donna's voice."
    ),
    {
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {
                "type": "string",
                "description": "Short search phrase. Plain words, not a question.",
            },
            "max_results": {
                "type": "integer",
                "description": "How many hits to return (1-10, default 5).",
            },
            "recency": {
                "type": "string",
                "enum": ["day", "week", "month", "year"],
                "description": (
                    "Optional recency filter when the answer depends on "
                    "freshness (news, scores, price). Omit otherwise."
                ),
            },
        },
    },
)
@traceable(name="donna.tool.web_search", run_type="tool")
async def web_search(args):
    from backend.web.search import search_web as _search_web

    query = str(args.get("query") or "").strip() if isinstance(args, dict) else ""
    if not query:
        return text_content("web_search: query is required.")
    max_results = args.get("max_results") or 5
    recency = args.get("recency") if isinstance(args, dict) else None
    try:
        res = await _search_web(
            query,
            max_results=int(max_results),
            recency=recency if isinstance(recency, str) else None,
        )
    except Exception:
        logger.exception("web_search: unexpected failure")
        return text_content("web_search unavailable.")
    status = res.get("status")
    if status == "degraded":
        reason = (
            res.get("payload", {}).get("reason")
            if isinstance(res.get("payload"), dict)
            else ""
        )
        suffix = f" {reason}" if reason else ""
        return text_content(f"web_search unavailable.{suffix}")
    if status == "no_hits" or not res.get("payload"):
        return text_content("web_search: no hits.")
    return text_content(_render_web_hits(res["payload"]))


@tool(
    "agentic_web_search",
    (
        "Deeper multi-source web research. The provider reads several pages "
        "and returns a synthesized answer plus up to 5 supporting URLs. "
        "Use for comparison, synthesis, or 'current state of X' questions "
        "where one snippet will not cut it. Examples: "
        "'compare Poke and Limitless today', 'what are people saying about "
        "the openai sora pricing change', 'state of antler SG batch 13 "
        "companies'. "
        "Do NOT use for single-fact lookups (use web_search, cheaper). "
        "Do NOT use for questions about the user (use recall). "
        "Do NOT use speculatively when no external source helps. "
        "Do NOT use after web_search already gave a clear answer this turn. "
        "Call once per turn. The answer is raw material, not a reply — "
        "read it, pick the beat that matters, speak in Donna's voice."
    ),
    {
        "type": "object",
        "required": ["question"],
        "properties": {
            "question": {
                "type": "string",
                "description": (
                    "Specific research question in plain words. Include "
                    "comparison targets or scope if relevant."
                ),
            },
            "max_results": {
                "type": "integer",
                "description": "How many supporting sources to request (1-10, default 5).",
            },
        },
    },
)
@traceable(name="donna.tool.agentic_web_search", run_type="tool")
async def agentic_web_search(args):
    from backend.web.search import agentic_search as _agentic_search

    question = str(args.get("question") or "").strip() if isinstance(args, dict) else ""
    if not question:
        return text_content("agentic_web_search: question is required.")
    max_results = args.get("max_results") or 5
    try:
        res = await _agentic_search(question, max_results=int(max_results))
    except Exception:
        logger.exception("agentic_web_search: unexpected failure")
        return text_content("agentic_web_search unavailable.")
    status = res.get("status")
    if status == "degraded":
        reason = (
            res.get("payload", {}).get("reason")
            if isinstance(res.get("payload"), dict)
            else ""
        )
        suffix = f" {reason}" if reason else ""
        return text_content(f"agentic_web_search unavailable.{suffix}")
    if status == "no_hits" or not res.get("payload"):
        return text_content("agentic_web_search: no hits.")
    return text_content(_render_agentic_answer(res["payload"]))


def _render_research_answer(
    answer: str,
    sources: list[Any],
    *,
    confidence: float,
    dissent: str | None,
    variant: str,
) -> str:
    lines: list[str] = []
    if answer:
        lines.append(f"answer ({variant}, confidence={confidence:.2f}): {answer}")
    if dissent:
        lines.append(f"dissent: {dissent}")
    if sources:
        lines.append("sources:")
        for src in sources[:5]:
            title = (getattr(src, "title", "") or "").strip()
            url = (getattr(src, "url", "") or "").strip()
            if not url:
                continue
            lines.append(f"- {title} ({url})" if title else f"- {url}")
    return "\n".join(lines) if lines else "no web answer."


@tool(
    "research",
    (
        "Deep multi-stage web research. Runs our own pipeline: query "
        "expansion via Haiku, parallel Exa neural + keyword search, URL "
        "dedup + RRF, optional Cohere rerank, and a two-prompt synthesis "
        "(strict facts vs weak signals ok) with a judge. Returns one "
        "synthesized answer, a confidence score, an optional dissent line, "
        "and up to 5 cited sources. "
        "Use for questions that need real synthesis across sources: "
        "'how has X evolved', 'what are the tradeoffs between A and B', "
        "'what's the current state of Y', deep comparisons, reading the "
        "room on a topic the user just brought up. "
        "Do NOT use for single-fact lookups (use web_search, cheaper). "
        "Do NOT use for questions about the user (use recall). "
        "Do NOT use for small talk or ambient chatter. "
        "Do NOT use after web_search already gave a clear answer. "
        "Call once per turn. The answer is raw material, not a reply — "
        "read it, pick the one thread that matters, speak in Donna's voice."
    ),
    {
        "type": "object",
        "required": ["question"],
        "properties": {
            "question": {
                "type": "string",
                "description": (
                    "Specific research question in plain words. Include "
                    "comparison targets or scope if relevant."
                ),
            },
            "top_k": {
                "type": "integer",
                "description": "How many sources to rerank into the synthesis (default 8, max 12).",
            },
            "seed_url": {
                "type": "string",
                "description": (
                    "Optional URL to seed find_similar on. Use when the user "
                    "pasted a link and you want related pages."
                ),
            },
        },
    },
)
@traceable(name="donna.tool.research", run_type="tool")
async def research(args):
    from backend.web.pipeline import run_web_research

    question = str(args.get("question") or "").strip() if isinstance(args, dict) else ""
    if not question:
        return text_content("research: question is required.")
    top_k = args.get("top_k") or 8
    try:
        top_k = max(3, min(int(top_k), 12))
    except (TypeError, ValueError):
        top_k = 8
    seed_url = args.get("seed_url") if isinstance(args, dict) else None
    seed = seed_url.strip() if isinstance(seed_url, str) and seed_url.strip() else None

    try:
        answer, trace = await run_web_research(
            question, top_k=top_k, seed_url=seed
        )
    except Exception:
        logger.exception("research: pipeline failure")
        return text_content("research unavailable.")

    if not answer.answer:
        reason = (answer.metadata or {}).get("reason", "")
        suffix = f" {reason}" if reason else ""
        if trace.merged_count == 0:
            return text_content(f"research: no hits.{suffix}")
        return text_content(f"research unavailable.{suffix}")

    variant = (answer.metadata or {}).get("variant", "merged")
    rendered = _render_research_answer(
        answer.answer,
        list(answer.sources),
        confidence=answer.confidence,
        dissent=answer.dissent,
        variant=variant,
    )
    return text_content(rendered)
