"""Pure-function tool handlers for the Attention primitive.

These are the functions BRAIN will wrap as Claude Agent SDK tools. They keep
all persistence + pipeline orchestration in one place so the CLI and BRAIN
call identical code.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from donna.attention.dry_run import DryRunResult, dry_run
from donna.attention.harness import run_attention_pipeline
from donna.attention.normalize import UserContext, load_user_timezone
from donna.attention.schema import Attention, AttentionOrigin, AttentionStatus
from donna.attention.store import AttentionStore, AttentionTick, now_iso


@dataclass(frozen=True)
class CreateResult:
    attention: Attention
    authored_via: str
    authored_confidence: float
    preview: DryRunResult


async def create_attention(
    raw_intent: str,
    user_id: str,
    *,
    store: AttentionStore | None = None,
    auto_live: bool = True,
) -> CreateResult:
    """Run the full pipeline and persist the resulting Attention."""
    store = store or AttentionStore()
    tz = await load_user_timezone(user_id)
    ctx = UserContext(user_id=user_id, user_tz=tz) if tz else UserContext(user_id=user_id)
    pipeline = await run_attention_pipeline(raw_intent, ctx)

    user_uuid = _coerce_uuid(user_id)
    attention = Attention(
        user_id=user_uuid,
        spec=pipeline.authored.spec,
        origin=AttentionOrigin.USER_EXPLICIT,
        status=AttentionStatus.LIVE if auto_live else AttentionStatus.SPEC_DRAFTED,
        created_at=datetime.now(timezone.utc),
    )
    store.save(attention)
    return CreateResult(
        attention=attention,
        authored_via=pipeline.authored.via,
        authored_confidence=pipeline.authored.confidence,
        preview=pipeline.preview,
    )


def list_attentions(
    user_id: str | None = None,
    status: AttentionStatus | None = None,
    *,
    store: AttentionStore | None = None,
) -> list[Attention]:
    store = store or AttentionStore()
    return store.list(user_id=user_id, status=status)


def get_attention(
    attention_id: str, *, store: AttentionStore | None = None
) -> Attention | None:
    store = store or AttentionStore()
    return store.get(attention_id)


def tick_attention(
    attention_id: str, *, store: AttentionStore | None = None
) -> tuple[Attention, DryRunResult] | None:
    """Fetch sources, render a preview, append to tick history."""
    store = store or AttentionStore()
    attention = store.get(attention_id)
    if attention is None:
        return None
    preview = dry_run(attention.spec, user_id=str(attention.user_id))
    source_counts = {p.source_type.value: p.item_count for p in preview.source_previews}
    store.append_tick(
        attention_id,
        AttentionTick(
            at=now_iso(),
            rendered_markdown=preview.rendered_markdown,
            warnings=preview.warnings,
            source_counts=source_counts,
        ),
    )
    refreshed = store.get(attention_id)
    assert refreshed is not None
    return refreshed, preview


def pause_attention(
    attention_id: str, *, store: AttentionStore | None = None
) -> Attention | None:
    store = store or AttentionStore()
    return store.update_status(attention_id, AttentionStatus.PAUSED)


def resume_attention(
    attention_id: str, *, store: AttentionStore | None = None
) -> Attention | None:
    store = store or AttentionStore()
    return store.update_status(attention_id, AttentionStatus.LIVE)


def resolve_attention(
    attention_id: str, *, store: AttentionStore | None = None
) -> Attention | None:
    store = store or AttentionStore()
    return store.update_status(attention_id, AttentionStatus.RESOLVED)


def _coerce_uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, TypeError):
        # CLI convenience: deterministic UUID5 from the handle.
        from uuid import NAMESPACE_URL, uuid5

        return uuid5(NAMESPACE_URL, f"donna://user/{value}") if value else uuid4()
