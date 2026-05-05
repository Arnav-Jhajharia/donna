from __future__ import annotations

import logging
from typing import Any

from claude_agent_sdk import tool

from ..hooks import _CURRENT_USER_ID, _fire_memory_hooks
from ..langsmith_tracing import traceable
from ..tool_logic import text_content
from ._shared import _current_user_id, _tool_text

logger = logging.getLogger(__name__)

async def _create_and_queue_attention(
    *, intent: str, user_id: str | None, origin: str, label: str
) -> dict[str, Any]:
    """Shared core for `attend` / `remind` / future attention-creating tools.

    Runs the author pipeline, materializes the first fire when the cadence
    is queueable (ONE_SHOT or SCHEDULED), and returns a small dict the
    individual tool wrappers turn into user-facing text. Keeps the failure
    modes uniform across entry points.
    """
    if not user_id:
        return {"status": "error", "reason": "no_user_id"}
    if not intent:
        return {"status": "error", "reason": "missing_intent"}

    try:
        from sqlalchemy import select

        from backend.db.models import User
        from backend.db.session import async_session as _session_factory
        from donna.attention.firing import materialize_next_fire
        from donna.attention.schema import AttentionOrigin
        from donna.attention.tools import create_attention
        from donna.attention.vocabulary import CadenceType
    except Exception as exc:
        logger.exception("%s: backend imports unavailable", label)
        return {"status": "error", "reason": f"imports:{type(exc).__name__}"}

    try:
        result = await create_attention(intent, user_id=user_id, auto_live=True)
    except Exception as exc:
        logger.exception("%s: create_attention failed", label)
        return {"status": "error", "reason": f"author:{type(exc).__name__}"}

    attention = result.attention

    # Near-match dedup: ``create_attention`` returns ``reused=True`` when
    # a recent LIVE PING with the same normalised subject already exists.
    # Skip every "wire it up" step (postgres mirror, schedule fire,
    # DonnaInstance materialise) — they're already done for the
    # original attention. Just confirm the merge to the caller.
    if result.reused:
        return {
            "status": "reused",
            "attention_id": str(attention.id),
            "title": attention.spec.title,
            "card": attention.spec.card.value,
            "cadence_type": attention.spec.cadence.type.value,
            "reused": True,
        }

    if origin == "donna":
        attention = attention.model_copy(
            update={"origin": AttentionOrigin.SHADOW_INFERRED}
        )

    try:
        async with _session_factory() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            if user is None:
                return {"status": "error", "reason": "user_not_found"}
            phone = getattr(user, "phone", None)
            tz = getattr(user, "timezone", None) or "Asia/Singapore"
            if not phone:
                return {"status": "error", "reason": "missing_phone"}
    except Exception as exc:
        logger.exception("%s: user lookup failed", label)
        return {"status": "error", "reason": f"db:{type(exc).__name__}"}

    # Dual-write to postgres so other replicas / the schedule worker see
    # the attention. The file store was already written by
    # ``create_attention`` above and remains the dev / cli fallback. We
    # don't fail the user request on mirror failure — the fire still
    # queues via DonnaSchedule, which is the path that actually delivers.
    try:
        from donna.attention.postgres_store import persist_attention

        await persist_attention(attention, user_id=user_id)
    except Exception:
        logger.exception("%s: postgres mirror write failed", label)

    cadence_type = attention.spec.cadence.type
    queueable = cadence_type in (CadenceType.ONE_SHOT, CadenceType.SCHEDULED)
    schedule_id: str | None = None
    if queueable:
        try:
            schedule_id = await materialize_next_fire(
                attention,
                user_id=user_id,
                user_phone=phone,
                user_tz=tz,
                origin=origin,
            )
        except Exception as exc:
            logger.exception("%s: materialize_next_fire failed", label)
            return {
                "status": "partial",
                "attention_id": str(attention.id),
                "reason": f"queue:{type(exc).__name__}",
            }
        if schedule_id is None:
            return {"status": "past_trigger", "attention_id": str(attention.id)}

    # For tracker-shaped cards (TALLY/EVENT_STREAM), do the same
    # post-accept work the dashboard accept handler does: materialize a
    # DonnaInstance(primitive=track) so observations route correctly,
    # and recompose the dashboard so the tracker-grid lands on the next
    # poll. Best-effort — failures here don't void the attention.
    instance_id: str | None = None
    instance_created = False
    try:
        from backend.dashboard.actions import (
            _maybe_materialize_instance,
            _spawn_recompose,
        )

        instance_id, instance_created = await _maybe_materialize_instance(
            user_id=user_id, attention=attention
        )
        if instance_id is not None:
            # Only recompose when a tracker actually materialized — for
            # PING / OPEN_LOOP / BRIEF cards there's nothing the
            # dashboard would surface differently right now. Fire-and-
            # forget so the brain turn doesn't block on a 60s LLM call.
            _spawn_recompose(user_id=user_id)
    except Exception:
        logger.exception("%s: dashboard wireup failed (non-fatal)", label)

    return {
        "status": "ok",
        "attention_id": str(attention.id),
        "title": attention.spec.title,
        "card": attention.spec.card.value,
        "cadence_type": cadence_type.value,
        "schedule_id": schedule_id,
        "instance_id": instance_id,
        "instance_created": instance_created,
    }


