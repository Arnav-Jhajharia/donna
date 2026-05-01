"""Haiku-driven enrichment for inbound EmailMessage rows.

Triggered by ``gmail_ingest.ingest_gmail_message`` after a row is
upserted. When the email is important and inbound (not sent), this
module asks Haiku 4.5 to:

  * classify the email (reply_needed | fyi | scheduling |
    waiting_on_others | killable)
  * extract 3-5 key points
  * draft a reply in the user's voice when classification ==
    ``reply_needed``
  * suggest a recommended_action one-liner

Outputs land in ``email_intelligence`` (one row per important inbound
email, idempotent on user_id + email_message_id). Drives the morning
brief, the [INTEGRATIONS SIGNALS] block's "drafts ready" count, and
the dashboard's pending-review surface.

Conservative agency: ``draft_text`` is *never* sent. ``user_action``
and ``sent_draft_at`` are set only when the user explicitly confirms.

Failure-safe: returns ``None`` on missing API key, missing row, LLM
timeout, parse failure, or DB error. The caller (gmail_ingest) wraps
this in a try/except so ingest durability is unaffected.
"""
from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from backend.memory.retrieval.structured import call_structured
from db.models import EmailIntelligence, EmailMessage, User

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"
_TIMEOUT_S = 12.0
_MAX_TOKENS = 1500
_THREAD_CONTEXT_LIMIT = 5
_BODY_CHARS_CAP = 6000

Classification = Literal[
    "reply_needed",
    "fyi",
    "scheduling",
    "waiting_on_others",
    "killable",
]


class _EmailIntel(BaseModel):
    """Structured output schema for the Haiku enrichment call."""

    classification: Classification
    urgency: float = Field(ge=0.0, le=1.0)
    key_points: list[str] = Field(default_factory=list, max_length=5)
    draft_text: str | None = None
    draft_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    recommended_action: str | None = None


def _session_factory():
    from backend.db.session import async_session

    return async_session


_SYSTEM_PROMPT = """You are the email-triage subagent for Donna, a WhatsApp-native personal AI.

Your job: read one inbound email (with thread context) and emit a structured
verdict the main loop can act on. You are not Donna herself — you do not
talk to the user. You produce data.

Voice for any drafted reply text:
  - lowercase only, no capitalization at the start of sentences
  - no em dashes, no semicolons
  - blunt, high-agency, no filler ("happy to", "just wanted to", "I hope")
  - no apologies unless the user actually owes one
  - never use "I understand" or "Great question"
  - sign-off only if the prior thread used one — match the user's pattern

Classification rules:
  - reply_needed: the sender is waiting on a substantive response from the
    user. Draft a reply.
  - scheduling: a meeting/time/availability question. Draft only if a
    confirm/decline answer is unambiguous from context; otherwise leave
    draft_text null and set recommended_action to the question to ask.
  - fyi: information the user should see but does not have to reply to
    (status updates, receipts, internal CCs). No draft.
  - waiting_on_others: blocked on a third party, not the user. Surface
    the blocker in recommended_action so the user can chase if they want.
  - killable: noise (newsletter, marketing, automated digest, social
    notification) that the user can safely ignore or unsubscribe from.

Urgency is a 0..1 scalar reflecting how soon a response or action would
matter, blended with how high-stakes the sender/topic is. Newsletters: 0.
Same-day deadline from a key contact: 0.9+.

key_points: 3-5 short bullets capturing what the email actually says
and what it asks of the user. No fluff. Each bullet under 100 chars.

draft_text: only set when classification == reply_needed (or scheduling
with an unambiguous answer). Use the user's voice rules above. Leave
null if you would have to fabricate facts to write it.

draft_confidence: 0..1 honest read of how well the draft fits. Below 0.5
means the user should expect to rewrite. Null when no draft."""


def _format_email_body(msg: EmailMessage) -> str:
    body = (msg.body_text or msg.snippet or "").strip()
    if len(body) > _BODY_CHARS_CAP:
        body = body[: _BODY_CHARS_CAP - 1] + "…"
    return body


def _format_thread_history(thread: list[EmailMessage]) -> str:
    lines: list[str] = []
    for older in thread:
        sender = (older.from_name or older.from_address or "unknown").strip()
        subject = (older.subject or "").strip()
        body = (older.body_text or older.snippet or "").strip()
        if len(body) > 600:
            body = body[:599] + "…"
        direction = "outbound (user wrote)" if older.is_sent else "inbound"
        lines.append(
            f"--- {direction} from {sender} ({older.internal_date.isoformat()}) ---\n"
            f"subject: {subject}\n{body}"
        )
    return "\n\n".join(lines)


