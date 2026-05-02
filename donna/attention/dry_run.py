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
_SYNC_ENGINE = None


def _get_sync_engine():
    """Build (once) a sync SQLAlchemy engine off the same DATABASE_URL the
    async engine uses, swapping the driver to psycopg2/psycopg so we can
    talk to Postgres from sync proposer code without rewriting the
    async pipeline."""
    global _SYNC_ENGINE
    if _SYNC_ENGINE is not None:
        return _SYNC_ENGINE
    try:
        from sqlalchemy import create_engine
        from db.session import _clean_url
        from config import settings
    except Exception:
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
        logger.exception("calendar sync engine init failed")
        _SYNC_ENGINE = None
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

    Replaces the StubFetcher fixture path for SourceType.WEB_EXA,
    WEB_GOOGLE_NEWS, WEB_HN, WEB_REDDIT, WEB_X_TWITTER, WEB_RSS,
    WEB_SUBSTACK, WEB_PRODUCTHUNT, WEB_YOUTUBE, WEB_GITHUB_TRENDING,
    WEB_GITHUB_REPO, WEB_ARXIV, WEB_DOMAIN, WEB_PODCAST_TRANSCRIPT,
    WEB_SEARCH_GOOGLE.

    All of these used to return canned data via StubFetcher. They now
    call ``backend.web.client.exa_search`` with the source's ``query``
    param. The Source.type effectively becomes a hint we mostly ignore -
    Exa's neural index covers all of these flavors. We pass the search
    category when it maps cleanly (news for WEB_GOOGLE_NEWS, code for
    WEB_GITHUB_*).
    """

    _CATEGORY_BY_TYPE: dict[SourceType, str] = {
        SourceType.WEB_GOOGLE_NEWS: "news",
        SourceType.WEB_X_TWITTER: "tweet",
        SourceType.WEB_GITHUB_REPO: "github",
        SourceType.WEB_GITHUB_TRENDING: "github",
        SourceType.WEB_ARXIV: "research paper",
        SourceType.WEB_PODCAST_TRANSCRIPT: "podcast",
    }

    def fetch(self, source: Source, user_id: str | None) -> list[dict[str, Any]]:
        params = source.params or {}
        query = (params.get("query") or "").strip()
        if not query:
            return []
        # The fetcher Protocol is sync but exa_search is async. Run a
        # short event loop; this matches CalendarFetcher's pattern of
        # adapting async code to the sync proposer surface.
        import asyncio
        from backend.web.client import exa_search, have_exa_key
        from backend.web.proactive.cost_gate import exa_automation_paused

        if exa_automation_paused():
            return []
        if not have_exa_key():
            return []

        num_results = int(params.get("num_results") or 5)
        category = self._CATEGORY_BY_TYPE.get(source.type)
        # Domain restriction passes through where the spec set one.
        include_domains = params.get("include_domains")
        max_age_hours = params.get("max_age_hours")

        async def _run() -> dict[str, Any]:
            return await exa_search(
                query,
                num_results=num_results,
                search_type="auto",
                category=category if category in {"news", "company", "people", "code"} else None,
                include_domains=include_domains if isinstance(include_domains, list) else None,
                max_age_hours=int(max_age_hours) if max_age_hours else None,
            )

        try:
            res = asyncio.run(_run())
        except RuntimeError:
            # Already in an event loop - rare in the sync proposer
            # surface, but defensively run in a thread.
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, _run())
                res = future.result(timeout=15)
        except Exception:
            logger.exception("ExaWebFetcher failed for %s", source.type.value)
            return []

        items = res.get("results") if isinstance(res, dict) else None
        if not isinstance(items, list):
            return []
        normalized: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            highlights = item.get("highlights") or []
            snippet = ""
            if isinstance(highlights, list) and highlights:
                snippet = " | ".join(str(h).strip() for h in highlights[:2])
            elif item.get("text"):
                snippet = str(item.get("text"))[:300]
            normalized.append({
                "title": item.get("title") or url,
                "url": url,
                "snippet": snippet,
                "publishedDate": item.get("publishedDate"),
                "source_type": source.type.value,
            })
        return normalized


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
