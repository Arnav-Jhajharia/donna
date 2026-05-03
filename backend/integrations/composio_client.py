"""Thin wrapper around Composio's Python SDK.

Vendor symbols (class names, app codes, trigger names) live ONLY in this
module. All callers go through ComposioClient. If Composio renames things,
the blast radius is one file.

This module covers auth + signature verification. Ingest, fetch, and
bootstrap helpers are added in later phases.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

logger = logging.getLogger(__name__)


# App codes per Composio's vocabulary. Verify against current docs.
APP_GMAIL = "GMAIL"
APP_GOOGLE_CALENDAR = "GOOGLECALENDAR"


# Trigger name constants — verify against current Composio docs at impl time.
# V3 Composio trigger slugs. Verified against `c.triggers.list(toolkit_slugs=...)`
# 2026-04-26 — the calendar slugs were renamed from the v2 form
# (GOOGLECALENDAR_NEW_CALENDAR_EVENT etc.) to add the
# `_GOOGLE_CALENDAR_` infix and `_TRIGGER` suffix; the old slugs 404
# at trigger creation time. Gmail kept its v2 slug.
TRIGGER_GMAIL_NEW_MESSAGE = "GMAIL_NEW_GMAIL_MESSAGE"
TRIGGER_CALENDAR_EVENT_CREATED = "GOOGLECALENDAR_GOOGLE_CALENDAR_EVENT_CREATED_TRIGGER"
TRIGGER_CALENDAR_EVENT_UPDATED = "GOOGLECALENDAR_GOOGLE_CALENDAR_EVENT_UPDATED_TRIGGER"
TRIGGER_CALENDAR_EVENT_DELETED = "GOOGLECALENDAR_EVENT_CANCELED_DELETED_TRIGGER"


# ── Gmail message normalization ───────────────────────────────────────────


@dataclass(frozen=True)
class NormalizedGmailMessage:
    """Vendor-agnostic shape consumed by ingest + bootstrap. Built from
    Composio's wire format so changes upstream are absorbed here."""

    gmail_message_id: str
    thread_id: str
    from_address: str
    from_name: str | None
    to_addresses: list[str]
    cc_addresses: list[str]
    subject: str | None
    snippet: str | None
    body_text: str | None
    labels: list[str]
    is_important: bool
    is_starred: bool
    is_sent: bool
    internal_date: datetime


_FROM_RE = re.compile(r"^(?:\"?(?P<name>[^\"<]*?)\"?\s*<)?(?P<addr>[^>]+)>?$")


def _parse_address(raw: str) -> tuple[str | None, str]:
    if not raw:
        return None, ""
    m = _FROM_RE.match(raw.strip())
    if not m:
        return None, raw.strip()
    name = (m.group("name") or "").strip() or None
    addr = m.group("addr").strip()
    return name, addr


def _split_addresses(raw: str) -> list[str]:
    if not raw:
        return []
    return [_parse_address(part)[1] for part in raw.split(",") if part.strip()]


def _decode_body(payload: dict | None) -> str | None:
    """Walk MIME parts; prefer text/plain. Returns None if no plain text part."""
    if not payload:
        return None

    def walk(part: dict) -> str | None:
        mime = part.get("mimeType", "")
        body = part.get("body") or {}
        data = body.get("data")
        if data and mime == "text/plain":
            return base64.urlsafe_b64decode(data + "==").decode(
                "utf-8", errors="replace"
            )
        for child in part.get("parts") or []:
            found = walk(child)
            if found:
                return found
        return None

    return walk(payload)


