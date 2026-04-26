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


_REGISTRY: dict[SourceType, Fetcher] = {
    SourceType.CALENDAR_EVENTS: CalendarFetcher(),
    SourceType.USER_ELICITATION: UserElicitationFetcher(),
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