@tool(
    "attend",
    (
        "Create an attention — the SINGLE creation primitive for anything "
        "Donna will surface to the user in the future. One-shot reminders, "
        "recurring nudges, standing watches, weekly briefs, calendar prep: "
        "all collapse to this one tool. The author parses the intent and "
        "picks the right card (ping / event_stream / tally / brief / "
        "prep_doc / open_loop) and cadence (one_shot / scheduled / on_event) "
        "for you — do not pre-classify the intent yourself. "
        "Returns the attention_id; pass it to cancel_attention or "
        "snooze_attention. Origin defaults to 'user'; pass origin='donna' "
        "when Donna is proactively scheduling on the user's behalf. "
        "\n\n"
        "ALWAYS write the intent in first person from the user's "
        "perspective — 'remind me to ...', 'ping me at ...', 'prep me "
        "before ...', 'brief me on ...' — even when origin='donna'. "
        "NEVER write the intent in third person ('remind veer to ...', "
        "'ping <name> tomorrow ...'). First-person phrasing hits a fast "
        "deterministic time-parsing path; third-person bypasses it and "
        "produces unreliable fire times.\n"
        "\n"
        "ANTICIPATE. When the user mentions something that obviously sets "
        "up a future moment, schedule the attention yourself with "
        "origin='donna'. Don't wait to be asked. Examples of obvious "
        "anticipations (note: still first person):\n"
        "- user mentions 'meeting Aniroodh tomorrow at lunch' → "
        "origin='donna' attend('prep me 30 min before lunch with "
        "Aniroodh tomorrow') because they'll want context heading in.\n"
        "- user mentions 'shipping deploy at 3am' → origin='donna' "
        "attend('remind me tomorrow morning to check on how the canopy "
        "ship went').\n"
        "- user mentions 'I have a midterm in 3 days' → origin='donna' "
        "attend('remind me on the morning of the midterm with a quick "
        "ready check').\n"
        "- user mentions 'I'm writing the YC application this weekend' → "
        "origin='donna' attend('remind me saturday morning to check on "
        "YC progress').\n"
        "The bar for anticipation: would a thoughtful friend write it down "
        "without being asked? If yes, do it. If you're 50/50, do it — "
        "the user can cancel_attention if it's wrong. Silence on something "
        "obvious is worse than a slightly off attention.\n"
        "\n"
        "Use whenever the user asks to be reminded, watched, briefed, "
        "prepped, or pinged at a time or on a cadence. Examples: 'remind "
        "me at 5pm to call mom' (one-shot ping), 'every weekday at 9am "
        "journal' (recurring ping), 'keep an eye on poke launch updates' "
        "(standing event_stream), 'brief me on fundraising every friday' "
        "(weekly brief), 'prep me 15 min before sarah 1:1' (calendar prep). "
        "Do NOT use for open-ended commitments with no time or cadence "
        "('text luca' — that is track_open_loop). Do NOT use for "
        "past events (memory, not scheduling). For anticipations where "
        "the user didn't give an exact time, infer a sensible default "
        "(morning of, 30 min before, end of day) — do NOT pause to ask."
    ),
    {
        "type": "object",
        "required": ["intent"],
        "properties": {
            "intent": {
                "type": "string",
                "description": (
                    "Natural instruction phrased in first person from the "
                    "user's perspective ('remind me ...', 'ping me ...', "
                    "'brief me ...', 'prep me ...'), even when origin='donna'. "
                    "Never use the user's name as the subject of the "
                    "sentence — that bypasses the deterministic time-parsing "
                    "fast path. The author parses time / cadence / subject / "
                    "sources from the phrasing. Examples: 'remind me at 5pm "
                    "to call mom', 'every weekday at 9am journal', 'keep "
                    "an eye on poke launch updates', 'brief me on "
                    "fundraising every friday', 'prep me 15 minutes before "
                    "sarah 1:1'."
                ),
            },
            "origin": {
                "type": "string",
                "enum": ["user", "donna"],
                "description": (
                    "'user' when the user explicitly asked, 'donna' when "
                    "Donna is proactively scheduling. Defaults to 'user'."
                ),
            },
        },
    },
)
@traceable(name="donna.tool.attend", run_type="tool")
async def attend(args):
    user_id = _current_user_id()
    intent = str(args.get("intent") or "").strip()
    origin = str(args.get("origin") or "user").lower()
    if origin not in ("user", "donna"):
        origin = "user"

    result = await _create_and_queue_attention(
        intent=intent, user_id=user_id, origin=origin, label="attend"
    )
    return _render_attention_result(result)


