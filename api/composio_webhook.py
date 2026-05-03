"""POST /webhooks/composio — Composio inbound events.

Source-of-truth surface for connection lifecycle and live ingest. Verifies
HMAC-SHA256 signature against COMPOSIO_WEBHOOK_SECRET, then dispatches by
`event` field. Handles connection lifecycle (complete/revoke/expired) and
live ingest for gmail.new_message and calendar.event.{created,updated,deleted}.

Calendar event payloads ride on the top-level `data` field rather than `event`
to avoid colliding with the event-type discriminator.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from backend.integrations import state
from backend.integrations.biography_synthesis import synthesize_biography
from backend.integrations.bootstrap_calendar import bootstrap_calendar
from backend.integrations.bootstrap_gmail import (
    bootstrap_30d_important,
    bootstrap_90d_aggregates,
    bootstrap_today_dense,
)
from backend.integrations.calendar_ingest import (
    delete_calendar_event,
    ingest_calendar_event,
)
from backend.integrations.composio_client import (
    TRIGGER_CALENDAR_EVENT_CREATED,
    TRIGGER_CALENDAR_EVENT_DELETED,
    TRIGGER_CALENDAR_EVENT_UPDATED,
    TRIGGER_GMAIL_NEW_MESSAGE,
    ComposioClient,
    NormalizedGmailMessage,
    verify_webhook_signature,
)
from backend.integrations.gmail_ingest import ingest_gmail_message
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


_APP_TO_PRODUCT = {
    "GMAIL": "gmail",
    "GOOGLECALENDAR": "calendar",
}

_CALENDAR_UPSERT_EVENTS = {"calendar.event.created", "calendar.event.updated"}

_PRODUCT_TRIGGERS = {
    "gmail": (TRIGGER_GMAIL_NEW_MESSAGE,),
    "calendar": (
        TRIGGER_CALENDAR_EVENT_CREATED,
        TRIGGER_CALENDAR_EVENT_UPDATED,
        TRIGGER_CALENDAR_EVENT_DELETED,
    ),
}

# ---------------------------------------------------------------------------
# Composio V3 dispatch
# ---------------------------------------------------------------------------
#
# V3 webhooks fire events under names like ``composio.connected_account.created``
# and ``composio.trigger.message``. The payload envelope wraps the actual data
# inside a ``data`` key. Toolkit identity rides on ``data.toolkit.slug`` (or,
# for trigger envelopes, the ``trigger_slug`` field). We accept either ``type``
# or ``event`` as the dispatch key — Composio docs/clients have used both.

_GOOGLE_TOOLKIT_TO_PRODUCT = {
    "gmail": "gmail",
    "googlecalendar": "calendar",
    "googledrive": "drive",
}


def _v3_provider_product(toolkit_slug: str) -> tuple[str, str]:
    """Map a Composio toolkit slug to our (provider, product) so the row in
    the integrations table is consistent with what connect_integration writes."""
    if toolkit_slug in _GOOGLE_TOOLKIT_TO_PRODUCT:
        return "google", _GOOGLE_TOOLKIT_TO_PRODUCT[toolkit_slug]
    return "composio", toolkit_slug


def _extract_v3_toolkit_slug(data: dict) -> str | None:
    """V3 payloads expose toolkit as ``{slug, ...}`` under ``data.toolkit``,
    or sometimes flat as ``data.toolkit_slug``. Try both."""
    if not isinstance(data, dict):
        return None
    toolkit = data.get("toolkit")
    if isinstance(toolkit, dict) and toolkit.get("slug"):
        return str(toolkit["slug"]).lower()
    if isinstance(toolkit, str):
        return toolkit.lower()
    flat = data.get("toolkit_slug")
    if isinstance(flat, str):
        return flat.lower()
    return None


def _extract_v3_user_id(payload: dict, data: dict) -> str | None:
    """user_id may sit in metadata (V3 trigger envelopes), at the envelope
    level (older shapes), or inside data — accept any of them."""
    metadata = payload.get("metadata") if isinstance(payload, dict) else None
    for src in (metadata, data, payload):
        if isinstance(src, dict):
            uid = src.get("user_id") or src.get("userId")
            if uid:
                return str(uid)
    return None


async def _handle_v3_connected_account_created(payload: dict, data: dict) -> dict:
    user_id = _extract_v3_user_id(payload, data)
    toolkit_slug = _extract_v3_toolkit_slug(data)
    if not user_id or not toolkit_slug:
        logger.warning(
            "composio_webhook v3: connected_account.created missing user_id/toolkit"
        )
        return {"ok": True, "ignored": True, "reason": "missing_fields"}

    connection_id = str(data.get("id") or data.get("connected_account_id") or "")
    provider, product = _v3_provider_product(toolkit_slug)
    await state.upsert_pending(user_id, provider, product)
    await state.mark_connected(
        user_id, provider, product, connection_id=connection_id
    )

    # Subscribe live triggers for the google products that have them so
    # subsequent gmail.new_message / calendar.event.* events flow back here.
    triggers = _PRODUCT_TRIGGERS.get(product, ())
    if triggers and connection_id:
        try:
            client = ComposioClient(api_key=settings.composio_api_key or "")
            await client.subscribe_triggers(
                user_id=user_id,
                connection_id=connection_id,
                trigger_names=triggers,
            )
        except Exception:
            logger.exception(
                "composio_webhook v3: subscribe_triggers failed user=%s product=%s",
                user_id, product,
            )

    # Immediate-confirm ping for ANY toolkit landing — google toolkits
    # also get a post-bootstrap follow-up later but still need the
    # immediate ack so the user knows the OAuth tap actually worked.
    try:
        from backend.integrations.notify import (
            STAGE_CONNECTED,
            notify_integration_complete,
        )

        asyncio.create_task(
            notify_integration_complete(
                user_id, [toolkit_slug], stage=STAGE_CONNECTED
            )
        )
    except Exception:
        logger.exception(
            "composio_webhook v3: notify spawn failed user=%s", user_id
        )

    # Resume any pending intents that were blocked on this toolkit.
    # Fires a proactive brain turn that answers the user's original ask
    # without waiting for them to re-prompt.
    try:
        from backend.integrations.pending_intents import drain_for_toolkit

        asyncio.create_task(drain_for_toolkit(user_id, toolkit_slug))
    except Exception:
        logger.exception(
            "composio_webhook v3: drain spawn failed user=%s toolkit=%s",
            user_id, toolkit_slug,
        )

    # Fire bootstrap only when google lands. Idempotent — duplicate
    # webhooks within the dedupe window become no-ops. Bootstrap fires
    # its own post-bootstrap "read through your inbox" ping.
    if provider == "google":
        asyncio.create_task(run_bootstrap_async(user_id))
    return {"ok": True, "marked_connected": f"{provider}_{product}"}


async def _handle_v3_connected_account_revoked(payload: dict, data: dict) -> dict:
    user_id = _extract_v3_user_id(payload, data)
    toolkit_slug = _extract_v3_toolkit_slug(data)
    if not user_id or not toolkit_slug:
        return {"ok": True, "ignored": True, "reason": "missing_fields"}
    provider, product = _v3_provider_product(toolkit_slug)
    await state.mark_revoked(user_id, provider, product)
    return {"ok": True, "marked_revoked": f"{provider}_{product}"}


_GMAIL_TRIGGER_SLUGS = {TRIGGER_GMAIL_NEW_MESSAGE, "GMAIL_NEW_MESSAGE"}
_CALENDAR_UPSERT_TRIGGER_SLUGS = {
    TRIGGER_CALENDAR_EVENT_CREATED,
    TRIGGER_CALENDAR_EVENT_UPDATED,
    "GOOGLECALENDAR_EVENT_CREATED",
    "GOOGLECALENDAR_EVENT_UPDATED",
}
_CALENDAR_DELETE_TRIGGER_SLUGS = {
    TRIGGER_CALENDAR_EVENT_DELETED,
    "GOOGLECALENDAR_EVENT_DELETED",
}


async def _handle_v3_trigger_message(payload: dict, data: dict) -> dict:
    """Unwrap a V3 trigger envelope and route to the right ingest handler.

    V3 envelope shape (per composio SDK ``WebhookTriggerPayloadV3``):
    ``{type, id, timestamp, metadata: {trigger_slug, user_id, ...},
       data: {<event-specific fields>}}``.
    The trigger slug + user_id sit in ``metadata``; ``data`` is the
    event-specific payload directly (no nested ``trigger_data`` wrapper).
    Older envelopes carried these inside ``data`` — fall back so a
    legacy webhook doesn't 404 silently.
    """
    metadata = payload.get("metadata") if isinstance(payload, dict) else {}
    if not isinstance(metadata, dict):
        metadata = {}

    user_id = _extract_v3_user_id(payload, data)
    if not user_id:
        return {"ok": True, "ignored": True, "reason": "missing_user_id"}

    trigger_slug = str(
        metadata.get("trigger_slug")
        or metadata.get("trigger_name")
        or data.get("trigger_slug")
        or data.get("trigger_name")
        or data.get("triggerName")
        or ""
    ).upper()
    if not trigger_slug:
        logger.warning("composio_webhook v3: trigger.message missing slug")
        return {"ok": True, "ignored": True, "reason": "missing_trigger_slug"}

    # In V3, ``data`` IS the event payload directly. The legacy
    # ``trigger_data`` / ``payload`` wrappers only exist on older shapes.
    inner = (
        data
        if data and not data.get("trigger_data") and not data.get("payload")
        else (
            data.get("trigger_data")
            or data.get("payload")
            or data.get("data")
            or {}
        )
    )

    if trigger_slug in _GMAIL_TRIGGER_SLUGS:
        # Composio V3 has shipped at least three different gmail-message
        # data shapes across different toolkit versions. Try every key
        # we've ever seen, then log a sample of the inner keys when none
        # match so the next variant is one log line away from a fix.
        message_id = (
            inner.get("message_id")
            or inner.get("messageId")
            or inner.get("id")
            or (inner.get("message") or {}).get("id")
            or (inner.get("message") or {}).get("messageId")
            or (inner.get("payload") or {}).get("id")
            or (inner.get("payload") or {}).get("messageId")
            or (inner.get("payload") or {}).get("message_id")
        )
        if not message_id:
            sample = {
                k: (str(v)[:60] + "...") if isinstance(v, (dict, list)) and len(str(v)) > 60
                else v
                for k, v in (inner.items() if isinstance(inner, dict) else [])
            }
            logger.warning(
                "composio_webhook v3: gmail trigger missing message_id "
                "| inner keys=%s | sample=%s",
                sorted(inner.keys()) if isinstance(inner, dict) else type(inner).__name__,
                str(sample)[:500],
            )
            return {"ok": True, "ignored": True, "reason": "missing_message_id"}
        try:
            client = ComposioClient(api_key=settings.composio_api_key or "")
            msg = await client.fetch_gmail_message(
                user_id=user_id, message_id=message_id, include_body=True
            )
            await ingest_gmail_message(user_id, msg)
            await state.touch_synced(user_id, "google", "gmail")
        except Exception:
            logger.exception(
                "composio_webhook v3: gmail ingest failed user=%s msg=%s",
                user_id, message_id,
            )
        return {"ok": True, "ingested": "gmail.new_message"}

    if trigger_slug in _CALENDAR_UPSERT_TRIGGER_SLUGS:
        ev = inner if isinstance(inner, dict) else {}
        if not ev.get("id"):
            return {"ok": True, "ignored": True, "reason": "missing_event_id"}
        try:
            await ingest_calendar_event(user_id, ev)
            await state.touch_synced(user_id, "google", "calendar")
        except Exception:
            logger.exception(
                "composio_webhook v3: calendar upsert failed user=%s", user_id
            )
        return {"ok": True, "ingested": "calendar.event.upsert"}

    if trigger_slug in _CALENDAR_DELETE_TRIGGER_SLUGS:
        ev = inner if isinstance(inner, dict) else {}
        ev_id = ev.get("id") or inner.get("event_id")
        if not ev_id:
            return {"ok": True, "ignored": True, "reason": "missing_event_id"}
        try:
            await delete_calendar_event(user_id, ev_id)
            await state.touch_synced(user_id, "google", "calendar")
        except Exception:
            logger.exception(
                "composio_webhook v3: calendar delete failed user=%s", user_id
            )
        return {"ok": True, "ingested": "calendar.event.deleted"}

    logger.info(
        "composio_webhook v3: unhandled trigger_slug=%r user=%s",
        trigger_slug, user_id,
    )
    return {"ok": True, "unhandled_trigger": trigger_slug}


async def _dispatch_v3(event_type: str, payload: dict) -> dict:
    """Route a V3 envelope to the right handler by event type."""
    data = payload.get("data") or {}
    if event_type == "composio.connected_account.created":
        return await _handle_v3_connected_account_created(payload, data)
    if event_type in (
        "composio.connected_account.expired",
        "composio.connected_account.deleted",
    ):
        return await _handle_v3_connected_account_revoked(payload, data)
    if event_type == "composio.trigger.message":
        return await _handle_v3_trigger_message(payload, data)
    if event_type == "composio.trigger.disabled":
        # Trigger died (e.g. quota exhausted). Log so we can re-subscribe;
        # nothing else to do without losing the user's data.
        logger.warning("composio_webhook v3: trigger disabled payload=%r", data)
        return {"ok": True, "noted": "trigger_disabled"}
    logger.info("composio_webhook v3: unhandled type=%r", event_type)
    return {"ok": True, "unhandled": event_type}


# Skip a duplicate bootstrap run if the previous one completed successfully
# within this window. Prevents thundering-herd on multi-toolkit OAuth chains
# (gmail + calendar + drive each fire watcher.bootstrap when they go ACTIVE)
# and on any transient re-trigger paths.
_BOOTSTRAP_DUPLICATE_WINDOW_S = 60 * 60


def _utcnow_naive():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _read_bootstrap_runs(user_id: str) -> dict:
    """Returns the bootstrap_runs sub-dict from users.living_profile,
    or {} if the user / field is missing."""
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
        return dict(profile.get("bootstrap_runs") or {})


async def _write_bootstrap_runs(user_id: str, patch: dict) -> None:
    """Merge a patch into users.living_profile.bootstrap_runs."""
    from sqlalchemy import select
    from sqlalchemy.orm.attributes import flag_modified

    from backend.db.session import async_session
    from db.models import User

    async with async_session() as s:
        user = (
            await s.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None:
            return
        profile = dict(user.living_profile or {})
        runs = dict(profile.get("bootstrap_runs") or {})
        runs.update(patch)
        profile["bootstrap_runs"] = runs
        user.living_profile = profile
        flag_modified(user, "living_profile")
        await s.commit()


def _is_recent_success(runs: dict) -> bool:
    """True if a successful bootstrap completed within the duplicate-skip
    window. Anything else (failed / running / never ran) -> False."""
    if runs.get("last_status") != "completed":
        return False
    last_completed = runs.get("last_completed_at")
    if not last_completed:
        return False
    try:
        from datetime import datetime
        when = datetime.fromisoformat(last_completed)
    except ValueError:
        return False
    delta = (_utcnow_naive() - when).total_seconds()
    return 0 <= delta < _BOOTSTRAP_DUPLICATE_WINDOW_S


async def run_bootstrap_async(user_id: str) -> dict:
    """Run all bootstrap stages plus biography synthesis. Fire-and-forget.

    Idempotent: skips silently if a successful run completed within the
    last hour, so multi-toolkit OAuth completions don't kick the gmail
    pipeline three times. On failure, persists the error to
    users.living_profile.bootstrap_runs so Donna can surface it.
    Returns a small status dict for observability.
    """
    runs = await _read_bootstrap_runs(user_id)
    if _is_recent_success(runs):
        logger.info(
            "run_bootstrap_async: skip user=%s — recent successful run %s",
            user_id,
            runs.get("last_completed_at"),
        )
        return {"status": "skipped", "reason": "recent_success"}
    if runs.get("last_status") == "running":
        # Concurrent watchers — let the first one win.
        started = runs.get("last_started_at")
        logger.info(
            "run_bootstrap_async: skip user=%s — already running since %s",
            user_id,
            started,
        )
        return {"status": "skipped", "reason": "already_running"}

    started_at = _utcnow_naive().isoformat()
    await _write_bootstrap_runs(user_id, {
        "last_started_at": started_at,
        "last_status": "running",
        "last_error": None,
    })

    try:
        await bootstrap_today_dense(user_id)
        await bootstrap_30d_important(user_id)
        await bootstrap_calendar(user_id)
        aggregates = await bootstrap_90d_aggregates(user_id)

        from sqlalchemy import select

        from backend.db.session import async_session
        from db.models import EmailMessage

        async with async_session() as s:
            rows = (
                await s.execute(
                    select(EmailMessage)
                    .where(EmailMessage.user_id == user_id)
                    .where(EmailMessage.ingest_depth == "full")
                    .where(EmailMessage.body_stored.is_(True))
                )
            ).scalars().all()
        msgs = [
            NormalizedGmailMessage(
                gmail_message_id=r.gmail_message_id,
                thread_id=r.thread_id,
                from_address=r.from_address,
                from_name=r.from_name,
                to_addresses=r.to_addresses,
                cc_addresses=r.cc_addresses,
                subject=r.subject,
                snippet=r.snippet,
                body_text=r.body_text,
                labels=r.labels,
                is_important=r.is_important,
                is_starred=r.is_starred,
                is_sent=r.is_sent,
                internal_date=r.internal_date,
            )
            for r in rows
        ]
        await synthesize_biography(user_id, msgs, aggregates)

        completed_at = _utcnow_naive().isoformat()
        await _write_bootstrap_runs(user_id, {
            "last_completed_at": completed_at,
            "last_status": "completed",
            "last_error": None,
        })
        logger.info("run_bootstrap_async: completed user=%s", user_id)

        # Tell the user the bootstrap is done. Reads which google toolkits
        # are actually live so the message reflects reality (e.g. they
        # might've connected gmail+calendar+drive but only gmail is the
        # bootstrap-relevant one to mention).
        try:
            from backend.integrations import state as _state
            from backend.integrations.notify import notify_integration_complete

            rows = await _state.list_user_integrations(user_id)
            google_toolkit_slugs = {
                "gmail": "gmail",
                "calendar": "googlecalendar",
                "drive": "googledrive",
            }
            connected = [
                google_toolkit_slugs[r.product]
                for r in rows
                if r.provider == "google"
                and r.status == "connected"
                and r.product in google_toolkit_slugs
            ]
            if connected:
                from backend.integrations.notify import STAGE_BOOTSTRAPPED

                await notify_integration_complete(
                    user_id, connected, stage=STAGE_BOOTSTRAPPED
                )
        except Exception:
            logger.exception(
                "run_bootstrap_async: notify failed user=%s", user_id
            )

        return {"status": "completed", "completed_at": completed_at}
    except Exception as exc:
        logger.exception("bootstrap failed user=%s", user_id)
        await _write_bootstrap_runs(user_id, {
            "last_status": "failed",
            "last_error": f"{type(exc).__name__}: {exc}"[:500],
            "last_failed_at": _utcnow_naive().isoformat(),
        })
        return {"status": "failed", "error": str(exc)[:500]}


# Composio's webhook UI defaults vary between accounts — some users
# configured the singular ``/webhook/composio`` and some the plural
# ``/webhooks/composio``. Accept both so a misconfigured URL doesn't
# silently 404 the event into the void.
@router.post("/webhooks/composio")
@router.post("/webhook/composio")
async def composio_webhook(
    request: Request,
    # V3 Standard Webhooks headers — these are what Composio sends today.
    webhook_id: str | None = Header(default=None),
    webhook_timestamp: str | None = Header(default=None),
    webhook_signature: str | None = Header(default=None),
    # Legacy header from V1/V2 deployments — kept as a fallback so an old
    # Composio dashboard configuration doesn't silently 401 every event.
    x_composio_signature: str | None = Header(default=None),
) -> dict:
    body = await request.body()
    secret = settings.composio_webhook_secret or ""
    sig_header = webhook_signature or x_composio_signature or ""
    if not verify_webhook_signature(
        body,
        sig_header,
        secret,
        webhook_id=webhook_id or "",
        webhook_timestamp=webhook_timestamp or "",
    ):
        # Diagnostic: emit a single redacted line so we can see WHICH
        # piece is wrong without leaking the secret. Header names are
        # logged verbatim; values are truncated.
        header_keys = sorted(request.headers.keys())
        sig_preview = sig_header[:20] + "..." if sig_header else "<empty>"
        logger.warning(
            "composio_webhook: bad signature | headers=%s | "
            "webhook-id=%r | webhook-timestamp=%r | sig=%s | "
            "secret_prefix=%s | secret_len=%d | body_len=%d",
            header_keys,
            (webhook_id or "")[:30],
            (webhook_timestamp or "")[:30],
            sig_preview,
            (secret or "")[:6],
            len(secret or ""),
            len(body),
        )
        raise HTTPException(status_code=401, detail="bad signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="bad json")

    # V3 envelopes use "type" with a "composio.*" prefix; legacy v1/v2
    # envelopes use "event" with bare names. Accept either; dispatch V3
    # first because the prefix gives us an unambiguous signal.
    event_type = str(payload.get("type") or payload.get("event") or "")
    # Diagnostic: emit one structured line per accepted webhook so we
    # can tell at a glance whether trigger.message events are arriving
    # vs. account-status events. For trigger events, also surface the
    # inner trigger_slug so missed dispatches are obvious.
    inner_for_log = payload.get("data") or {}
    trigger_slug_log = (
        str(
            inner_for_log.get("trigger_slug")
            or inner_for_log.get("trigger_name")
            or inner_for_log.get("triggerName")
            or ""
        )
        if isinstance(inner_for_log, dict)
        else ""
    )
    logger.info(
        "composio_webhook: accepted event_type=%r trigger_slug=%r",
        event_type,
        trigger_slug_log,
    )
    if event_type.startswith("composio."):
        return await _dispatch_v3(event_type, payload)

    event = payload.get("event")
    user_id = payload.get("user_id")
    if not event or not user_id:
        raise HTTPException(status_code=400, detail="missing fields")

    if event == "connection.complete":
        app = (payload.get("app") or "").upper()
        product = _APP_TO_PRODUCT.get(app)
        if product is None:
            logger.warning("composio_webhook: unknown app=%r", app)
            return {"ok": True, "ignored": True}
        connection_id = payload.get("connection_id") or ""
        await state.mark_connected(
            user_id,
            "google",
            product,
            connection_id=connection_id,
        )
        triggers = _PRODUCT_TRIGGERS.get(product, ())
        if triggers and connection_id:
            client = ComposioClient(api_key=settings.composio_api_key or "")
            await client.subscribe_triggers(
                user_id=user_id,
                connection_id=connection_id,
                trigger_names=triggers,
            )
        # Resume any pending intents that were blocked on this google
        # toolkit (legacy v1/v2 envelope path; mirrors the v3 handler).
        try:
            from backend.integrations.pending_intents import drain_for_toolkit

            slug_map = {"gmail": "gmail", "calendar": "googlecalendar", "drive": "googledrive"}
            slug = slug_map.get(product, product)
            asyncio.create_task(drain_for_toolkit(user_id, slug))
        except Exception:
            logger.exception(
                "composio_webhook: drain spawn failed user=%s product=%s",
                user_id, product,
            )
        asyncio.create_task(run_bootstrap_async(user_id))
        return {"ok": True}

    if event in {"connection.revoked", "connection.expired"}:
        app = (payload.get("app") or "").upper()
        product = _APP_TO_PRODUCT.get(app)
        if product:
            await state.mark_revoked(user_id, "google", product)
        return {"ok": True}

    if event == "gmail.new_message":
        message_id = payload.get("message_id")
        if not message_id:
            raise HTTPException(status_code=400, detail="missing message_id")
        client = ComposioClient(api_key=settings.composio_api_key or "")
        msg = await client.fetch_gmail_message(
            user_id=user_id, message_id=message_id, include_body=True
        )
        await ingest_gmail_message(user_id, msg)
        await state.touch_synced(user_id, "google", "gmail")
        return {"ok": True}

    if event in _CALENDAR_UPSERT_EVENTS:
        ev = payload.get("data") or {}
        if not ev.get("id"):
            raise HTTPException(status_code=400, detail="missing event id")
        await ingest_calendar_event(user_id, ev)
        await state.touch_synced(user_id, "google", "calendar")
        return {"ok": True}

    if event == "calendar.event.deleted":
        ev = payload.get("data") or {}
        ev_id = ev.get("id") or payload.get("event_id")
        if not ev_id:
            raise HTTPException(status_code=400, detail="missing event id")
        await delete_calendar_event(user_id, ev_id)
        await state.touch_synced(user_id, "google", "calendar")
        return {"ok": True}

    logger.info("composio_webhook: unhandled event=%r", event)
    return {"ok": True, "unhandled": event}
