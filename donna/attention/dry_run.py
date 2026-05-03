"""Dry-run a spec against fixture data to produce a rendered preview.

Fetcher registry maps SourceType → Fetcher. CalendarFetcher is intended
to be the one live wire (see backend/memory/tools/list_calendar.py) — in
this harness it defers to a fixture loader if the live path is unavailable
or no user_id is supplied.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from donna.attention.schema import AttentionSpec, Source
from donna.attention.vocabulary import CardType, SourceType

logger = logging.getLogger(__name__)

_FIXTURE_DIR = Path(__file__).parent / "tests" / "fixtures"


class Fetcher(Protocol):
    def fetch(self, source: Source, user_id: str | None) -> list[dict[str, Any]]:
        ...


# -- Fixture-backed stub -----------------------------------------------------


class StubFetcher:
    """Load fixture JSON from tests/fixtures/<source_type>.json."""

    def fetch(self, source: Source, user_id: str | None) -> list[dict[str, Any]]:
        path = _FIXTURE_DIR / f"{source.type.value}.json"
        if not path.exists():
            logger.info("no fixture for %s; returning []", source.type.value)
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("fixture read failed for %s", source.type.value)
            return []


class CalendarFetcher:
    """Real calendar fetcher — falls back to fixture when DB not available.

    Queries the local ``calendar_entries`` mirror via a SYNC SQLAlchemy
    session so the (sync) Proposer interface doesn't have to await the
    async list_calendar tool. The previous implementation tried to call
    list_calendar (async) without awaiting it — which produced a runtime
    warning and the result was always a coroutine, so isinstance(list)
    failed and we silently fell through to the stub fixture every time.
    """

    def fetch(self, source: Source, user_id: str | None) -> list[dict[str, Any]]:
        if user_id:
            try:
                lookahead_days = int(source.params.get("lookahead_days") or 14)
                rows = _query_calendar_sync(user_id, lookahead_days)
                if rows is not None:
                    return rows
            except Exception:
                logger.exception(
                    "calendar live fetch failed; using fixture"
                )
        return StubFetcher().fetch(source, user_id)


# A single sync engine, lazily built. Reused across CalendarFetcher calls
# to avoid spinning up a fresh psycopg connection per propose pass.
# ``_SYNC_ENGINE_FAILED`` stays True after the first init failure so the
# next ten thousand calls don't each re-throw and re-log the same
# ImportError — the proposer ticks every minute, the brain ticks per
# turn, so silent retry-spam was filling logs.
_SYNC_ENGINE = None
_SYNC_ENGINE_FAILED = False


def _get_sync_engine():
    """Build (once) a sync SQLAlchemy engine off the same DATABASE_URL the
    async engine uses, swapping the driver to psycopg2/psycopg so we can
    talk to Postgres from sync proposer code without rewriting the
    async pipeline. Returns None on any failure; the caller falls back
    to a fixture/empty list."""
    global _SYNC_ENGINE, _SYNC_ENGINE_FAILED
    if _SYNC_ENGINE is not None:
        return _SYNC_ENGINE
    if _SYNC_ENGINE_FAILED:
        return None
    try:
        from sqlalchemy import create_engine
        from db.session import _clean_url
        from config import settings
    except Exception:
        _SYNC_ENGINE_FAILED = True
        logger.exception("calendar sync engine: import failed (one-shot log)")
        return None
    url, _kwargs = _clean_url(settings.database_url)
    # Async URLs use postgresql+asyncpg://; rewrite to use psycopg2 which
    # is what's installed for the sync path. _clean_url's connect_args
    # were tuned for asyncpg (statement_cache_size, ssl) and don't apply
    # to the sync driver, so we drop them entirely — defaults are fine
    # for a low-traffic propose pass.
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://"):
        if url.startswith(prefix):
            url = "postgresql+psycopg2://" + url[len(prefix):]
            break
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    try:
        _SYNC_ENGINE = create_engine(url, pool_pre_ping=True, pool_size=2)
    except Exception:
        _SYNC_ENGINE_FAILED = True
        logger.exception("calendar sync engine init failed (one-shot log)")
        return None
    return _SYNC_ENGINE


def _query_calendar_sync(
    user_id: str, lookahead_days: int
) -> list[dict[str, Any]] | None:
    """Returns the upcoming events list in the dict shape proposer
    consumes (id, title, start_time iso, end_time iso, location). Returns
    None on any DB failure so the caller can fall back to fixture."""
    from datetime import datetime, timedelta, timezone

    engine = _get_sync_engine()
    if engine is None:
        return None
    try:
        from sqlalchemy import select
        from sqlalchemy.orm import Session
        from db.models import CalendarEntry
    except Exception:
        return None

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    until = now + timedelta(days=lookahead_days)
    try:
        with Session(engine) as s:
            stmt = (
                select(CalendarEntry)
                .where(CalendarEntry.user_id == user_id)
                .where(CalendarEntry.start_time >= now)
                .where(CalendarEntry.start_time <= until)
                .order_by(CalendarEntry.start_time.asc())
                .limit(100)
            )
            rows = s.execute(stmt).scalars().all()
    except Exception:
        logger.exception("calendar sync query failed user=%s", user_id)
        return None
    return [
        {
            "id": r.id,
            "title": r.title,
            "start_time": r.start_time.isoformat() if r.start_time else None,
            "end_time": r.end_time.isoformat() if r.end_time else None,
            "location": r.location,
        }
        for r in rows
    ]


class UserElicitationFetcher:
    """Ping / elicitation stand-in: synthesize the question itself as the payload."""

    def fetch(self, source: Source, user_id: str | None) -> list[dict[str, Any]]:
        params = source.params
        return [{"question": params.get("question", ""), "expected_shape": params.get("expected_shape", "text")}]


class ExaWebFetcher:
    """Real fetcher for web-shaped attention sources.

    Backs SourceType.WEB_EXA, WEB_GOOGLE_NEWS, WEB_HN, WEB_REDDIT,
    WEB_X_TWITTER, WEB_RSS, WEB_SUBSTACK, WEB_PRODUCTHUNT, WEB_YOUTUBE,
    WEB_GITHUB_TRENDING, WEB_GITHUB_REPO, WEB_ARXIV, WEB_DOMAIN,
    WEB_PODCAST_TRANSCRIPT, WEB_SEARCH_GOOGLE.

    Routes through System B's fetcher (``backend.web.proactive.system_b``)
    so attention specs benefit from the same neighbor-expansion behavior
    proactive subs get: one ``/search`` plus an optional ``/findSimilar``
    on the top hit (~5 credits each) for ~2x richer results vs a single
    /search per source.

    The spec's frozen query is preserved verbatim — we do NOT regenerate
    it from current LP. The author committed to that watch; the upgrade
    is in HOW we resolve it, not WHAT it asks. Spec authors can set
    ``params.expand_with_similar=False`` on a source to opt out of the
    findSimilar layer if they want thinner / cheaper results.

    Cross-cycle dedup (against proactive_signals) is DISABLED here —
    attention is the committed surface; it should see everything on its
    topic regardless of what proactive subs already surfaced. Within-tick
    dedup (same URL across the spec's multiple sources) still applies.
    """

    def fetch(self, source: Source, user_id: str | None) -> list[dict[str, Any]]:
        params = source.params or {}
        query = (params.get("query") or "").strip()
        if not query:
            return []
        # The Fetcher Protocol is sync; System B's fetcher is async.
        # Same async-to-sync bridge as the legacy implementation.
        import asyncio
        from backend.web.client import have_exa_key
        from backend.web.proactive.cost_gate import exa_automation_paused
        from backend.web.proactive.system_b.fetcher import fetch_for_queries
        from backend.web.proactive.system_b.query_gen import GeneratedQuery

        if exa_automation_paused():
            return []
        if not have_exa_key():
            return []

        # Wrap the spec's frozen query as a single GeneratedQuery so it
        # flows through fetch_for_queries. Angle/cadence are placeholders
        # since legacy specs predate System B's metadata; the only field
        # that affects fetch behavior is expand_with_similar.
        expand = bool(params.get("expand_with_similar", True))
        gq = GeneratedQuery(
            text=query,
            angle="direct",
            cadence="weekly",
            ties_to=f"attention spec source {source.type.value}",
            expand_with_similar=expand,
        )

        async def _run() -> list[Any]:
            items, _summary = await fetch_for_queries(
                [gq],
                user_id=user_id or "",
                skip_dedup=True,  # attention sees everything on its topic
            )
            return items

        try:
            fetched = asyncio.run(_run())
        except RuntimeError:
            # Already in an event loop - rare in sync proposer surface,
            # but defensively run in a thread with a wider timeout
            # (System B may make 1 /search + 1 /findSimilar in series).
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, _run())
                fetched = future.result(timeout=30)
        except Exception:
            logger.exception("ExaWebFetcher failed for %s", source.type.value)
            return []

        return [
            {
                "title": it.title,
                "url": it.url,
                "snippet": it.snippet,
                "publishedDate": it.published_date,
                "source_type": source.type.value,
                "via_similar": it.via_similar,
            }
            for it in fetched
        ]


_EXA_FETCHER = ExaWebFetcher()

_WEB_SOURCE_TYPES = (
    SourceType.WEB_EXA,
    SourceType.WEB_GOOGLE_NEWS,
    SourceType.WEB_HN,
    SourceType.WEB_REDDIT,
    SourceType.WEB_X_TWITTER,
    SourceType.WEB_PRODUCTHUNT,
    SourceType.WEB_YOUTUBE,
    SourceType.WEB_SUBSTACK,
    SourceType.WEB_PODCAST_TRANSCRIPT,
    SourceType.WEB_RSS,
    SourceType.WEB_GITHUB_TRENDING,
    SourceType.WEB_GITHUB_REPO,
    SourceType.WEB_ARXIV,
    SourceType.WEB_DOMAIN,
    SourceType.WEB_SEARCH_GOOGLE,
)


_REGISTRY: dict[SourceType, Fetcher] = {
    SourceType.CALENDAR_EVENTS: CalendarFetcher(),
    SourceType.USER_ELICITATION: UserElicitationFetcher(),
    **{t: _EXA_FETCHER for t in _WEB_SOURCE_TYPES},
}
_DEFAULT_FETCHER: Fetcher = StubFetcher()


def fetcher_for(source_type: SourceType) -> Fetcher:
    return _REGISTRY.get(source_type, _DEFAULT_FETCHER)


# -- Dry run -----------------------------------------------------------------


@dataclass(frozen=True)
class SourcePreview:
    source_type: SourceType
    item_count: int
    sample: list[dict[str, Any]]


@dataclass(frozen=True)
class DryRunResult:
    spec_title: str
    card: CardType
    source_previews: tuple[SourcePreview, ...]
    rendered_markdown: str
    warnings: tuple[str, ...] = field(default_factory=tuple)


def dry_run(spec: AttentionSpec, user_id: str | None = None) -> DryRunResult:
    previews: list[SourcePreview] = []
    warnings: list[str] = []

    for src in spec.sources:
        fetcher = fetcher_for(src.type)
        try:
            items = fetcher.fetch(src, user_id)
        except Exception as e:
            warnings.append(f"{src.type.value}: fetch failed ({e})")
            items = []
        if not items:
            warnings.append(f"{src.type.value}: no items")
        previews.append(
            SourcePreview(
                source_type=src.type,
                item_count=len(items),
                sample=items[:3],
            )
        )

    rendered = _render(spec, previews)
    return DryRunResult(
        spec_title=spec.title,
        card=spec.card,
        source_previews=tuple(previews),
        rendered_markdown=rendered,
        warnings=tuple(warnings),
    )


# -- Rendering --------------------------------------------------------------


def _render(spec: AttentionSpec, previews: list[SourcePreview]) -> str:
    header = f"## {spec.title}\n_{spec.description}_\n"
    card_line = f"**card:** `{spec.card.value}` · **subject:** {spec.subject.name} ({spec.subject.type.value})\n"
    src_lines = ["**sources:**"]
    for p in previews:
        src_lines.append(f"- `{p.source_type.value}` — {p.item_count} item(s)")

    body = {
        CardType.EVENT_STREAM: _render_event_stream,
        CardType.TALLY: _render_tally,
        CardType.BRIEF: _render_brief,
        CardType.PREP_DOC: _render_prep,
        CardType.OPEN_LOOP: _render_openloop,
        CardType.PING: _render_ping,
    }[spec.card](spec, previews)

    return "\n".join([header, card_line, *src_lines, "", body])


def _render_event_stream(spec: AttentionSpec, previews: list[SourcePreview]) -> str:
    lines = ["**events (preview):**"]
    total = 0
    for p in previews:
        for item in p.sample:
            title = item.get("title") or item.get("summary") or str(item)[:80]
            lines.append(f"- {title}")
            total += 1
    if total == 0:
        lines.append("_no items in fixture_")
    return "\n".join(lines)


def _render_tally(spec: AttentionSpec, previews: list[SourcePreview]) -> str:
    total = sum(p.item_count for p in previews)
    return f"**tally:** {total} item(s) across {len(previews)} source(s)."


def _render_brief(spec: AttentionSpec, previews: list[SourcePreview]) -> str:
    return (
        f"**brief:** would synthesize {sum(p.item_count for p in previews)} "
        f"items from {len(previews)} source(s) via Haiku at cadence "
        f"`{spec.cadence.type.value}`."
    )


def _render_prep(spec: AttentionSpec, previews: list[SourcePreview]) -> str:
    return (
        f"**prep_doc** for subject `{spec.subject.name}`: would fuse "
        f"{sum(p.item_count for p in previews)} items into talking points."
    )


def _render_openloop(spec: AttentionSpec, previews: list[SourcePreview]) -> str:
    return (
        f"**open_loop:** tracking `{spec.subject.name}` — "
        f"{sum(p.item_count for p in previews)} candidate thread(s)."
    )


def _render_ping(spec: AttentionSpec, previews: list[SourcePreview]) -> str:
    sample = previews[0].sample if previews and previews[0].sample else [{}]
    question = sample[0].get("question", "(no question)")
    fire = spec.cadence.params.get("trigger_at") or spec.cadence.params.get("cron")
    return f"**ping:** `{question}` — fire: `{fire}`"