def _normalize_gmail(raw: dict) -> NormalizedGmailMessage:
    """Normalize a GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID payload into our DTO.

    Composio's response shape (post-rename) exposes top-level convenience
    fields like ``messageId``, ``messageText``, ``messageTimestamp``,
    ``sender``, ``subject``, ``to`` alongside the raw ``payload.headers``
    array. We prefer the convenience fields when present and fall back
    to header parsing for the legacy shape.
    """
    headers = {
        (h.get("name") or "").lower(): h.get("value") or ""
        for h in (raw.get("payload") or {}).get("headers", [])
    }
    # Sender/subject/to: prefer the parsed top-level fields when Composio
    # provides them; fall back to raw headers for forward/back compat.
    sender_raw = raw.get("sender") or headers.get("from", "")
    from_name, from_addr = _parse_address(sender_raw)

    to_raw = raw.get("to") or headers.get("to", "")
    to_addresses = (
        to_raw if isinstance(to_raw, list) else _split_addresses(to_raw)
    )

    labels = list(raw.get("labelIds") or raw.get("labels") or [])

    # Timestamp: prefer messageTimestamp ISO; fall back to internalDate ms.
    timestamp_iso = raw.get("messageTimestamp")
    if timestamp_iso:
        try:
            # Strip trailing Z for fromisoformat compat.
            iso = timestamp_iso.rstrip("Z")
            internal_dt = datetime.fromisoformat(iso).replace(tzinfo=None)
        except ValueError:
            internal_dt = datetime.now(timezone.utc).replace(tzinfo=None)
    else:
        internal_ms = int(raw.get("internalDate") or 0)
        internal_dt = datetime.fromtimestamp(
            internal_ms / 1000, tz=timezone.utc
        ).replace(tzinfo=None)

    body_text = (
        raw.get("messageText")
        or _decode_body(raw.get("payload"))
        or None
    )
    # Empty string from messageText counts as "no body" — fall back so
    # downstream classifiers don't see truthy-empty.
    if isinstance(body_text, str) and not body_text.strip():
        body_text = _decode_body(raw.get("payload"))

    # ``preview`` is a string in some responses, a {body, subject} dict
    # in others. We only want a short text snippet for the snippet column.
    preview_raw = raw.get("preview") or raw.get("snippet")
    if isinstance(preview_raw, dict):
        snippet = preview_raw.get("body") or preview_raw.get("subject")
    else:
        snippet = preview_raw

    return NormalizedGmailMessage(
        gmail_message_id=raw.get("messageId") or raw.get("id") or "",
        thread_id=raw.get("threadId") or raw.get("thread_id") or "",
        from_address=from_addr,
        from_name=from_name,
        to_addresses=to_addresses,
        cc_addresses=_split_addresses(headers.get("cc", "")),
        subject=raw.get("subject") or headers.get("subject") or None,
        snippet=snippet,
        body_text=body_text,
        labels=labels,
        is_important="IMPORTANT" in labels,
        is_starred="STARRED" in labels,
        is_sent="SENT" in labels,
        internal_date=internal_dt,
    )


def _composio():  # pragma: no cover - thin import site
    from composio import Composio

    return Composio()


def verify_webhook_signature(
    body: bytes,
    sig_header: str,
    secret: str,
    *,
    webhook_id: str = "",
    webhook_timestamp: str = "",
) -> bool:
    """Verify a Composio webhook signature.

    Composio V3 follows the Standard Webhooks spec
    (https://www.standardwebhooks.com): three headers — ``webhook-id``,
    ``webhook-timestamp``, ``webhook-signature`` — and the signature is
    ``HMAC-SHA256("{id}.{timestamp}.{body}", secret)`` base64-encoded
    with a ``v1,`` prefix. Multiple signatures may be space-separated
    (rotation window); any match is acceptance.

    A pre-V3 fallback is kept: if ``webhook_id`` and ``webhook_timestamp``
    are empty, fall back to hex HMAC of the raw body — the V1/V2
    scheme — so legacy webhook configurations keep working through a
    transition.

    Returns False on missing inputs rather than raising — webhook routes
    treat False as 401 unauthorized.
    """
    if not sig_header or not secret:
        return False

    # V3 (Standard Webhooks) — id + timestamp present.
    if webhook_id and webhook_timestamp:
        signed = f"{webhook_id}.{webhook_timestamp}.".encode() + body
        expected = base64.b64encode(
            hmac.new(secret.encode(), signed, hashlib.sha256).digest()
        ).decode()
        # The header may carry multiple "v1,sig" tokens (rotation window),
        # space-separated. Accept any match.
        for token in sig_header.split():
            if not token.startswith("v1,"):
                continue
            candidate = token.split(",", 1)[1]
            if hmac.compare_digest(expected, candidate):
                return True
        return False

    # Legacy V1/V2 fallback — hex HMAC of raw body.
    expected_hex = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_hex, sig_header)


