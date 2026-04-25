"""Three-stage Gmail bootstrap: today-dense, 30d-important, 90d-aggregates.

Run once after connection.complete. Writes mirror rows; biography
synthesis runs after all stages complete (separate module).
"""
from __future__ import annotations

import logging
from collections import Counter

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


async def bootstrap_90d_aggregates(
    user_id: str, top_n: int = 50
) -> list[dict]:
    """Return top-N senders in last 90d (count + sample subjects).

    Metadata-only. Does NOT write to email_messages mirror; returned in
    memory for biography synthesis to consume immediately.
    """
    client = _client()
    ids, page_token = await client.list_gmail_message_ids(
        user_id=user_id, query="newer_than:90d", max_results=500
    )
    while page_token:
        more, page_token = await client.list_gmail_message_ids(
            user_id=user_id,
            query="newer_than:90d",
            max_results=500,
            page_token=page_token,
        )
        ids.extend(more)
        if len(ids) > 5000:
            break  # safety cap

    counter: Counter = Counter()
    samples: dict[str, list[str]] = {}
    for mid in ids:
        try:
            msg = await client.fetch_gmail_message(
                user_id=user_id, message_id=mid, include_body=False
            )
        except Exception:
            continue
        addr = msg.from_address
        counter[addr] += 1
        if len(samples.setdefault(addr, [])) < 3 and msg.subject:
            samples[addr].append(msg.subject)

    return [
        {
            "from_address": addr,
            "count": n,
            "sample_subjects": samples.get(addr, []),
        }
        for addr, n in counter.most_common(top_n)
    ]
