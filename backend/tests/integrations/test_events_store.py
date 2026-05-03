"""Tests for the generic integration_events landing zone."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.integrations.events_store import (
    record_event,
    source_ref_for,
    toolkit_for_trigger_slug,
)
from db.models import IntegrationEvent


def test_toolkit_for_trigger_slug_known() -> None:
    assert toolkit_for_trigger_slug("SLACK_NEW_MESSAGE") == "slack"
    assert toolkit_for_trigger_slug("NOTION_PAGE_UPDATED") == "notion"
    assert toolkit_for_trigger_slug("LINEAR_ISSUE_CREATED") == "linear"
    assert toolkit_for_trigger_slug("GITHUB_PULL_REQUEST_OPENED") == "github"
    assert toolkit_for_trigger_slug("GMAIL_NEW_GMAIL_MESSAGE") == "gmail"
    assert (
        toolkit_for_trigger_slug(
            "GOOGLECALENDAR_GOOGLE_CALENDAR_EVENT_CREATED_TRIGGER"
        )
        == "calendar"
    )


def test_toolkit_for_trigger_slug_unknown_falls_back() -> None:
    assert toolkit_for_trigger_slug("SOMETHING_NEW_THING") == "something"
    assert toolkit_for_trigger_slug("") == "unknown"


def test_source_ref_slack_uses_channel_and_ts() -> None:
    assert source_ref_for(
        "slack", {"channel": "C123", "ts": "1700000000.000100"}
    ) == "C123:1700000000.000100"


def test_source_ref_notion_prefers_page_id() -> None:
    assert (
        source_ref_for("notion", {"page": {"id": "abc-def"}})
        == "page:abc-def"
    )


def test_source_ref_linear_uses_identifier() -> None:
    assert source_ref_for(
        "linear", {"issue": {"identifier": "ENG-123"}}
    ) == "ENG-123"


def test_source_ref_falls_back_to_id() -> None:
    assert source_ref_for("unknown", {"id": "xyz"}) == "xyz"
    assert source_ref_for("unknown", {}) is None


@pytest.mark.asyncio
async def test_record_event_inserts_row(db) -> None:
    inserted = await record_event(
        user_id="u1",
        trigger_slug="SLACK_NEW_MESSAGE",
        inner={"channel": "C1", "ts": "111.001", "text": "hi"},
    )
    assert inserted is True

    async with db() as s:
        row = (
            await s.execute(
                select(IntegrationEvent).where(IntegrationEvent.user_id == "u1")
            )
        ).scalar_one()
    assert row.toolkit == "slack"
    assert row.trigger_slug == "SLACK_NEW_MESSAGE"
    assert row.source_ref == "C1:111.001"
    assert row.payload == {"channel": "C1", "ts": "111.001", "text": "hi"}
    assert row.processed_at is None


@pytest.mark.asyncio
async def test_record_event_dedupes_on_source_ref(db) -> None:
    """Composio retries the same envelope; we should insert once."""
    payload = {"channel": "C1", "ts": "222.002", "text": "retry"}
    first = await record_event(
        user_id="u1",
        trigger_slug="SLACK_NEW_MESSAGE",
        inner=payload,
    )
    second = await record_event(
        user_id="u1",
        trigger_slug="SLACK_NEW_MESSAGE",
        inner=payload,
    )
    assert first is True
    assert second is False  # deduped

    async with db() as s:
        rows = (
            await s.execute(
                select(IntegrationEvent).where(IntegrationEvent.user_id == "u1")
            )
        ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_record_event_no_source_ref_inserts_each_time(db) -> None:
    """When the toolkit doesn't expose an id, we still insert (rare path)."""
    inner = {"text": "no id field"}
    a = await record_event(
        user_id="u1",
        trigger_slug="WEIRD_TOOLKIT_EVENT",
        inner=inner,
    )
    b = await record_event(
        user_id="u1",
        trigger_slug="WEIRD_TOOLKIT_EVENT",
        inner=inner,
    )
    assert a is True
    assert b is True

    async with db() as s:
        rows = (
            await s.execute(
                select(IntegrationEvent).where(IntegrationEvent.user_id == "u1")
            )
        ).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_record_event_rejects_missing_user_or_slug(db) -> None:
    assert await record_event(user_id="", trigger_slug="X", inner={}) is False
    assert await record_event(user_id="u1", trigger_slug="", inner={}) is False
