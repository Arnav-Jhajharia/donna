"""Send the user a short proactive WhatsApp ping when an integration
finishes connecting. Fire-and-forget: failures log but never propagate.

Called from two places:
  - api.composio_webhook.run_bootstrap_async after the gmail bootstrap
    pipeline completes (so the message can say "read through your
    inbox" — the biography is ready by then)
  - backend.integrations.oauth_watcher when a non-google toolkit goes
    ACTIVE (no bootstrap step, ping immediately)

Dedup via ``users.living_profile.notified_integrations[<toolkit>]`` so a
re-fired webhook + watcher don't double-message the user. We keep the
window short (1 hour) so a genuine reconnect after a revocation still
sends a fresh ping.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Don't re-ping the user about a toolkit they already heard about within
# this window. Short enough that a real disconnect/reconnect re-pings.
NOTIFY_DEDUPE_WINDOW_S = 60 * 60

# Friendly product names shown to the user instead of raw composio slugs.
_TOOLKIT_LABEL = {
    "gmail": "gmail",
    "googlecalendar": "calendar",
    "googledrive": "drive",
    "slack": "slack",
    "notion": "notion",
    "linear": "linear",
    "github": "github",
    "asana": "asana",
    "hubspot": "hubspot",
    "salesforce": "salesforce",
    "intercom": "intercom",
}


def _label(toolkit: str) -> str:
    return _TOOLKIT_LABEL.get(toolkit, toolkit)


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _read_notified_map(user_id: str) -> dict[str, str]:
    from sqlalchemy import select

    from backend.db.session import async_session
    from db.models import User

    async with async_session() as s:
        user = (
            await s.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None:
            return {}
        profile = user.living_profile or {}
        return dict(profile.get("notified_integrations") or {})


async def _write_notified_map(user_id: str, toolkits: list[str]) -> None:
    """Mark each toolkit as notified-now, merging into existing map."""
    from sqlalchemy import select
    from sqlalchemy.orm.attributes import flag_modified

    from backend.db.session import async_session
    from db.models import User

    now_iso = _utcnow_naive().isoformat()
    async with async_session() as s:
        user = (
            await s.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None:
            return
        profile = dict(user.living_profile or {})
        notified = dict(profile.get("notified_integrations") or {})
        for tk in toolkits:
            notified[tk] = now_iso
        profile["notified_integrations"] = notified
        user.living_profile = profile
        flag_modified(user, "living_profile")
        await s.commit()


# Two-stage notify: stage="connected" fires the moment the toolkit goes
# ACTIVE on Composio (from any path: watcher, webhook, or per-turn
# reconcile). stage="bootstrapped" fires only after run_bootstrap_async
# finishes successfully. Dedupe keys incorporate stage so the two stages
# don't suppress each other for the same toolkit.
STAGE_CONNECTED = "connected"
STAGE_BOOTSTRAPPED = "bootstrapped"


def _dedupe_key(toolkit: str, stage: str) -> str:
    return f"{toolkit}:{stage}"


def _filter_unnotified(
    toolkits: list[str], stage: str, notified_map: dict[str, str]
) -> list[str]:
    """Drop toolkits whose last notification (for this stage) was within
    the dedupe window."""
    now = _utcnow_naive()
    window = timedelta(seconds=NOTIFY_DEDUPE_WINDOW_S)
    out: list[str] = []
    for tk in toolkits:
        last = notified_map.get(_dedupe_key(tk, stage))
        if not last:
            out.append(tk)
            continue
        try:
            when = datetime.fromisoformat(last)
        except ValueError:
            out.append(tk)
            continue
        if now - when >= window:
            out.append(tk)
    return out


def _build_message(toolkits: list[str], *, stage: str) -> str:
    """Compose Donna-voice copy per stage.

    stage="connected": fires immediately when OAuth lands. Tells the user
    we received the connection and (for google) are starting to read.

    stage="bootstrapped": fires after the gmail bootstrap completes.
    Tells the user we now actually have a sense of them and can field
    questions.
    """
    labels = [_label(t) for t in toolkits]
    has_gmail = "gmail" in toolkits

    if stage == STAGE_BOOTSTRAPPED:
        if len(labels) == 1 and has_gmail:
            return (
                "alright. read through your inbox, got a sense of who "
                "matters. ask me anything."
            )
        rest = " + ".join(l for l in labels if l != "gmail")
        if has_gmail and rest:
            return (
                f"alright. read through your inbox, plus i've got "
                f"{rest}. ask me anything."
            )
        joined = " + ".join(labels)
        return f"{joined} all set. ask me anything."

    # stage == STAGE_CONNECTED
    if has_gmail and len(labels) == 1:
        return "gmail's in. reading through your inbox, give me a sec."
    if has_gmail:
        rest = " + ".join(l for l in labels if l != "gmail")
        return (
            f"got it — gmail + {rest} connected. reading through your "
            f"inbox now, give me a sec."
        )
    if len(labels) == 1:
        return f"{labels[0]} connected. on it."
    joined = " + ".join(labels)
    return f"{joined} connected. on it."


async def _user_phone(user_id: str) -> str | None:
    from sqlalchemy import select

    from backend.db.session import async_session
    from db.models import User

    async with async_session() as s:
        user = (
            await s.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        return getattr(user, "phone", None) if user else None


async def notify_integration_complete(
    user_id: str,
    toolkits: list[str],
    *,
    stage: str = STAGE_CONNECTED,
    bootstrap_summary: bool | None = None,
) -> dict:
    """Send the integration ping. Returns ``{status, sent, skipped}``.

    ``stage`` selects the dedupe key + the copy:
      - STAGE_CONNECTED — fires immediately on flip pending->connected
        from any path (watcher / webhook / reconcile)
      - STAGE_BOOTSTRAPPED — fires after run_bootstrap_async completes
        successfully (gmail bootstrap pipeline)

    Stages have independent dedupe maps so the user gets BOTH messages
    (one when the connection lands, one when biography is ready) without
    one suppressing the other.

    Legacy ``bootstrap_summary`` kwarg still accepted: True maps to
    stage=STAGE_BOOTSTRAPPED, False maps to stage=STAGE_CONNECTED. New
    callers should pass ``stage`` directly.

    Never raises — WA delivery failures and DB errors surface as
    ``status="failed"`` so the caller (a watcher / hook task) keeps going.
    """
    if bootstrap_summary is not None:
        stage = STAGE_BOOTSTRAPPED if bootstrap_summary else STAGE_CONNECTED
    if not toolkits:
        return {"status": "noop", "reason": "no_toolkits"}

    try:
        notified = await _read_notified_map(user_id)
        fresh = _filter_unnotified(toolkits, stage, notified)
        if not fresh:
            return {"status": "skipped", "reason": "all_recently_notified"}

        phone = await _user_phone(user_id)
        if not phone:
            logger.warning(
                "notify_integration_complete: no phone user=%s stage=%s",
                user_id, stage,
            )
            return {"status": "skipped", "reason": "no_phone"}

        body = _build_message(fresh, stage=stage)

        try:
            from delivery.messages import TextMessage
            from delivery.whatsapp import WhatsAppChannel
        except Exception:
            logger.exception(
                "notify_integration_complete: import failed user=%s", user_id
            )
            return {"status": "failed", "reason": "import_failed"}

        wa = WhatsAppChannel()
        try:
            await wa.send(phone, TextMessage(body=body))
        except Exception:
            logger.exception(
                "notify_integration_complete: WA send failed user=%s", user_id
            )
            return {"status": "failed", "reason": "wa_send_failed"}

        # Persist the dedupe marker AFTER the send succeeds so a transient
        # WA failure doesn't suppress the eventual real notification.
        await _write_notified_map(
            user_id, [_dedupe_key(t, stage) for t in fresh]
        )
        logger.info(
            "notify_integration_complete: sent user=%s stage=%s toolkits=%s",
            user_id[:8], stage, fresh,
        )
        return {
            "status": "sent",
            "stage": stage,
            "sent": fresh,
            "skipped": [t for t in toolkits if t not in fresh],
        }
    except Exception:
        logger.exception(
            "notify_integration_complete: unexpected failure user=%s", user_id
        )
        return {"status": "failed", "reason": "unexpected"}
