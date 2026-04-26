"""PDF text extractor backed by pypdf.

Handles text-bearing PDFs (resumes, contracts, slide decks, articles).
Scanned/image-only PDFs return empty text — they need OCR, which is
out of scope for the first pass; the orchestrator falls back to logging
a ``document_received`` observation with no chunks.
"""
from __future__ import annotations

import io
import logging

from . import ExtractedDocument

logger = logging.getLogger(__name__)

_MAX_PAGES = 50
_PAGE_SEPARATOR = "\n\n"


async def extract(
    file_bytes: bytes, *, mime_type: str, filename: str
) -> ExtractedDocument | None:
    """Pull plaintext from a PDF. Returns None on unrecoverable failure."""
    if not file_bytes:
        return None
    if not (mime_type.startswith("application/pdf") or filename.lower().endswith(".pdf")):
        return None
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.warning("pypdf not installed — skipping PDF ingest")
        return None

    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except Exception:
        logger.exception("pdf extract: PdfReader failed for %s", filename)
        return None

    pages: list[str] = []
    page_count = 0
    for index, page in enumerate(reader.pages):
        if index >= _MAX_PAGES:
            logger.info(
                "pdf extract: %s exceeded %d pages, truncating",
                filename, _MAX_PAGES,
            )
            break
        try:
            text = page.extract_text() or ""
        except Exception:
            logger.exception("pdf extract: page %d of %s failed", index, filename)
            text = ""
        page_count += 1
        text = text.strip()
        if text:
            pages.append(text)

    body = _PAGE_SEPARATOR.join(pages).strip()
    title = (filename or "document").rsplit(".", 1)[0]
    return ExtractedDocument(
        text=body,
        title=title,
        page_count=page_count,
        extra_metadata={"format": "pdf"},
    )
