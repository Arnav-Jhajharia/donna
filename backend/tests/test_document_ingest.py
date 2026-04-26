"""Document deep-ingest unit tests.

Covers chunking, summary builder, extractor dispatch, and the public
``ingest_attachment`` happy path with all backends faked. End-to-end
verification (real Supermemory + Graphiti + Haiku) is run from the
verify_phase2.py harness against Kai.
"""
from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.memory.ingest import documents
from backend.memory.ingest.extractors import ExtractedDocument


def test_chunk_text_returns_single_chunk_for_short_input():
    chunks = documents._chunk_text("a short paragraph.")
    assert chunks == ["a short paragraph."]


def test_chunk_text_splits_long_input_with_overlap():
    text = ("paragraph one is here.\n\n" * 200).strip()
    chunks = documents._chunk_text(text)
    assert len(chunks) > 1
    # Each chunk under target plus overlap.
    for chunk in chunks:
        assert len(chunk) <= documents._CHUNK_TARGET_CHARS + 50
    # Overlap: end of chunk N should appear at start of chunk N+1.
    for prev, nxt in zip(chunks, chunks[1:]):
        tail = prev[-documents._CHUNK_OVERLAP_CHARS // 2 :]
        # Soft check: at least *some* tail words appear in the next
        # chunk's first half.
        head = nxt[: len(nxt) // 2]
        assert any(token in head for token in tail.split() if len(token) > 3)


def test_chunk_text_caps_chunks_per_doc():
    text = "x" * (documents._CHUNK_TARGET_CHARS * 200)
    chunks = documents._chunk_text(text)
    assert len(chunks) <= documents._CHUNK_MAX_PER_DOC


def test_chunk_text_returns_empty_for_empty_input():
    assert documents._chunk_text("") == []
    assert documents._chunk_text("   ") == []


def test_build_summary_includes_caption_and_chunk_count():
    extracted = ExtractedDocument(
        text="line one\nline two\nline three",
        title="resume",
        page_count=2,
    )
    summary = documents._build_summary(extracted, caption="my updated cv", chunk_count=3)
    assert "caption: my updated cv" in summary
    assert "title: resume" in summary
    assert "pages: 2" in summary
    assert "chunks: 3" in summary
    assert "line one" in summary


def test_build_summary_omits_empty_caption():
    extracted = ExtractedDocument(text="content", title="doc", page_count=0)
    summary = documents._build_summary(extracted, caption=None, chunk_count=1)
    assert "caption:" not in summary
    assert "title: doc" in summary


@pytest.mark.asyncio
async def test_extract_dispatches_to_pdf_for_pdf_mime():
    captured = {}

    async def fake_pdf_extract(file_bytes, *, mime_type, filename):
        captured["pdf"] = (mime_type, filename)
        return ExtractedDocument(text="pdf body", title="cv", page_count=1)

    async def fake_image_extract(file_bytes, *, mime_type, filename):
        captured["image"] = (mime_type, filename)
        return None

    with patch.object(documents.pdf_extractor, "extract", fake_pdf_extract), patch.object(
        documents.image_extractor, "extract", fake_image_extract
    ):
        out = await documents._extract(
            b"%PDF-1.4 fake bytes",
            mime_type="application/pdf",
            filename="cv.pdf",
        )

    assert out is not None
    assert captured.get("pdf") == ("application/pdf", "cv.pdf")
    assert "image" not in captured


@pytest.mark.asyncio
async def test_extract_dispatches_to_image_for_image_mime():
    captured = {}

    async def fake_pdf_extract(file_bytes, *, mime_type, filename):
        captured["pdf"] = True
        return None

    async def fake_image_extract(file_bytes, *, mime_type, filename):
        captured["image"] = (mime_type, filename)
        return ExtractedDocument(text="a screenshot of slack.", title="image", page_count=1)

    with patch.object(documents.pdf_extractor, "extract", fake_pdf_extract), patch.object(
        documents.image_extractor, "extract", fake_image_extract
    ):
        out = await documents._extract(
            b"\xff\xd8\xff\xe0 jpeg",
            mime_type="image/jpeg",
            filename="photo.jpg",
        )

    assert out is not None
    assert captured.get("image") == ("image/jpeg", "photo.jpg")
    assert "pdf" not in captured


@pytest.mark.asyncio
async def test_extract_returns_none_for_unknown_mime():
    out = await documents._extract(
        b"unknown bytes",
        mime_type="application/zip",
        filename="archive.zip",
    )
    assert out is None


@pytest.mark.asyncio
async def test_ingest_attachment_returns_none_for_empty_bytes():
    out = await documents.ingest_attachment(
        "user-1",
        file_bytes=b"",
        mime_type="application/pdf",
        filename="empty.pdf",
    )
    assert out is None


@pytest.mark.asyncio
async def test_ingest_attachment_dedupes_when_prior_observation_exists():
    sha = hashlib.sha256(b"hello world").hexdigest()
    prior = SimpleNamespace(
        id="obs-prior",
        fields={
            "sha256": sha,
            "filename": "cv.pdf",
            "title": "cv",
            "summary": "prior summary",
            "chunk_count": 4,
        },
    )

    async def fake_find_prior(user_id, sha_arg):
        assert sha_arg == sha
        return prior

    async def fake_extract(file_bytes, *, mime_type, filename):
        raise AssertionError("dedupe path should short-circuit before extract")

    with patch.object(documents, "_find_prior_ingest", fake_find_prior), patch.object(
        documents, "_extract", fake_extract
    ):
        out = await documents.ingest_attachment(
            "user-1",
            file_bytes=b"hello world",
            mime_type="application/pdf",
            filename="cv.pdf",
        )

    assert out is not None
    assert out.deduped is True
    assert out.observation_id == "obs-prior"
    assert out.chunk_count == 4
    assert out.title == "cv"


@pytest.mark.asyncio
async def test_ingest_attachment_happy_path_writes_chunks_and_observation():
    """End-to-end happy path with all backends faked."""
    extracted = ExtractedDocument(
        text="line one. line two. line three.",
        title="resume",
        page_count=1,
    )

    async def fake_find_prior(user_id, sha_arg):
        return None

    async def fake_extract(file_bytes, *, mime_type, filename):
        return extracted

    chunk_calls: list[dict] = []
    observation_calls: list[dict] = []
    graph_calls: list[dict] = []

    async def fake_persist_chunks(user_id, **kwargs):
        chunk_calls.append({"user_id": user_id, **kwargs})
        return ["sm-chunk-0"]

    async def fake_log_summary(user_id, **kwargs):
        observation_calls.append({"user_id": user_id, **kwargs})
        return "obs-new"

    async def fake_push(user_id, *, summary, title):
        graph_calls.append({"user_id": user_id, "summary": summary, "title": title})

    with patch.object(documents, "_find_prior_ingest", fake_find_prior), patch.object(
        documents, "_extract", fake_extract
    ), patch.object(
        documents, "_persist_chunks", fake_persist_chunks
    ), patch.object(
        documents, "_log_summary_observation", fake_log_summary
    ), patch.object(
        documents, "_push_to_graph", fake_push
    ):
        out = await documents.ingest_attachment(
            "user-1",
            file_bytes=b"resume bytes",
            mime_type="application/pdf",
            filename="cv.pdf",
            caption="updated resume",
        )

    assert out is not None
    assert out.deduped is False
    assert out.observation_id == "obs-new"
    assert out.chunk_count == 1  # short text -> single chunk
    assert out.title == "resume"
    assert chunk_calls and chunk_calls[0]["chunks"] == ["line one. line two. line three."]
    assert observation_calls and observation_calls[0]["chunk_count"] == 1
    assert graph_calls and "resume" in graph_calls[0]["title"]


@pytest.mark.asyncio
async def test_ingest_attachment_logs_unsupported_for_unknown_type():
    async def fake_find_prior(user_id, sha_arg):
        return None

    log_calls: list[dict] = []

    async def fake_log_observation(*, user_id, type, fields, tags, raw, event_time, confidence):
        log_calls.append({"type": type, "fields": fields})
        return {"status": "ok", "payload": {"id": "obs-unsup"}}

    with patch.object(documents, "_find_prior_ingest", fake_find_prior), patch.object(
        documents, "log_observation", fake_log_observation
    ):
        out = await documents.ingest_attachment(
            "user-1",
            file_bytes=b"random zip bytes",
            mime_type="application/zip",
            filename="archive.zip",
        )

    assert out is not None
    assert out.chunk_count == 0
    assert out.observation_id == "obs-unsup"
    assert "unsupported type" in out.summary
    assert log_calls and log_calls[0]["type"] == "document_received"
    assert log_calls[0]["fields"]["chunk_count"] == 0
