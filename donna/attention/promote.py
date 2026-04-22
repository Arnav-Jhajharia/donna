"""Shadow → Offered promoter.

Shadow attentions (`status=SHADOW`) tick silently. Each cycle:
  - tick the attention through the normal dry-run path,
  - classify the tick as a "hit" (did it surface real signal?),
  - increment `shadow_state.tick_count` and, if a hit, `promotion_hits`,
  - if `promotion_hits >= PROMOTION_THRESHOLD` → transition to OFFERED,
  - else if `tick_count >= shadow_state.max_ticks` → QUIETLY_ARCHIVED.

OFFERED attentions wait for the user to accept (→ LIVE) or reject
(→ REJECTED). The offer surface (WhatsApp tool) is a BRAIN concern and
lives outside this module.

Design bias: archive quietly rather than offer noisily. The whole point
of shadow mode is to fail silent.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from donna.attention.dry_run import DryRunResult, dry_run
from donna.attention.schema import Attention, AttentionStatus, ShadowState
from donna.attention.store import AttentionStore, AttentionTick, now_iso
from donna.attention.vocabulary import SourceType

logger = logging.getLogger(__name__)

PROMOTION_THRESHOLD = 2  # distinct ticks that produced real signal

# User elicitation synthesizes its own payload, so a non-zero count there
# isn't evidence the world produced a signal — exclude from hit detection.
_HIT_EXCLUDED_SOURCES = {SourceType.USER_ELICITATION}

# Noisy sources need multiple items before we call it a hit. A single tweet
# or news hit often turns out to be unrelated; real signal usually shows up
# with volume. Anything not listed defaults to _HIT_MIN_DEFAULT.
_HIT_MIN_DEFAULT = 1
_HIT_MIN_BY_SOURCE: dict[SourceType, int] = {
    SourceType.WEB_X_TWITTER: 5,
    SourceType.WEB_GOOGLE_NEWS: 3,
    SourceType.WEB_EXA: 3,
    SourceType.WEB_HN: 3,
    SourceType.WEB_REDDIT: 5,
}


@dataclass(frozen=True)
class PromotionResult:
    attention_id: str
    from_status: AttentionStatus
    to_status: AttentionStatus
    action: str  # "stayed" | "promoted" | "archived"
    hit: bool
    tick_count: int
    promotion_hits: int


def _is_hit(preview: DryRunResult) -> bool:
    for p in preview.source_previews:
        if p.source_type in _HIT_EXCLUDED_SOURCES:
            continue
        threshold = _HIT_MIN_BY_SOURCE.get(p.source_type, _HIT_MIN_DEFAULT)
        if p.item_count >= threshold:
            return True
    return False


def _classify(shadow: ShadowState) -> tuple[AttentionStatus, str]:
    """Decide next status based on current shadow_state counters."""
    if shadow.promotion_hits >= PROMOTION_THRESHOLD:
        return AttentionStatus.OFFERED, "promoted"
    if shadow.tick_count >= shadow.max_ticks:
        return AttentionStatus.QUIETLY_ARCHIVED, "archived"
    return AttentionStatus.SHADOW, "stayed"


def _step_shadow(
    attention: Attention, preview: DryRunResult
) -> tuple[Attention, PromotionResult]:
    shadow = attention.shadow_state or ShadowState()
    hit = _is_hit(preview)
    next_shadow = shadow.model_copy(
        update={
            "tick_count": shadow.tick_count + 1,
            "promotion_hits": shadow.promotion_hits + (1 if hit else 0),
        }
    )
    next_status, action = _classify(next_shadow)
    updated = attention.model_copy(
        update={
            "shadow_state": next_shadow,
            "status": next_status,
            "last_update_at": datetime.now(timezone.utc),
        }
    )
    result = PromotionResult(
        attention_id=str(attention.id),
        from_status=attention.status,
        to_status=next_status,
        action=action,
        hit=hit,
        tick_count=next_shadow.tick_count,
        promotion_hits=next_shadow.promotion_hits,
    )
    return updated, result


def run_shadow_cycle(
    user_id: str | None = None,
    *,
    store: AttentionStore | None = None,
) -> list[PromotionResult]:
    """Tick every SHADOW attention once and transition as warranted."""
    store = store or AttentionStore()
    shadow_atts = [
        a for a in store.list(user_id=user_id) if a.status is AttentionStatus.SHADOW
    ]

    results: list[PromotionResult] = []
    for attention in shadow_atts:
        try:
            preview = dry_run(attention.spec, user_id=str(attention.user_id))
        except Exception:
            logger.exception("shadow tick failed for %s; skipping", attention.id)
            continue

        # Record the tick (same as the normal tick pipeline) for parity.
        source_counts = {
            p.source_type.value: p.item_count for p in preview.source_previews
        }
        store.append_tick(
            str(attention.id),
            AttentionTick(
                at=now_iso(),
                rendered_markdown=preview.rendered_markdown,
                warnings=preview.warnings,
                source_counts=source_counts,
            ),
        )

        refreshed = store.get(attention.id)
        assert refreshed is not None  # append_tick just wrote it
        updated, result = _step_shadow(refreshed, preview)
        store.save(updated)
        results.append(result)
    return results


# -- Offer decisions ---------------------------------------------------------


def accept_offer(
    attention_id: str, *, store: AttentionStore | None = None
) -> Attention | None:
    """User said yes → LIVE, discard shadow bookkeeping."""
    store = store or AttentionStore()
    a = store.get(attention_id)
    if a is None or a.status is not AttentionStatus.OFFERED:
        return None
    updated = a.model_copy(
        update={"status": AttentionStatus.LIVE, "shadow_state": None}
    )
    return store.save(updated)


def reject_offer(
    attention_id: str, *, store: AttentionStore | None = None
) -> Attention | None:
    """User said no → REJECTED, keep record for future proposer suppression."""
    store = store or AttentionStore()
    a = store.get(attention_id)
    if a is None or a.status is not AttentionStatus.OFFERED:
        return None
    updated = a.model_copy(update={"status": AttentionStatus.REJECTED})
    return store.save(updated)
