"""Document deep-ingest orchestrator.

Single public entry: ``ingest_attachment(user_id, *, file_bytes, mime_type,
filename, source="whatsapp", caption=None, message_id=None)``.

Pipeline:

1. Compute SHA-256. Idempotency check: if an Observation already exists
   with ``type="document_received"`` and matching ``sha256`` for this
   user, no-op and return the prior ingest summary.
2. Pick an extractor by mime/filename (PDF / image). Voice notes are
   already transcribed at ingress, so we don't re-ingest them here.
3. Chunk the extracted text with a sliding window.
4. Persist each chunk to Supermemory via ``add_episode`` with rich
   metadata (sha256, filename, chunk_index, kind="document_chunk")
   so existing recall fans across them.
5. Log a single Observation of ``type="document_received"`` with a
   short summary so the doc surfaces in TODAY block + temporal context.
6. Push the summary into Graphiti via ``ingest_episode`` so entity
   extraction picks up names/places/dates and the next ``recall`` query
   pulls the doc edge.

Failure mode is "best effort." Any step that fails logs and continues
so we never drop the user's file silently with zero record. Worst case
is a Observation with no chunks — still recallable by mention.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from backend.db.models import Observation
from backend.db.session import async_session
from backend.memory.clients.supermemory import get_memory_client
from backend.memory.ingest.extractors import ExtractedDocument
from backend.memory.ingest.extractors import image as image_extractor
from backend.memory.ingest.extractors import pdf as pdf_extractor
from backend.memory.tools.log_observation import log_observation

logger = logging.getLogger(__name__)

_CHUNK_TARGET_CHARS = 1800
_CHUNK_OVERLAP_CHARS = 200
_CHUNK_MAX_PER_DOC = 50
_SUMMARY_MAX_CHARS = 360


@dataclass(frozen=True)
class IngestResult:
    sha256: str
    chunk_count: int
    observation_id: str | None
    summary: str
    title: str
    deduped: bool = False


async def ingest_attachment(
    user_id: str,
    *,
    file_bytes: bytes,
    mime_type: str,
    filename: str,
    source: str = "whatsapp",
    caption: str | None = None,
    message_id: str | None = None,
) -> IngestResult | None:
    """Run the full ingest pipeline for one attachment. Returns None for
    unsupported types or empty inputs."""
    if not file_bytes:
        return None

    sha = hashlib.sha256(file_bytes).hexdigest()

    prior = await _find_prior_ingest(user_id, sha)
    if prior is not None:
        logger.info(
            "ingest: dedupe hit user=%s sha=%s obs=%s",
            user_id[:8], sha[:10], prior.id,
        )
        fields = prior.fields or {}
        return IngestResult(
            sha256=sha,
            chunk_count=int(fields.get("chunk_count", 0)),
            observation_id=prior.id,
            summary=str(fields.get("summary") or ""),
            title=str(fields.get("title") or filename),
            deduped=True,
        )

    extracted = await _extract(
        file_bytes, mime_type=mime_type, filename=filename
    )
    if extracted is None:
        # Unknown type. Still log the Observation so the user sees we
        # received the file — recall by filename will work, full-text
        # won't.
        return await _log_unsupported(
            user_id,
            sha=sha,
            mime_type=mime_type,
            filename=filename,
            caption=caption,
            message_id=message_id,
            source=source,
        )

    chunks = _chunk_text(extracted.text)

    chunk_ids: list[str] = []
    if chunks:
        chunk_ids = await _persist_chunks(
            user_id,
            sha=sha,
            extracted=extracted,
            chunks=chunks,
            mime_type=mime_type,
            filename=filename,
            source=source,
            caption=caption,
            message_id=message_id,
        )

    summary = _build_summary(extracted, caption=caption, chunk_count=len(chunks))
    obs_id = await _log_summary_observation(
        user_id,
        sha=sha,
        summary=summary,
        title=extracted.title,
        chunk_count=len(chunks),
        chunk_ids=chunk_ids,
        mime_type=mime_type,
        filename=filename,
        page_count=extracted.page_count,
        caption=caption,
        message_id=message_id,
        source=source,
    )
    await _push_to_graph(user_id, summary=summary, title=extracted.title)
    return IngestResult(
        sha256=sha,
        chunk_count=len(chunks),
        observation_id=obs_id,
        summary=summary,
        title=extracted.title,
    )


# --- extractor dispatch ------------------------------------------------------


async def _extract(
    file_bytes: bytes, *, mime_type: str, filename: str
) -> ExtractedDocument | None:
    mime = (mime_type or "").lower()
    name = (filename or "").lower()

    if mime.startswith("application/pdf") or name.endswith(".pdf"):
        return await pdf_extractor.extract(
            file_bytes, mime_type=mime, filename=filename
        )

    if mime.startswith("image/") or name.endswith(
        (".jpg", ".jpeg", ".png", ".webp", ".gif")
    ):
        return await image_extractor.extract(
            file_bytes, mime_type=mime, filename=filename
        )

    return None


# --- chunking ----------------------------------------------------------------


def _chunk_text(text: str) -> list[str]:
    """Sliding-window chunking on character boundaries.

    Token-aware chunking would be marginally better but pulls a
    tokenizer dep. Character windows on prose are within 10% of
    optimal and have zero footprint.
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= _CHUNK_TARGET_CHARS:
        return [text]

    out: list[str] = []
    start = 0
    while start < len(text) and len(out) < _CHUNK_MAX_PER_DOC:
        end = min(start + _CHUNK_TARGET_CHARS, len(text))
        # Try to end the chunk on a paragraph boundary if one is nearby.
        if end < len(text):
            tail = text.rfind("\n\n", start, end)
            if tail != -1 and tail - start > _CHUNK_TARGET_CHARS // 2:
                end = tail
        chunk = text[start:end].strip()
        if chunk:
            out.append(chunk)
        if end >= len(text):
            break
        start = max(end - _CHUNK_OVERLAP_CHARS, start + 1)
    return out