@dataclass(frozen=True)
class ComposioClient:
    """Stateless wrapper. SDK reads its key from env via Composio()."""

    api_key: str

    async def get_or_create_connection(
        self, user_id: str, app: str
    ) -> tuple[str, str]:
        """Return (connection_id, oauth_redirect_url) for a given (user, app).

        Idempotent at the SDK level — if a connection already exists for this
        (user_id, app), Composio returns the existing connection. The URL is
        the OAuth start URL the user must tap.
        """
        composio = _composio()
        result = composio.toolkits.authorize(user_id=user_id, toolkit=app)
        return result.id, result.redirect_url

    async def subscribe_triggers(
        self,
        user_id: str,
        connection_id: str,
        trigger_names: Iterable[str],
    ) -> list[str]:
        """Create Composio trigger instances so webhook events fire on
        new mail / calendar updates.

        V3 split the API: ``triggers.subscribe()`` is the websocket-style
        receive handler (takes ``timeout`` only); ``triggers.create()``
        actually registers a trigger instance against a connected account.
        We want create. Idempotent: Composio dedupes by
        (slug, user_id, connected_account_id), so re-creating an existing
        trigger returns the same id.

        Returns the list of created trigger ids (so callers can mirror
        them in their own DB if needed). Failures per slug are logged
        but don't abort — partial subscription is still useful.
        """
        composio = _composio()
        created_ids: list[str] = []
        for slug in trigger_names:
            try:
                resp = composio.triggers.create(
                    slug=slug,
                    user_id=user_id,
                    connected_account_id=connection_id,
                )
                trigger_id = (
                    getattr(resp, "trigger_id", None)
                    or getattr(resp, "id", None)
                )
                if trigger_id:
                    created_ids.append(str(trigger_id))
                logger.info(
                    "subscribe_triggers: created user=%s slug=%s id=%s",
                    user_id, slug, trigger_id,
                )
            except Exception:
                logger.exception(
                    "subscribe_triggers: failed user=%s slug=%s",
                    user_id, slug,
                )
        return created_ids

    async def fetch_gmail_message(
        self, user_id: str, message_id: str, include_body: bool = True
    ) -> NormalizedGmailMessage:
        """Fetch one Gmail message and normalize into a vendor-agnostic shape.

        Composio renamed ``GMAIL_FETCH_MESSAGE_BY_ID`` to
        ``GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID`` in their toolkit refresh —
        the old slug now 404s with Tool_ToolNotFound."""
        composio = _composio()
        result = composio.tools.execute(
            "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID",
            user_id=user_id,
            arguments={
                "message_id": message_id,
                "format": "full" if include_body else "metadata",
            },
            # Composio's SDK refuses to dispatch typed tools without an
            # explicit version pin since v1; we don't track per-toolkit
            # versions, so opt-in to "latest" via this flag. Same flag
            # already used by composio_meta for the COMPOSIO_* tools.
            dangerously_skip_version_check=True,
        )
        return _normalize_gmail(result["data"])

    async def search_gmail_id_by_rfc(
        self, user_id: str, rfc_message_id: str
    ) -> str | None:
        """Resolve an RFC822 ``Message-ID`` header value to a Gmail API id.

        Composio's V3 trigger payload only carries the parsed email body
        (headers + parts) — the Gmail API ``id`` field is missing. The
        RFC822 ``Message-ID`` header is the stable cross-system id; we
        translate it back to the Gmail API id with a search query, which
        lets ``fetch_gmail_message`` work normally.

        Gmail's search syntax: ``rfc822msgid:<id-without-angle-brackets>``.
        Returns None on no match (or any error) so the caller can log
        and bail without raising into the webhook handler.
        """
        if not rfc_message_id:
            return None
        # Strip surrounding angle brackets if present.
        cleaned = rfc_message_id.strip()
        if cleaned.startswith("<") and cleaned.endswith(">"):
            cleaned = cleaned[1:-1]
        try:
            ids, _ = await self.list_gmail_message_ids(
                user_id=user_id,
                query=f"rfc822msgid:{cleaned}",
                max_results=1,
            )
        except Exception:
            logger.exception(
                "search_gmail_id_by_rfc: list failed user=%s rfc=%r",
                user_id, cleaned,
            )
            return None
        return ids[0] if ids else None

    async def list_gmail_message_ids(
        self,
        user_id: str,
        query: str = "",
        max_results: int = 100,
        page_token: str | None = None,
    ) -> tuple[list[str], str | None]:
        """Page through Gmail message IDs by query string.

        Returns (ids, next_page_token). next_page_token=None means EOF.

        Composio renamed ``GMAIL_LIST_MESSAGES`` to ``GMAIL_FETCH_EMAILS``
        — the old slug 404s. The response shape kept ``data.messages`` and
        ``data.nextPageToken`` (matching the underlying Gmail API)."""
        composio = _composio()
        result = composio.tools.execute(
            "GMAIL_FETCH_EMAILS",
            user_id=user_id,
            arguments={
                "query": query,
                "max_results": max_results,
                "page_token": page_token,
                # IDs-only is faster + lighter; we hydrate body via
                # fetch_gmail_message for the few we keep.
                "include_payload": False,
                "ids_only": True,
            },
            dangerously_skip_version_check=True,
        )
        data = result.get("data") or {}
        # GMAIL_FETCH_EMAILS returns {messageId, threadId, display_url}
        # per item; older slug returned {id, threadId}. Accept either so
        # we don't break again on the next rename.
        ids = [
            m.get("messageId") or m.get("id")
            for m in data.get("messages", [])
        ]
        ids = [i for i in ids if i]
        next_token = data.get("nextPageToken") or None
        if next_token == "":
            next_token = None
        return ids, next_token

    async def list_calendar_events(
        self,
        user_id: str,
        time_min: datetime,
        time_max: datetime,
        max_results: int = 250,
    ) -> list[dict]:
        """List primary-calendar events in [time_min, time_max). Single events,
        i.e. recurring instances are expanded.

        Composio renamed ``GOOGLECALENDAR_LIST_EVENTS`` to
        ``GOOGLECALENDAR_EVENTS_LIST`` — the old slug 404s."""
        composio = _composio()
        result = composio.tools.execute(
            "GOOGLECALENDAR_EVENTS_LIST",
            user_id=user_id,
            arguments={
                "calendar_id": "primary",
                "time_min": time_min.isoformat() + "Z",
                "time_max": time_max.isoformat() + "Z",
                "max_results": max_results,
                "single_events": True,
            },
            dangerously_skip_version_check=True,
        )
        return (result.get("data") or {}).get("items", [])
