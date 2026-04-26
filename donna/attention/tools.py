"""Pure-function tool handlers for the Attention primitive.

These are the functions BRAIN will wrap as Claude Agent SDK tools. They keep
all persistence + pipeline orchestration in one place so the CLI and BRAIN
call identical code.
"""
from __future__ import annotations

import re
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
    # True when the request matched an existing LIVE PING with the same
    # normalised subject created in the last ``_PING_DEDUP_WINDOW_S``
    # seconds. The returned ``attention`` is the EXISTING row, not a
    # newly-saved one. Callers should NOT re-materialise schedule fires
    # in this case — the existing attention's fire is already queued.
    reused: bool = False


# Two PINGs for the same subject within this window collapse to one.
# 30 minutes is wide enough to catch "remind me in 15 min to sleep" /
# "remind me in 30 min to sleep" said back-to-back; tight enough that
# a deliberate refresh hours later still creates a fresh row.
_PING_DEDUP_WINDOW_S = 30 * 60

# Stopwords + time-words stripped before comparing PING subjects.
# The author often writes the whole user sentence into ``subject.name``
# ("remind me in 30 minutes to sleep"), so naive equality misses
# obvious dupes. After stripping these, what's left is the topic
# the user actually cares about ("sleep").
_PING_SUBJECT_STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "about", "after", "all", "an", "and", "any", "around", "as", "at",
        "before", "by", "for", "from", "in", "into", "it", "later", "me", "my",
        "now", "of", "on", "or", "over", "remind", "reminder", "send",
        "should", "soon", "the", "then", "there", "these", "this", "those",
        "to", "today", "tomorrow", "tonight", "tongiht", "until", "us",
        "with", "you", "your",
        # time words
        "am", "pm", "second", "seconds", "sec", "secs",
        "minute", "minutes", "min", "mins",
        "hour", "hours", "hr", "hrs",
        "morning", "afternoon", "evening", "night",
        "monday", "tuesday", "wednesday", "thursday", "friday",
        "saturday", "sunday",
    }
)
_NUMBER_TOKEN_RE = re.compile(r"^\d+$")


def _ping_subject_tokens(text: str) -> set[str]:
    """Distinctive tokens left over after stripping numbers and the
    boilerplate words people use to phrase reminders. Used by PING
    near-match dedup so two "sleep" reminders collapse regardless of
    how the user phrased the time delta.
    """
    if not text:
        return set()
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    tokens: set[str] = set()
    for raw in cleaned.split():
        token = raw.strip()
        if not token:
            continue
        if _NUMBER_TOKEN_RE.match(token):
            continue
        if token in _PING_SUBJECT_STOPWORDS:
            continue
        tokens.add(token)
    return tokens


def _find_recent_ping_match(
    *,
    store: AttentionStore,
    user_id: str,
    subject_name: str,
) -> Attention | None:
    """Look for an existing LIVE PING within the dedup window whose
    subject overlaps in distinctive tokens with ``subject_name``.

    User-id matching uses the same UUID coercion as ``create_attention``
    so CLI handles like ``"cli-user"`` agree with stored UUID values.
    Returns the most recent match.
    """
    from donna.attention.vocabulary import CardType

    target_tokens = _ping_subject_tokens(subject_name)
    if not target_tokens:
        return None

    canonical_user_id = str(_coerce_uuid(user_id))
    now = datetime.now(timezone.utc)
    candidates: list[Attention] = []
    for a in store.list(user_id=canonical_user_id, status=AttentionStatus.LIVE):
        if a.spec.card is not CardType.PING:
            continue
        existing_subj = (
            getattr(getattr(a.spec, "subject", None), "name", "") or ""
        )
        existing_tokens = _ping_subject_tokens(existing_subj)
        if not existing_tokens or not (existing_tokens & target_tokens):
            continue
        created = a.created_at
        if created is None:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        delta = (now - created).total_seconds()
        if 0 <= delta <= _PING_DEDUP_WINDOW_S:
            candidates.append(a)
    if not candidates:
        return None
    return sorted(candidates, key=lambda a: a.created_at, reverse=True)[0]


async def create_attention(
    raw_intent: str,
    user_id: str,
    *,
    store: AttentionStore | None = None,
    auto_live: bool = True,
) -> CreateResult:
    """Run the full pipeline and persist the resulting Attention.

    For PING cards we do a near-match dedup against existing LIVE
    PINGs with the same normalised subject created in the last
    ``_PING_DEDUP_WINDOW_S`` seconds. When a match is found we return
    the EXISTING attention with ``reused=True`` instead of saving a
    duplicate. Caller is responsible for NOT re-materialising the
    schedule fire in that case.
    """
    store = store or AttentionStore()
    tz = await load_user_timezone(user_id)
    ctx = UserContext(user_id=user_id, user_tz=tz) if tz else UserContext(user_id=user_id)
    pipeline = await run_attention_pipeline(raw_intent, ctx)
    spec = pipeline.authored.spec

    # PING dedup — only after authoring so we know the canonical
    # subject the LLM picked. Non-PING cards skip this branch.
    from donna.attention.vocabulary import CardType

    if spec.card is CardType.PING:
        subject_name = (
            getattr(getattr(spec, "subject", None), "name", "") or ""
        )
        match = _find_recent_ping_match(
            store=store, user_id=user_id, subject_name=subject_name
        )
        if match is not None:
            return CreateResult(
                attention=match,
                authored_via=pipeline.authored.via,
                authored_confidence=pipeline.authored.confidence,
                preview=pipeline.preview,
                reused=True,
            )

    user_uuid = _coerce_uuid(user_id)
    attention = Attention(
        user_id=user_uuid,
        spec=spec,
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