# --- persistence -------------------------------------------------------------


async def _persist_chunks(
    user_id: str,
    *,
    sha: str,
    extracted: ExtractedDocument,
    chunks: list[str],
    mime_type: str,
    filename: str,
    source: str,
    caption: str | None,
    message_id: str | None,
) -> list[str]:
    client = get_memory_client()
    if not client.available:
        logger.info(
            "ingest: supermemory unavailable, chunks not persisted user=%s",
            user_id[:8],
        )
        return []

    chunk_ids: list[str] = []
    base_metadata = {
        "kind": "document_chunk",
        "sha256": sha,
        "filename": filename,
        "title": extracted.title,
        "mime_type": mime_type,
        "source": source,
        "page_count": extracted.page_count,
    }
    if caption:
        base_metadata["caption"] = caption[:280]
    if message_id:
        base_metadata["message_id"] = message_id
    extras = extracted.extra_metadata or {}
    for k, v in extras.items():
        base_metadata.setdefault(k, v)

    for index, chunk in enumerate(chunks):
        metadata = dict(base_metadata)
        metadata["chunk_index"] = index
        metadata["chunk_count"] = len(chunks)
        try:
            chunk_id = await client.add_episode(
                user_id,
                content=chunk,
                message_type="document",
                metadata=metadata,
            )
        except Exception:
            logger.exception(
                "ingest: chunk %d of %s failed user=%s",
                index, filename, user_id[:8],
            )
            continue
        if chunk_id:
            chunk_ids.append(chunk_id)
    return chunk_ids