def _render_attention_result(result: dict[str, Any]):
    status = result.get("status")
    if status == "reused":
        title = result.get("title") or "(untitled)"
        aid = result.get("attention_id") or "?"
        return text_content(
            f"attention reused: '{title}' is already live (attention_id={aid}). "
            "tell the user you already have this one running and you're "
            "keeping the existing schedule, not adding a duplicate."
        )
    if status == "ok":
        title = result.get("title") or "(untitled)"
        cadence = result.get("cadence_type") or "?"
        card = result.get("card") or "?"
        aid = result.get("attention_id") or "?"
        return text_content(
            f"attention created: '{title}' (card={card}, cadence={cadence}, "
            f"attention_id={aid})"
        )
    if status == "past_trigger":
        return text_content(
            "attention not queued: the parsed time is in the past. Ask the "
            "user to clarify the time."
        )
    if status == "partial":
        aid = result.get("attention_id") or "?"
        reason = result.get("reason") or "unknown"
        return text_content(
            f"attention partly created (saved as {aid}, fire not queued: "
            f"{reason}). Tell the user to retry."
        )
    reason = result.get("reason") or "unknown"
    if reason == "no_user_id":
        return text_content(
            "attention not created: no user_id in scope. Runtime bug — report it."
        )
    if reason == "missing_intent":
        return text_content(
            "attention not created: 'intent' is required. Pass a natural "
            "instruction in the user's words, e.g. 'remind me at 5pm to "
            "call mom' or 'keep an eye on the poke launch updates'."
        )
    if reason == "user_not_found":
        return text_content("attention not created: user not found.")
    if reason == "missing_phone":
        return text_content("attention not created: user missing phone.")
    return text_content(f"attention not created: {reason}.")