def _format_user_block(user: User | None) -> str:
    if user is None:
        return "user: (no profile)"
    bits = [f"name: {user.name or 'unknown'}"]
    if user.profession:
        bits.append(f"profession: {user.profession}")
    profile = user.living_profile or {}
    narrative = (profile.get("narrative") or "").strip()
    if narrative:
        if len(narrative) > 1500:
            narrative = narrative[:1499] + "…"
        bits.append(f"living profile narrative:\n{narrative}")
    return "\n".join(bits)


def _build_user_message(
    *,
    target: EmailMessage,
    thread: list[EmailMessage],
    user: User | None,
) -> str:
    sender = (target.from_name or target.from_address or "unknown").strip()
    subject = (target.subject or "").strip() or "(no subject)"
    body = _format_email_body(target)
    parts = [
        _format_user_block(user),
        "",
        f"--- email under triage ---",
        f"from: {sender} <{target.from_address}>",
        f"subject: {subject}",
        f"received: {target.internal_date.isoformat()}",
        f"labels: {', '.join(target.labels or [])}",
        "",
        body or "(empty body)",
    ]
    if thread:
        parts.extend(
            [
                "",
                "--- earlier thread context (oldest first) ---",
                _format_thread_history(thread),
            ]
        )
    return "\n".join(parts)


async def _load_thread_context(
    session, *, user_id: str, thread_id: str, exclude_id: str
) -> list[EmailMessage]:
    """Load up to _THREAD_CONTEXT_LIMIT prior messages in the same thread,
    oldest first, excluding the email under triage itself."""
    stmt = (
        select(EmailMessage)
        .where(
            EmailMessage.user_id == user_id,
            EmailMessage.thread_id == thread_id,
            EmailMessage.id != exclude_id,
        )
        .order_by(desc(EmailMessage.internal_date))
        .limit(_THREAD_CONTEXT_LIMIT)
    )
    rows = (await session.execute(stmt)).scalars().all()
    rows.reverse()
    return list(rows)


def _should_enrich(msg: EmailMessage) -> bool:
    if msg.is_sent:
        return False
    if not msg.is_important:
        return False
    return True


async def enrich_email(user_id: str, email_message_id: str) -> bool:
    """Run Haiku enrichment for one inbound email row.

    Returns True when a row was written, False otherwise (skipped,
    already-enriched, gated out, or LLM unavailable). Never raises.
    """
    if not user_id or not email_message_id:
        return False

    try:
        async with _session_factory()() as session:
            target = await session.get(EmailMessage, email_message_id)
            if target is None or target.user_id != user_id:
                return False
            if not _should_enrich(target):
                return False

            existing = (
                await session.execute(
                    select(EmailIntelligence)
                    .where(EmailIntelligence.user_id == user_id)
                    .where(EmailIntelligence.email_message_id == email_message_id)
                )
            ).scalar_one_or_none()
            if existing is not None:
                return False

            user = await session.get(User, user_id)
            thread = await _load_thread_context(
                session,
                user_id=user_id,
                thread_id=target.thread_id,
                exclude_id=target.id,
            )

            prompt = _build_user_message(target=target, thread=thread, user=user)
    except Exception:
        logger.exception(
            "enrich_email: load failed user=%s email=%s", user_id, email_message_id
        )
        return False

    intel = await call_structured(
        model=_MODEL,
        system_prompt=_SYSTEM_PROMPT,
        user_message=prompt,
        schema=_EmailIntel,
        max_tokens=_MAX_TOKENS,
        timeout=_TIMEOUT_S,
    )
    if intel is None:
        logger.info(
            "enrich_email: llm returned no result user=%s email=%s",
            user_id, email_message_id,
        )
        return False

    # Sanity guard: drafts only land for the two classifications that
    # warrant them. Drop anything the model emitted off-spec.
    classification = intel.classification
    draft_text = intel.draft_text
    draft_confidence = intel.draft_confidence
    if classification not in ("reply_needed", "scheduling"):
        draft_text = None
        draft_confidence = None
    if draft_text is not None:
        draft_text = draft_text.strip() or None

    try:
        async with _session_factory()() as session:
            session.add(
                EmailIntelligence(
                    user_id=user_id,
                    email_message_id=email_message_id,
                    classification=classification,
                    urgency=float(intel.urgency),
                    key_points=list(intel.key_points or []),
                    draft_text=draft_text,
                    draft_confidence=(
                        float(draft_confidence)
                        if draft_confidence is not None
                        else None
                    ),
                    recommended_action=(intel.recommended_action or None),
                    context_links={},
                )
            )
            await session.commit()
    except Exception:
        # Most likely cause: race with a concurrent enrich_email call
        # for the same email — the unique index will reject the second
        # insert, which is fine.
        logger.exception(
            "enrich_email: persist failed user=%s email=%s",
            user_id, email_message_id,
        )
        return False

    return True