async def _find_prior_ingest(user_id: str, sha: str) -> Observation | None:
    """Idempotency check via Postgres Observation row."""
    try:
        async with async_session() as session:
            row = (
                await session.execute(
                    select(Observation)
                    .where(Observation.user_id == user_id)
                    .where(Observation.type == "document_received")
                    .where(Observation.fields["sha256"].astext == sha)
                    .order_by(Observation.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            return row
    except Exception:
        logger.exception(
            "ingest: prior-ingest lookup failed user=%s sha=%s",
            user_id[:8], sha[:10],
        )
        return None


def _build_summary(
    extracted: ExtractedDocument, *, caption: str | None, chunk_count: int
) -> str:
    head = extracted.text.strip().splitlines()
    leading = " ".join(line.strip() for line in head[:6] if line.strip())
    leading = leading[:_SUMMARY_MAX_CHARS]
    parts: list[str] = []
    if caption:
        parts.append(f"caption: {caption.strip()[:160]}")
    parts.append(f"title: {extracted.title}")
    if extracted.page_count:
        parts.append(f"pages: {extracted.page_count}")
    parts.append(f"chunks: {chunk_count}")
    if leading:
        parts.append(f"opening: {leading}")
    return " | ".join(parts)


async def _log_summary_observation(
    user_id: str,
    *,
    sha: str,
    summary: str,
    title: str,
    chunk_count: int,
    chunk_ids: list[str],
    mime_type: str,
    filename: str,
    page_count: int,
    caption: str | None,
    message_id: str | None,
    source: str,
) -> str | None:
    fields: dict[str, Any] = {
        "sha256": sha,
        "filename": filename,
        "title": title,
        "mime_type": mime_type,
        "summary": summary,
        "chunk_count": chunk_count,
        "page_count": page_count,
        "source": source,
    }
    if caption:
        fields["caption"] = caption
    if message_id:
        fields["message_id"] = message_id
    if chunk_ids:
        fields["sm_chunk_ids"] = chunk_ids[:10]

    try:
        result = await log_observation(
            user_id=user_id,
            type="document_received",
            fields=fields,
            tags={"source": source, "ingest": "v2"},
            raw=None,
            event_time=datetime.now(timezone.utc),
            confidence=1.0,
        )
    except Exception:
        logger.exception("ingest: log_observation raised user=%s", user_id[:8])
        return None
    if result.get("status") != "ok":
        logger.warning(
            "ingest: log_observation degraded user=%s status=%s",
            user_id[:8], result.get("status"),
        )
        return None
    payload = result.get("payload")
    if isinstance(payload, dict):
        return payload.get("id")
    return None


async def _log_unsupported(
    user_id: str,
    *,
    sha: str,
    mime_type: str,
    filename: str,
    caption: str | None,
    message_id: str | None,
    source: str,
) -> IngestResult:
    fields: dict[str, Any] = {
        "sha256": sha,
        "filename": filename,
        "mime_type": mime_type,
        "summary": f"unsupported type ({mime_type or 'unknown'}) — recorded receipt only",
        "chunk_count": 0,
        "source": source,
    }
    if caption:
        fields["caption"] = caption
    if message_id:
        fields["message_id"] = message_id
    obs_id = None
    try:
        result = await log_observation(
            user_id=user_id,
            type="document_received",
            fields=fields,
            tags={"source": source, "ingest": "v2", "supported": "false"},
            raw=None,
            event_time=datetime.now(timezone.utc),
            confidence=1.0,
        )
        if result.get("status") == "ok":
            payload = result.get("payload")
            if isinstance(payload, dict):
                obs_id = payload.get("id")
    except Exception:
        logger.exception(
            "ingest: unsupported-type log failed user=%s", user_id[:8]
        )
    return IngestResult(
        sha256=sha,
        chunk_count=0,
        observation_id=obs_id,
        summary=fields["summary"],
        title=filename,
    )


async def _push_to_graph(
    user_id: str, *, summary: str, title: str
) -> None:
    """Best-effort Graphiti episode so entity extraction picks up names."""
    try:
        from backend.memory.clients.graphiti import ingest_episode

        episode_text = f"Document received: {title}. {summary}"
        await ingest_episode(
            user_id,
            content=episode_text,
            metadata={"kind": "document_received", "title": title},
        )
    except Exception:
        logger.exception(
            "ingest: graphiti push failed user=%s title=%s",
            user_id[:8], title[:40],
        )
