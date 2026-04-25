"""Three-stage Gmail bootstrap: today-dense, 30d-important, 90d-aggregates.

Run once after connection.complete. Writes mirror rows; biography
synthesis runs after all stages complete (separate module).
"""
from __future__ import annotations

import logging

from backend.integrations.composio_client import ComposioClient
from backend.integrations.gmail_ingest import ingest_gmail_message
from config import settings

logger = logging.getLogger(__name__)


def _client() -> ComposioClient:
    return ComposioClient(api_key=settings.composio_api_key)


async def bootstrap_today_dense(user_id: str) -> int:
    """Read every message from the last ~24h, classify, ingest. Returns count."""
    client = _client()
    ids, _ = await client.list_gmail_message_ids(
        user_id=user_id, query="newer_than:1d", max_results=200
    )
    count = 0
    for mid in ids:
        try:
            msg = await client.fetch_gmail_message(
                user_id=user_id, message_id=mid, include_body=True
            )
        except Exception:
            logger.exception("bootstrap_today_dense: fetch failed mid=%s", mid)
            continue
        await ingest_gmail_message(user_id, msg)
        count += 1
    return count


async def bootstrap_30d_important(user_id: str) -> int:
    """Read IMPORTANT-labelled messages from the last ~30d, ingest. Returns count."""
    client = _client()
    ids, _ = await client.list_gmail_message_ids(
        user_id=user_id,
        query="is:important newer_than:30d",
        max_results=300,
    )
    count = 0
    for mid in ids:
        try:
            msg = await client.fetch_gmail_message(
                user_id=user_id, message_id=mid, include_body=True
            )
        except Exception:
            logger.exception(
                "bootstrap_30d_important: fetch failed mid=%s", mid
            )
            continue
        await ingest_gmail_message(user_id, msg)
        count += 1
    return count
