"""Batch refresh job for stored temporal situation briefs."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.memory.synthesis.temporal_brief import BriefImplementation

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RefreshOutcome:
    user_id: str
    status: str
    implementation: str = ""
    generated_at: str = ""
    evidence_used: dict[str, int] | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if data["evidence_used"] is None:
            data["evidence_used"] = {}
        return data


@dataclass(frozen=True)
class RefreshReport:
    dry_run: bool
    active_within_days: int
    selected: int
    refreshed: int
    failed: int
    skipped: int
    outcomes: list[RefreshOutcome]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "active_within_days": self.active_within_days,
            "selected": self.selected,
            "refreshed": self.refreshed,
            "failed": self.failed,
            "skipped": self.skipped,
            "outcomes": [outcome.to_dict() for outcome in self.outcomes],
        }


async def select_active_user_ids(
    *,
    active_within_days: int = 14,
    limit: int | None = None,
    include_sandbox: bool = False,
) -> list[str]:
    """Return user ids worth refreshing.

    A user is active when either `users.last_active_at`/`created_at` is recent
    or they have recent chat messages. This handles older rows where
    `last_active_at` was not reliably maintained.
    """
    from sqlalchemy import desc, distinct, or_, select

    from backend.db.models import ChatMessage, User
    from backend.db.session import async_session

    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=active_within_days)
    selected: list[str] = []
    seen: set[str] = set()

    async with async_session() as session:
        user_stmt = select(User).where(
            or_(
                User.last_active_at >= since,
                User.created_at >= since,
            )
        )
        if not include_sandbox:
            user_stmt = user_stmt.where(User.is_sandbox.is_(False))
        user_stmt = user_stmt.order_by(desc(User.last_active_at), desc(User.created_at))
        if limit:
            user_stmt = user_stmt.limit(limit)
        users = (await session.execute(user_stmt)).scalars().all()
        for user in users:
            if user.id not in seen:
                seen.add(user.id)
                selected.append(user.id)

        remaining = None if limit is None else max(0, limit - len(selected))
        if remaining != 0:
            chat_stmt = (
                select(distinct(ChatMessage.user_id))
                .join(User, User.id == ChatMessage.user_id)
                .where(ChatMessage.created_at >= since)
                .order_by(ChatMessage.user_id)
            )
            if not include_sandbox:
                chat_stmt = chat_stmt.where(User.is_sandbox.is_(False))
            if remaining:
                chat_stmt = chat_stmt.limit(remaining)
            chat_user_ids = (await session.execute(chat_stmt)).scalars().all()
            for user_id in chat_user_ids:
                if user_id not in seen:
                    seen.add(user_id)
                    selected.append(user_id)

    return selected


async def refresh_active_user_briefs(
    *,
    active_within_days: int = 14,
    limit: int | None = None,
    include_sandbox: bool = False,
    dry_run: bool = False,
    implementation: str = BriefImplementation.WINDOWED_TIMELINE.value,
    use_claude: bool = False,
    concurrency: int = 4,
) -> RefreshReport:
    user_ids = await select_active_user_ids(
        active_within_days=active_within_days,
        limit=limit,
        include_sandbox=include_sandbox,
    )
    if dry_run:
        outcomes = [RefreshOutcome(user_id=user_id, status="skipped") for user_id in user_ids]
        return RefreshReport(
            dry_run=True,
            active_within_days=active_within_days,
            selected=len(user_ids),
            refreshed=0,
            failed=0,
            skipped=len(user_ids),
            outcomes=outcomes,
        )

    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _one(user_id: str) -> RefreshOutcome:
        async with semaphore:
            try:
                from backend.memory.synthesis.temporal_brief import synthesize_and_store_temporal_brief

                brief = await synthesize_and_store_temporal_brief(
                    user_id=user_id,
                    implementation=implementation,
                    use_claude=use_claude,
                )
                return RefreshOutcome(
                    user_id=user_id,
                    status="ok",
                    implementation=brief.implementation,
                    generated_at=brief.generated_at,
                    evidence_used=brief.evidence_used,
                )
            except Exception as exc:
                logger.exception("temporal refresh failed for user=%s", user_id[:8])
                return RefreshOutcome(user_id=user_id, status="error", error=str(exc))

    outcomes = await asyncio.gather(*[_one(user_id) for user_id in user_ids])
    refreshed = sum(1 for outcome in outcomes if outcome.status == "ok")
    failed = sum(1 for outcome in outcomes if outcome.status == "error")
    skipped = sum(1 for outcome in outcomes if outcome.status == "skipped")
    return RefreshReport(
        dry_run=False,
        active_within_days=active_within_days,
        selected=len(user_ids),
        refreshed=refreshed,
        failed=failed,
        skipped=skipped,
        outcomes=list(outcomes),
    )


async def run_forever(
    *,
    poll_interval_s: float = 7200.0,
    active_within_days: int = 14,
    limit: int | None = None,
    include_sandbox: bool = False,
    implementation: str = BriefImplementation.WINDOWED_TIMELINE.value,
    use_claude: bool = False,
    concurrency: int = 4,
) -> None:
    """Periodically refresh temporal briefs for active users.

    Designed to be spawned from the API startup hook. Each tick calls
    `refresh_active_user_briefs(...)` and logs a one-line summary. A failing
    tick is logged but never breaks the loop.
    """
    from donna_runtime.observability import emit

    while True:
        try:
            report = await refresh_active_user_briefs(
                active_within_days=active_within_days,
                limit=limit,
                include_sandbox=include_sandbox,
                implementation=implementation,
                use_claude=use_claude,
                concurrency=concurrency,
            )
            logger.info(
                "brief_refresh tick: selected=%d refreshed=%d failed=%d skipped=%d",
                report.selected, report.refreshed, report.failed, report.skipped,
            )
            try:
                emit(
                    "memory.brief_refresh.tick",
                    selected=report.selected,
                    refreshed=report.refreshed,
                    failed=report.failed,
                    skipped=report.skipped,
                    implementation=implementation,
                )
            except Exception:
                logger.exception("brief_refresh: emit failed")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("brief_refresh tick failed")
        await asyncio.sleep(poll_interval_s)
