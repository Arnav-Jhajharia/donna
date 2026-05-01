"""URL-similar source: serendipity from URLs the user has engaged with.

Mines recent ChatMessage rows for URLs, then for each URL calls Exa's
``/findSimilar`` endpoint. The results are pages near the seed URL in
embedding space - genuinely-near-but-not-already-known content. This
is the engine of serendipity: surfaces things the user wouldn't have
searched for but would care about because they're adjacent to something
they already engaged with.

Output flows into the same ``proactive_signals`` queue the rest of the
proactive harness reads from. The drain trigger judges these the same
way it judges webset/poll signals.

Each found URL gets enqueued with a synthesized ``intent_key`` of the
form ``url_similar:<seed_url_hash>`` so downstream dedup works
naturally.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass

from sqlalchemy import desc, select

from backend.web.client import exa_find_similar, have_exa_key
from backend.web.proactive.store import SignalQueueRepo
from db.models import ChatMessage, ProactiveSignal, ProactiveSubscription
from db.session import async_session

logger = logging.getLogger(__name__)


_URL_RE = re.compile(r"https?://[^\s<>\"\)\]]+", re.IGNORECASE)
_DEFAULT_CHAT_LOOKBACK = 200
_DEFAULT_NUM_RESULTS = 4
_DEFAULT_MAX_SEEDS = 5
_SEED_DELAY_S = 1.5  # polite delay between findSimilar calls

# Filter out URLs that won't yield useful neighbors via findSimilar:
# auth/magic tokens, localhost, our own product URLs, generic API routes,
# and short URL shorteners (which don't carry semantic signal in the
# domain itself).
_URL_BLOCKLIST_SUBSTRINGS: tuple[str, ...] = (
    "/auth/",
    "/magic",
    "?t=",  # auth-token query
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "itsmedonna.com",
    "donna-dashboard",
    "composio.dev/api",
    "/api/",
    ".vercel.app/auth",
)


def _is_useful_seed(url: str) -> bool:
    """Coarse filter to skip auth tokens / internal URLs / etc."""
    if not url:
        return False
    low = url.lower()
    if any(needle in low for needle in _URL_BLOCKLIST_SUBSTRINGS):
        return False
    # Drop seeds with trailing JWT-like opaque blobs (long random strings).
    # Heuristic: any "?t=" param or 100+ char trailing path means token.
    if len(url) > 250:
        return False
    return True


@dataclass(frozen=True)
class UrlSimilarSummary:
    """Result of one ``poll_url_similar_signals`` pass."""

    user_id: str
    seeds_used: int
    new_signals: int
    failed: int


def _seed_intent_key(url: str) -> str:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    return f"url_similar:{digest}"


def _extract_urls_from_chats(messages: list[str]) -> list[str]:
    """Pull URLs out of chat content, dedupe, preserve order (most-recent
    first since callers pass desc-sorted messages). Filters out auth
    tokens / internal URLs / shorteners that wouldn't yield useful
    findSimilar neighbors.
    """
    seen: set[str] = set()
    out: list[str] = []
    for msg in messages:
        if not msg:
            continue
        for match in _URL_RE.findall(msg):
            url = match.rstrip(".,;:'\")")
            if url in seen:
                continue
            if not _is_useful_seed(url):
                continue
            seen.add(url)
            out.append(url)
    return out


async def _existing_urls_for_user(user_id: str) -> set[str]:
    """All URLs already in the queue for this user, for dedup."""
    async with async_session() as session:
        rows = (
            await session.execute(
                select(ProactiveSignal.payload).where(
                    ProactiveSignal.user_id == user_id,
                )
            )
        ).all()
    out: set[str] = set()
    for r in rows:
        payload = r[0] or {}
        if not isinstance(payload, dict):
            continue
        url = payload.get("url")
        if isinstance(url, str) and url.strip():
            out.add(url.strip())
    return out


async def _resolve_subscription_id(user_id: str) -> str | None:
    """Pick any active subscription for this user as the FK target.

    URL-similar signals don't naturally belong to a single watch
    subscription - they're seeded from URLs the user pasted, not from
    a topic-shaped watch. We attach them to any active sub so the FK
    constraint is satisfied; the intent_key on the signal carries the
    actual provenance.
    """
    async with async_session() as session:
        sub = (
            await session.execute(
                select(ProactiveSubscription)
                .where(
                    ProactiveSubscription.user_id == user_id,
                    ProactiveSubscription.active.is_(True),
                )
                .order_by(desc(ProactiveSubscription.created_at))
                .limit(1)
            )
        ).scalars().first()
    return sub.id if sub else None


async def poll_url_similar_signals(
    user_id: str,
    *,
    max_seeds: int = _DEFAULT_MAX_SEEDS,
    chat_lookback: int = _DEFAULT_CHAT_LOOKBACK,
    num_results_per_seed: int = _DEFAULT_NUM_RESULTS,
) -> UrlSimilarSummary:
    """Pull URLs from recent chat -> findSimilar -> enqueue new pages.

    Never raises. No-op when ``EXA_API_KEY`` missing, no URLs in chat,
    or no active subscriptions on this user (the proactive_signals FK
    requires a subscription_id).
    """
    if not have_exa_key():
        return UrlSimilarSummary(user_id, seeds_used=0, new_signals=0, failed=0)

    async with async_session() as session:
        chat_rows = (
            await session.execute(
                select(ChatMessage.content)
                .where(
                    ChatMessage.user_id == user_id,
                    ChatMessage.is_shadow.is_(False),
                )
                .order_by(desc(ChatMessage.created_at))
                .limit(chat_lookback)
            )
        ).all()
    chats = [str(r[0] or "").strip() for r in chat_rows if r[0]]
    seeds = _extract_urls_from_chats(chats)
    if not seeds:
        return UrlSimilarSummary(user_id, seeds_used=0, new_signals=0, failed=0)

    seeds = seeds[:max_seeds]
    sub_id = await _resolve_subscription_id(user_id)
    if sub_id is None:
        return UrlSimilarSummary(user_id, seeds_used=0, new_signals=0, failed=0)

    seen_urls = await _existing_urls_for_user(user_id)
    queue = SignalQueueRepo()
    seeds_used = 0
    new_signals = 0
    failed = 0

    for idx, seed in enumerate(seeds):
        if idx > 0:
            await asyncio.sleep(_SEED_DELAY_S)
        intent_key = _seed_intent_key(seed)
        seeds_used += 1
        try:
            res = await exa_find_similar(
                seed,
                num_results=num_results_per_seed,
                exclude_source_domain=True,
            )
        except Exception:
            logger.exception(
                "poll_url_similar_signals: find_similar failed user=%s seed=%s",
                user_id[:8] if user_id else "?",
                seed[:80],
            )
            failed += 1
            continue

        items = res.get("results") if isinstance(res, dict) else None
        if not isinstance(items, list) or not items:
            continue

        for item in items:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            await queue.enqueue(
                user_id=user_id,
                subscription_id=sub_id,
                intent_key=intent_key,
                payload={
                    "title": item.get("title") or url,
                    "url": url,
                    "highlights": item.get("highlights") or [],
                    "publishedDate": item.get("publishedDate"),
                    "seed_url": seed,
                },
            )
            seen_urls.add(url)
            new_signals += 1

    return UrlSimilarSummary(
        user_id=user_id,
        seeds_used=seeds_used,
        new_signals=new_signals,
        failed=failed,
    )