@tool(
    "list_attentions",
    (
        "List the user's pending attentions (unfired attention-linked "
        "schedules — reminders, scheduled watches, recurring nudges). "
        "Returns attention_id, fire_at, message, and recurrence info per row. "
        "Use when the user asks 'what reminders do I have', 'when is the next "
        "ping', 'what are you watching', or before calling cancel_attention / "
        "snooze_attention so you have the right id. "
        "Do NOT use as a fishing expedition — only when the user is asking "
        "about their pending attentions or you need to discover an "
        "attention_id to act on."
    ),
    {"type": "object", "properties": {}},
)
@traceable(name="donna.tool.list_attentions", run_type="tool")
async def list_attentions(args):
    user_id = _current_user_id()
    if not user_id:
        return text_content("No attentions.")
    try:
        from donna.attention.firing import list_pending_for_user
    except Exception:
        logger.exception("list_attentions: import failed")
        return text_content("Attentions unavailable.")
    try:
        rows = await list_pending_for_user(user_id)
    except Exception:
        logger.exception("list_attentions: query failed")
        return text_content("Attentions unavailable.")
    if not rows:
        return text_content("No attentions.")
    lines: list[str] = []
    for r in rows[:20]:
        meta = r.get("recurrence_meta") or {}
        cad_type = meta.get("cadence_type") or "one_shot"
        line = (
            f"- {r['fire_at']}  ({cad_type})  {r.get('message') or '(no message)'}"
            f"  [attention_id={r.get('attention_id')}]"
        )
        lines.append(line)
    if len(rows) > 20:
        lines.append(f"(showing 20 of {len(rows)})")
    return text_content("\n".join(lines))


@tool(
    "cancel_attention",
    (
        "Cancel an attention by attention_id. Deletes any pending fires and "
        "marks the attention resolved. Idempotent — safe to call twice. "
        "Use when the user explicitly says to cancel / stop / forget a "
        "reminder, watch, or scheduled nudge. Get the attention_id from "
        "list_attentions first if you do not have it. "
        "Do NOT cancel without an explicit user instruction. Do NOT use to "
        "snooze (use snooze_attention). Do NOT use to pause temporarily — "
        "cancel is permanent."
    ),
    {
        "type": "object",
        "required": ["attention_id"],
        "properties": {
            "attention_id": {
                "type": "string",
                "description": "The id returned by attend / list_attentions.",
            },
        },
    },
)
@traceable(name="donna.tool.cancel_attention", run_type="tool")
async def cancel_attention(args):
    user_id = _current_user_id()
    attention_id = str(args.get("attention_id") or "").strip()
    if not user_id:
        return text_content("Cancel failed: no user_id in scope.")
    if not attention_id:
        return text_content(
            "Cancel failed: 'attention_id' is required. Call list_attentions "
            "to discover it first."
        )
    try:
        from donna.attention.firing import cancel_pending_fires
        from donna.attention.postgres_store import update_attention_status
        from donna.attention.schema import AttentionStatus
        from donna.attention.tools import resolve_attention
    except Exception:
        logger.exception("cancel_attention: imports unavailable")
        return text_content("Cancel failed: backend unavailable.")
    try:
        deleted = await cancel_pending_fires(attention_id)
    except Exception:
        logger.exception("cancel_attention: db delete failed")
        return text_content("Cancel failed: db error.")
    try:
        resolve_attention(attention_id)
    except Exception:
        logger.info("cancel_attention: file-store status update skipped")
    try:
        await update_attention_status(attention_id, AttentionStatus.RESOLVED)
    except Exception:
        logger.exception("cancel_attention: postgres status update failed")
    if deleted == 0:
        return text_content(
            f"Cancel: nothing pending for attention_id={attention_id} "
            f"(already fired or unknown)."
        )
    return text_content(
        f"Cancelled attention_id={attention_id} ({deleted} pending fire(s) removed)."
    )


