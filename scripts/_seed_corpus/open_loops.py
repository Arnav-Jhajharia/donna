"""Open loops for Kai — varied ages, one resolved mid-corpus."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class OpenLoopRow:
    user_id: str
    content: str
    source_message: str | None
    created_at: datetime  # naive UTC
    status: str  # active | resolved
    resolved_at: datetime | None


def build_open_loop_rows(user_id: str, anchor: datetime) -> list[OpenLoopRow]:
    """Return 8 loops at varied ages. One is resolved mid-corpus."""
    return [
        OpenLoopRow(
            user_id=user_id,
            content="confirm dinner with maya",
            source_message="dinner with maya tomorrow night. confirm the place.",
            created_at=anchor - timedelta(days=1, hours=2),
            status="active",
            resolved_at=None,
        ),
        OpenLoopRow(
            user_id=user_id,
            content="finish board sync prep doc",
            source_message="board sync friday. need to prep.",
            created_at=anchor - timedelta(days=2),
            status="active",
            resolved_at=None,
        ),
        OpenLoopRow(
            user_id=user_id,
            content="set up weekly update cadence with saurabh",
            source_message="saurabh wants a weekly update. set that up.",
            created_at=anchor - timedelta(days=3),
            status="active",
            resolved_at=None,
        ),
        OpenLoopRow(
            user_id=user_id,
            content="respond to saurabh term sheet",
            source_message="saurabh sent the term sheet. 10m pre, clean terms.",
            created_at=anchor - timedelta(days=6),
            status="active",
            resolved_at=None,
        ),
        OpenLoopRow(
            user_id=user_id,
            content="respond to priya on revenue multiples",
            source_message="priya emailed asking about revenue multiples.",
            created_at=anchor - timedelta(days=10),
            status="resolved",
            resolved_at=anchor - timedelta(days=9),
        ),
        OpenLoopRow(
            user_id=user_id,
            content="clarify hiring plan with maya",
            source_message="maya wants to hire a third eng. disagree but haven't said so.",
            created_at=anchor - timedelta(days=14),
            status="active",
            resolved_at=None,
        ),
        OpenLoopRow(
            user_id=user_id,
            content="refactor ingest gate",
            source_message=None,
            created_at=anchor - timedelta(days=18),
            status="active",
            resolved_at=None,
        ),
        OpenLoopRow(
            user_id=user_id,
            content="call mom this weekend",
            source_message="talked to mom, she's doing fine.",
            created_at=anchor - timedelta(days=25),
            status="active",
            resolved_at=None,
        ),
    ]
