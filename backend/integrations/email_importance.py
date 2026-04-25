"""Deterministic importance scoring for inbound gmail.

Pure function — no DB, no network. The caller assembles ScoringContext
from biography + open_loops + recent sent state, then asks for a score.

Threshold for proactive surfacing is 0.5 (defined in proactive_email_trigger).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from backend.integrations.composio_client import NormalizedGmailMessage


@dataclass(frozen=True)
class ScoringContext:
    biography_relationships: Sequence[dict] = field(default_factory=list)
    # each: {"name": str, "frequency": "daily|weekly|monthly|rare",
    #        "_email": str (the from_address inferred at biography time)}
    open_loop_keywords: Sequence[str] = field(default_factory=list)
    # phrases pulled from open_loops summaries
    recent_sent_thread_ids: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class ScoreResult:
    score: float
    signals: list[str]


_FREQ_WEIGHT = {"daily": 0.6, "weekly": 0.5, "monthly": 0.25, "rare": 0.0}


def score_email(
    msg: NormalizedGmailMessage, ctx: ScoringContext
) -> ScoreResult:
    score = 0.0
    signals: list[str] = []

    if msg.is_important:
        score += 0.5
        signals.append("important_label")

    if msg.is_starred:
        score += 0.5
        signals.append("starred")

    rel_match = next(
        (
            r for r in ctx.biography_relationships
            if r.get("_email", "").lower() == msg.from_address.lower()
        ),
        None,
    )
    if rel_match is not None:
        weight = _FREQ_WEIGHT.get(rel_match.get("frequency", "rare"), 0.0)
        if weight > 0:
            score += weight
            signals.append("biography_relationship")

    subj_lower = (msg.subject or "").lower()
    body_lower = (msg.body_text or "").lower()
    for kw in ctx.open_loop_keywords:
        if not kw:
            continue
        if kw.lower() in subj_lower or kw.lower() in body_lower:
            score += 0.5
            signals.append("open_loop_match")
            break

    if msg.thread_id in ctx.recent_sent_thread_ids:
        score += 0.2
        signals.append("recent_sent_thread")

    score = min(score, 1.0)
    return ScoreResult(score=score, signals=signals)
