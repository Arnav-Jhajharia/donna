"""Bridge between attention specs and the proactive web search harness.

Attention has rich `AttentionSpec` definitions with multiple typed
sources (WEB_EXA, WEB_GOOGLE_NEWS, WEB_HN, ...). All web-shaped sources
in attention used to fall through to ``StubFetcher`` and return canned
data. ``donna.attention.dry_run.ExaWebFetcher`` now backs them with real
Exa searches.

For ambient watching (the core attention promise: "watch this for me"),
this module compiles an ``AttentionSpec`` into ``proactive_subscriptions``
rows. The proactive harness then handles:
  - daily Exa monitor cadence
  - polling fallback for Starter accounts
  - signal queue + drain trigger
  - judge with surprise check
  - shadow / live delivery

Attention's own promote / fire-via-brain pipeline still works for
one-shot urgent surfaces; this bridge is for the steady-state "watch
this for me indefinitely" use case.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from donna.attention.schema import AttentionSpec
from donna.attention.vocabulary import SourceType

logger = logging.getLogger(__name__)


# Source types whose `params.query` is a search-shaped string we can
# feed straight into Exa as a webset description. Internal-state sources
# (CALENDAR_EVENTS, USER_ELICITATION, ENTITY_MEMORY, etc.) do NOT belong
# here - they're attention's own machinery.
_WEB_SOURCE_TYPES: frozenset[SourceType] = frozenset({
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
})


@dataclass(frozen=True)
class BridgeSummary:
    """What ``from_attention_spec`` did. For tests and traces."""

    user_id: str
    spec_title: str
    descriptions: tuple[str, ...]
    created: int
    deactivated: int


def _spec_to_descriptions(spec: AttentionSpec) -> list[str]:
    """Compile an AttentionSpec's web sources into search-shaped strings.

    Strategy:
    - For each web-typed source, take ``params.query`` as the base.
    - If the spec has a named subject and the subject's name doesn't
      already appear in the query, prepend it. This makes ``ambient
      agent Series A`` become ``Poke: ambient agent Series A`` for the
      poke_watch case (no-op when the subject is already in the query).
    - Dedup near-identical strings.
    """
    subject_name = ""
    if spec.subject and getattr(spec.subject, "name", None):
        subject_name = str(spec.subject.name).strip()

    out: list[str] = []
    seen: set[str] = set()
    for src in spec.sources:
        if src.type not in _WEB_SOURCE_TYPES:
            continue
        params = src.params or {}
        query = str(params.get("query") or "").strip()
        if not query:
            continue
        desc = query
        if subject_name and subject_name.lower() not in query.lower():
            desc = f"{subject_name}: {query}"
        # Cap length so it fits the description column comfortably.
        desc = desc[:240]
        normalized = desc.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(desc)
    return out


async def from_attention_spec(
    user_id: str,
    spec: AttentionSpec,
    *,
    max_active: int = 20,
) -> BridgeSummary:
    """Compile an AttentionSpec into proactive_subscriptions rows.

    Reuses ``reconcile_subscriptions`` with ``watches_override`` so the
    same dedup, deactivation, and budget paths apply. The descriptions
    are derived per spec (one spec usually maps to 1-3 subscription
    rows depending on how many web sources it has).

    Subsequent calls with the same spec are idempotent: descriptions
    that already exist as active subs are left alone; new ones are
    created. Provisioning Exa websets is NOT triggered here - that's
    the next step (call ``provision_pending_websets`` separately, or
    let the worker pick it up on the next reconcile tick).
    """
    from backend.web.proactive.subscriptions import reconcile_subscriptions

    descriptions = _spec_to_descriptions(spec)
    if not descriptions:
        logger.info(
            "from_attention_spec: spec %r has no web sources, skipping",
            spec.title,
        )
        return BridgeSummary(
            user_id=user_id,
            spec_title=spec.title,
            descriptions=(),
            created=0,
            deactivated=0,
        )

    # NOTE: reconcile uses watches_override to drive both creation AND
    # deactivation - i.e. it would deactivate any active subs not in the
    # provided list. To AUGMENT instead of replace, we read existing
    # active sub descriptions first and merge.
    from sqlalchemy import select
    from db.models import ProactiveSubscription
    from db.session import async_session

    async with async_session() as session:
        existing = (
            await session.execute(
                select(ProactiveSubscription.description).where(
                    ProactiveSubscription.user_id == user_id,
                    ProactiveSubscription.active.is_(True),
                )
            )
        ).all()
    existing_descs = {str(r[0] or "").strip() for r in existing if r[0]}

    merged = sorted(set(descriptions) | existing_descs)
    summary = await reconcile_subscriptions(
        user_id, max_active=max_active, watches_override=merged
    )
    return BridgeSummary(
        user_id=user_id,
        spec_title=spec.title,
        descriptions=tuple(descriptions),
        created=summary.created,
        deactivated=summary.deactivated,
    )
