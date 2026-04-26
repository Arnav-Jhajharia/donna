"""Per-mime-type extractors for the deep-ingest pipeline.

Each extractor exposes ``async def extract(file_bytes, *, mime_type, filename)
-> ExtractedDocument | None``. Returning ``None`` means the file type is
unsupported or extraction failed gracefully — the orchestrator skips it
and logs at info level. Never raise from an extractor; degrade.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractedDocument:
    """Output of any extractor.

    ``text`` is the full plaintext used for chunking and search. ``title``
    is best-effort (filename for PDFs, leading caption for images, empty
    for unknown types). ``page_count`` is informational only — used in
    the Observation summary so the model can quote it.
    """

    text: str
    title: str
    page_count: int = 0
    extra_metadata: dict | None = None
