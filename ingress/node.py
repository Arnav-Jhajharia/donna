"""Ingress enrichment.

Takes a flat state dict (post-user_lookup) and augments it with:
  - raw_input from voice notes via Deepgram STT (when state carries voice bytes)
  - _inbound_modality flag so the brain knows the message arrived as voice
  - reply_to_content / reply_to_role (from prior ChatMessage row)
  - url_contents (up to 3 URL excerpts fetched via httpx + BeautifulSoup)
  - background document/image deep-ingest (PDF text + image caption/OCR)
    fired as a fire-and-forget task so the brain turn isn't blocked
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
    """Enrich state with STT, reply context, and URL excerpts. Mutates and returns state."""
    updates: dict = {}

    transcript = await _maybe_transcribe(state)
    if transcript:
        updates["raw_input"] = transcript
        updates["_inbound_modality"] = "voice"

    if state.get("reply_to_id"):
        reply = await _resolve_reply(state["user_id"], state["reply_to_id"])
        if reply:
            updates["reply_to_content"] = reply["content"]
            updates["reply_to_role"] = reply["role"]

    raw = updates.get("raw_input") or state.get("raw_input") or ""
    urls = _URL_RE.findall(raw)[:_MAX_URLS]
    if urls:
        updates["url_contents"] = await _fetch_urls(urls)

    _maybe_dispatch_attachment_ingest(state)

    state.update(updates)
    return state


def _maybe_dispatch_attachment_ingest(state: dict) -> None:
    """Fire deep-ingest for documents/images as a background task.

    We do NOT await: chunking + Haiku vision can take many seconds, and
    the brain turn must not stall on it. The orchestrator is fully
    self-contained (own DB session, own logging, own error handling)
    so a crash there can't cascade into the response path.

    Voice notes are intentionally skipped: ``_maybe_transcribe`` already
    converts them into ``raw_input`` so they enter as text.
    """
    payload = state.get("_ingress_payload")
    if payload is None:
        return
    user_id = state.get("user_id")
    if not user_id:
        return

    document = getattr(payload, "document", None)
    image = getattr(payload, "image", None)
    caption = state.get("raw_input") or ""
    message_id = state.get("platform_message_id") or getattr(
        payload, "platform_message_id", None
    )

    target = None
    if document is not None and getattr(document, "file_bytes", None):
        target = (
            getattr(document, "file_bytes", b""),
            getattr(document, "mime_type", "") or "application/octet-stream",
            getattr(document, "filename", "") or "document",
        )
    elif image is not None and getattr(image, "file_bytes", None):
        target = (
            getattr(image, "file_bytes", b""),
            getattr(image, "mime_type", "") or "image/jpeg",
            "image",
        )
    if target is None:
        return

    file_bytes, mime, filename = target
    asyncio.create_task(
        _ingest_in_background(
            user_id=user_id,
            file_bytes=file_bytes,
            mime_type=mime,
            filename=filename,
            caption=caption or None,
            message_id=message_id,
        ),
        name="document_ingest",
    )


async def _ingest_in_background(
    *,
    user_id: str,
    file_bytes: bytes,
    mime_type: str,
    filename: str,
    caption: str | None,
    message_id: str | None,
) -> None:
    try:
        from backend.memory.ingest.documents import ingest_attachment

        result = await ingest_attachment(
            user_id,
            file_bytes=file_bytes,
            mime_type=mime_type,
            filename=filename,
            caption=caption,
            message_id=message_id,
        )
    except Exception:
        logger.exception(
            "ingest: background dispatch failed user=%s file=%s",
            user_id[:8], (filename or "")[:40],
        )
        return
    if result is None:
        logger.info(
            "ingest: skipped user=%s file=%s mime=%s (no extractor)",
            user_id[:8], (filename or "")[:40], mime_type,
        )
        return
    logger.info(
        "ingest: done user=%s sha=%s chunks=%d obs=%s deduped=%s",
        user_id[:8],
        result.sha256[:10],
        result.chunk_count,
        result.observation_id or "?",
        result.deduped,
    )


async def _maybe_transcribe(state: dict) -> str:
    """Run STT when the inbound payload carries voice bytes. Empty on miss/error."""
    payload = state.get("_ingress_payload")
    voice = getattr(payload, "voice", None) if payload is not None else None
    if voice is None:
        return ""
    file_bytes = getattr(voice, "file_bytes", None)
    if not file_bytes:
        return ""
    mime = getattr(voice, "mime_type", "audio/ogg") or "audio/ogg"
    try:
        from ingress.stt import transcribe_voice

        return await transcribe_voice(file_bytes, mime_type=mime)
    except Exception:
        logger.exception("ingress: STT raised unexpectedly")
        return ""


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
