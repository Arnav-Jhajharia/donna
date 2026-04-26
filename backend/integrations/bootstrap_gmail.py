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


# How many concurrent fetch_gmail_message calls to keep in flight. Composio
# rate limits aren't well-documented but observed throughput is ~2s per
# request serial; 8 in parallel cuts 200 messages from ~7min to ~50s
# without tripping rate limits in our testing.
_FETCH_CONCURRENCY = 8

# Hard cap on the 90d sender-aggregate scan. Each metadata fetch is still
# a HTTP roundtrip; observed Composio throughput is ~2s/req even with
# concurrency, so 200 messages = ~50s. Anything bigger and bootstrap
# blocks the proactive ping for too long. Top 200 most-recent senders is
# still plenty signal for biography ("who emails you most").
_AGGREGATE_SCAN_CAP = 200


async def _fetch_many(
    client: ComposioClient,
    user_id: str,
    ids: list[str],
    *,
    include_body: bool,
) -> list:
    """Fetch a batch of gmail messages with bounded concurrency.

    Failures per-message are logged and dropped (we'd rather get partial
    bootstrap data than abort the whole pipeline on one bad message).
    """
    import asyncio

    sem = asyncio.Semaphore(_FETCH_CONCURRENCY)

    async def _one(mid: str):
        async with sem:
            try:
                return await client.fetch_gmail_message(
                    user_id=user_id, message_id=mid, include_body=include_body
                )
            except Exception:
                logger.exception("_fetch_many: failed mid=%s", mid)
                return None

    results = await asyncio.gather(*[_one(mid) for mid in ids])
    return [r for r in results if r is not None]


async def bootstrap_today_dense(user_id: str) -> int:
    """Read every message from the last ~24h, classify, ingest. Returns count."""
    client = _client()
    ids, _ = await client.list_gmail_message_ids(
        user_id=user_id, query="newer_than:1d", max_results=200
    )
    msgs = await _fetch_many(client, user_id, ids, include_body=True)
    for msg in msgs:
        await ingest_gmail_message(user_id, msg)
    return len(msgs)


async def bootstrap_30d_important(user_id: str) -> int:
    """Read IMPORTANT-labelled messages from the last ~30d, ingest. Returns count."""
    client = _client()
    ids, _ = await client.list_gmail_message_ids(
        user_id=user_id,
        query="is:important newer_than:30d",
        max_results=300,
    )
    msgs = await _fetch_many(client, user_id, ids, include_body=True)
    for msg in msgs:
        await ingest_gmail_message(user_id, msg)
    return len(msgs)


async def bootstrap_90d_aggregates(
    user_id: str, top_n: int = 50
) -> list[dict]:
    """Return top-N senders in last 90d (count + sample subjects).

    Metadata-only. Does NOT write to email_messages mirror; returned in
    memory for biography synthesis to consume immediately. Capped at
    _AGGREGATE_SCAN_CAP messages to keep bootstrap latency bounded.
    """
    client = _client()
    ids, page_token = await client.list_gmail_message_ids(
        user_id=user_id, query="newer_than:90d", max_results=500
    )
    while page_token and len(ids) < _AGGREGATE_SCAN_CAP:
        more, page_token = await client.list_gmail_message_ids(
            user_id=user_id,
            query="newer_than:90d",
            max_results=500,
            page_token=page_token,
        )
        ids.extend(more)
    ids = ids[:_AGGREGATE_SCAN_CAP]

    msgs = await _fetch_many(client, user_id, ids, include_body=False)
    counter: Counter = Counter()
    samples: dict[str, list[str]] = {}
    for msg in msgs:
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
