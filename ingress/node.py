"""Text-only ingress enrichment.

Takes a flat state dict (post-user_lookup) and augments it with:
  - reply_to_content / reply_to_role (from prior ChatMessage row)
  - url_contents (up to 3 URL excerpts fetched via httpx + BeautifulSoup)

Media-specific branches (voice transcription, image b64, document extraction)
are deferred to a later phase — they're stubbed as no-ops for the text MVP.
"""
from __future__ import annotations

import asyncio
import logging
import re

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select

from db.models import ChatMessage
from db.session import async_session

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_MAX_URLS = 3
_FETCH_TIMEOUT = 6
_EXCERPT_MAX = 2000


async def enrich(state: dict) -> dict:
    """Enrich state with reply context + URL excerpts. Mutates and returns state."""
    updates: dict = {}

    if state.get("reply_to_id"):
        reply = await _resolve_reply(state["user_id"], state["reply_to_id"])
        if reply:
            updates["reply_to_content"] = reply["content"]
            updates["reply_to_role"] = reply["role"]

    raw = state.get("raw_input") or ""
    urls = _URL_RE.findall(raw)[:_MAX_URLS]
    if urls:
        updates["url_contents"] = await _fetch_urls(urls)

    state.update(updates)
    return state


async def _resolve_reply(user_id: str, platform_message_id: str) -> dict | None:
    try:
        async with async_session() as session:
            result = await session.execute(
                select(ChatMessage)
                .where(ChatMessage.wa_message_id == platform_message_id)
                .limit(1)
            )
            msg = result.scalar_one_or_none()
            if msg is None:
                return None
            return {"content": (msg.content or "")[:500], "role": msg.role}
    except Exception:
        logger.exception("ingress: _resolve_reply failed for %s", platform_message_id[:16])
        return None


async def _fetch_urls(urls: list[str]) -> list[dict]:
    async with httpx.AsyncClient(
        timeout=_FETCH_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; DonnaBot/1.0)"},
    ) as client:
        tasks = [_fetch_one(client, url) for url in urls]
        return await asyncio.gather(*tasks)


async def _fetch_one(client: httpx.AsyncClient, url: str) -> dict:
    domain = ""
    try:
        domain = httpx.URL(url).host or ""
    except Exception:
        pass
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else None
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = " ".join(soup.get_text(" ", strip=True).split())[:_EXCERPT_MAX]
        return {"url": url, "domain": domain, "title": title, "text": text, "status": "ok", "error": None}
    except Exception as exc:
        return {"url": url, "domain": domain, "title": None, "text": None, "status": "error", "error": str(exc)[:200]}
