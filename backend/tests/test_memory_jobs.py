from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from backend.memory.jobs import temporal_refresh
from backend.memory.synthesis.temporal_brief import TemporalEvidence, TemporalItem
from scripts.export_temporal_eval_traces import anonymize_user_id, evidence_to_record, redact_text


def test_refresh_job_dry_run_uses_active_selection(monkeypatch):
    async def fake_select(**kwargs):
        return ["u1", "u2"]

    monkeypatch.setattr(temporal_refresh, "select_active_user_ids", fake_select)

    report = asyncio.run(temporal_refresh.refresh_active_user_briefs(dry_run=True))

    assert report.selected == 2
    assert report.refreshed == 0
    assert report.skipped == 2
    assert [outcome.user_id for outcome in report.outcomes] == ["u1", "u2"]


def test_run_forever_ticks_and_emits(monkeypatch):
    """run_forever should call refresh_active_user_briefs each tick and emit
    a memory.brief_refresh.tick event summarizing the outcome."""
    from donna_runtime import observability

    ticks: list[dict] = []
    emitted: list[tuple[str, dict]] = []

    async def fake_refresh(**kwargs):
        ticks.append(dict(kwargs))
        return temporal_refresh.RefreshReport(
            dry_run=False,
            active_within_days=kwargs.get("active_within_days", 14),
            selected=3,
            refreshed=2,
            failed=1,
            skipped=0,
            outcomes=[],
        )

    def fake_emit(event, **payload):
        emitted.append((event, payload))

    monkeypatch.setattr(temporal_refresh, "refresh_active_user_briefs", fake_refresh)
    monkeypatch.setattr(observability, "emit", fake_emit)

    async def _drive():
        task = asyncio.create_task(
            temporal_refresh.run_forever(poll_interval_s=0.01, active_within_days=7)
        )
        # let at least one tick complete
        for _ in range(50):
            await asyncio.sleep(0.005)
            if ticks:
                break
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_drive())

    assert len(ticks) >= 1
    assert ticks[0]["active_within_days"] == 7
    brief_events = [e for e in emitted if e[0] == "memory.brief_refresh.tick"]
    assert brief_events, f"expected brief_refresh.tick, got {[e[0] for e in emitted]}"
    payload = brief_events[0][1]
    assert payload["selected"] == 3
    assert payload["refreshed"] == 2
    assert payload["failed"] == 1


def test_run_forever_survives_tick_exception(monkeypatch):
    """A failing tick must be logged but never break the loop."""
    calls: list[int] = []

    async def fake_refresh(**kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return temporal_refresh.RefreshReport(
            dry_run=False,
            active_within_days=14,
            selected=0, refreshed=0, failed=0, skipped=0, outcomes=[],
        )

    monkeypatch.setattr(temporal_refresh, "refresh_active_user_briefs", fake_refresh)

    async def _drive():
        task = asyncio.create_task(
            temporal_refresh.run_forever(poll_interval_s=0.01)
        )
        for _ in range(80):
            await asyncio.sleep(0.005)
            if len(calls) >= 2:
                break
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_drive())
    assert len(calls) >= 2, f"run_forever stopped after exception, calls={len(calls)}"


def test_anonymized_trace_export_redacts_obvious_pii():
    text = "email me at arnav@example.com or call +1 555 123 4567 https://example.com @arnav"

    redacted = redact_text(text)

    assert "arnav@example.com" not in redacted
    assert "555 123 4567" not in redacted
    assert "https://example.com" not in redacted
    assert "@arnav" not in redacted
    assert "<email>" in redacted
    assert "<phone>" in redacted
    assert "<url>" in redacted
    assert "<handle>" in redacted


def test_evidence_to_record_hashes_user_and_preserves_structure():
    evidence = TemporalEvidence(
        user_id="real-user-id",
        now=datetime(2026, 4, 23, 12, 0, tzinfo=timezone.utc),
        timezone="Asia/Singapore",
        chat_messages=[
            TemporalItem(
                kind="chat",
                text="message arnav@example.com",
                at=datetime(2026, 4, 22, 10, 0, tzinfo=timezone.utc),
                role="user",
            )
        ],
    )

    record = evidence_to_record(evidence)

    assert record["user_hash"] == anonymize_user_id("real-user-id")
    assert "real-user-id" not in str(record)
    assert record["timezone"] == "Asia/Singapore"
    assert record["items"][0]["kind"] == "chat"
    assert "<email>" in record["items"][0]["text"]