@tool(
    "snooze_attention",
    (
        "Push a pending attention's next fire forward by N minutes. Returns "
        "the new fire time. Idempotent per call — calling twice snoozes "
        "twice. "
        "Use when the user says 'snooze 10 min', 'remind me 30 min later', "
        "'push that back an hour'. Get the attention_id from list_attentions "
        "if you do not have it. "
        "Do NOT use for cancellation (use cancel_attention). Do NOT use to "
        "set an absolute new time — create a fresh attention via attend "
        "instead."
    ),
    {
        "type": "object",
        "required": ["attention_id", "minutes"],
        "properties": {
            "attention_id": {"type": "string"},
            "minutes": {
                "type": "integer",
                "description": "How many minutes to push the next fire forward (1..1440).",
            },
        },
    },
)
@traceable(name="donna.tool.snooze_attention", run_type="tool")
async def snooze_attention(args):
    user_id = _current_user_id()
    attention_id = str(args.get("attention_id") or "").strip()
    try:
        minutes = int(args.get("minutes") or 0)
    except Exception:
        return text_content("Snooze failed: 'minutes' must be an integer.")
    if not user_id:
        return text_content("Snooze failed: no user_id in scope.")
    if not attention_id:
        return text_content("Snooze failed: 'attention_id' is required.")
    if minutes <= 0 or minutes > 60 * 24:
        return text_content("Snooze failed: 'minutes' must be 1..1440.")
    try:
        from donna.attention.firing import snooze_pending_fires
    except Exception:
        logger.exception("snooze_attention: import failed")
        return text_content("Snooze failed: backend unavailable.")
    try:
        new_fire = await snooze_pending_fires(attention_id, by_seconds=minutes * 60)
    except Exception:
        logger.exception("snooze_attention: db update failed")
        return text_content("Snooze failed: db error.")
    if new_fire is None:
        return text_content(
            f"Snooze: nothing pending for attention_id={attention_id}."
        )
    return text_content(
        f"snoozed attention_id={attention_id} by {minutes} min "
        f"(new fire at {new_fire.isoformat()})"
    )


@tool(
    "accept_attention",
    (
        "Accept an OFFERED attention so it goes LIVE and starts running. "
        "OFFERED attentions appear in the per-turn ATTENTIONS WAITING block "
        "with their attention_id. The user accepting one looks like 'yes', "
        "'do it', 'start it', 'go ahead', or a clear contextual yes after "
        "you proposed the structure last turn or this turn. "
        "Use ONLY when the user agreed to a specific OFFERED attention from "
        "ATTENTIONS WAITING — pass that exact attention_id. "
        "Do NOT use for cancellation (use cancel_attention). Do NOT use to "
        "create a brand new attention (use attend). Do NOT call without an "
        "explicit user yes — never accept on the user's behalf. Do NOT pass "
        "an attention_id that isn't in ATTENTIONS WAITING — accept_attention "
        "only flips OFFERED -> LIVE."
    ),
    {
        "type": "object",
        "required": ["attention_id"],
        "properties": {
            "attention_id": {
                "type": "string",
                "description": (
                    "The attention_id from ATTENTIONS WAITING in your per-turn context."
                ),
            },
        },
    },
)
@traceable(name="donna.tool.accept_attention", run_type="tool")
async def accept_attention(args):
    user_id = _current_user_id()
    attention_id = str(args.get("attention_id") or "").strip()
    if not user_id:
        return text_content("Accept failed: no user_id in scope.")
    if not attention_id:
        return text_content(
            "Accept failed: 'attention_id' is required. The id is shown in "
            "ATTENTIONS WAITING."
        )
    try:
        from donna.attention.promote import accept_offer
    except Exception:
        logger.exception("accept_attention: imports unavailable")
        return text_content("Accept failed: backend unavailable.")
    try:
        updated = accept_offer(attention_id)
    except Exception:
        logger.exception("accept_attention: store update failed")
        return text_content("Accept failed: store error.")
    if updated is None:
        return text_content(
            f"Accept: attention_id={attention_id} is not OFFERED right now "
            "(already accepted, expired, or unknown)."
        )
    title = getattr(getattr(updated, "spec", None), "title", "") or "attention"
    return text_content(
        f"accepted attention_id={attention_id} ({title}) — status LIVE."
    )

