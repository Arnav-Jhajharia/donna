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
TRIGGER_GMAIL_NEW_MESSAGE = "GMAIL_NEW_GMAIL_MESSAGE"
TRIGGER_CALENDAR_EVENT_CREATED = "GOOGLECALENDAR_NEW_CALENDAR_EVENT"
TRIGGER_CALENDAR_EVENT_UPDATED = "GOOGLECALENDAR_UPDATED_CALENDAR_EVENT"
TRIGGER_CALENDAR_EVENT_DELETED = "GOOGLECALENDAR_DELETED_CALENDAR_EVENT"


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
    headers = {
        (h.get("name") or "").lower(): h.get("value") or ""
        for h in (raw.get("payload") or {}).get("headers", [])
    }
    from_name, from_addr = _parse_address(headers.get("from", ""))
    labels = list(raw.get("labelIds") or [])
    internal_ms = int(raw.get("internalDate") or 0)
    internal_dt = datetime.fromtimestamp(
        internal_ms / 1000, tz=timezone.utc
    ).replace(tzinfo=None)

    return NormalizedGmailMessage(
        gmail_message_id=raw["id"],
        thread_id=raw["threadId"],
        from_address=from_addr,
        from_name=from_name,
        to_addresses=_split_addresses(headers.get("to", "")),
        cc_addresses=_split_addresses(headers.get("cc", "")),
        subject=headers.get("subject") or None,
        snippet=raw.get("snippet"),
        body_text=_decode_body(raw.get("payload")),
        labels=labels,
        is_important="IMPORTANT" in labels,
        is_starred="STARRED" in labels,
        is_sent="SENT" in labels,
        internal_date=internal_dt,
    )


def _composio():  # pragma: no cover - thin import site
    from composio import Composio

    return Composio()


def verify_webhook_signature(body: bytes, sig_hex: str, secret: str) -> bool:
    """Constant-time HMAC-SHA256 verify.

    Returns False on missing inputs rather than raising — webhook routes
    treat False as 401 unauthorized.
    """
    if not sig_hex or not secret:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_hex)


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
        result = composio.toolkits.authorize(user_id, app)
        return result.connected_account_id, result.redirect_url

    async def subscribe_triggers(
        self,
        user_id: str,
        connection_id: str,
        trigger_names: Iterable[str],
    ) -> None:
        """Subscribe Composio triggers for live webhook delivery.

        Idempotent: re-subscribing an active trigger is a no-op at Composio.
        Failures are logged and swallowed — caller decides whether to retry.
        """
        composio = _composio()
        for name in trigger_names:
            try:
                composio.triggers.subscribe(
                    user_id=user_id,
                    connected_account_id=connection_id,
                    trigger_name=name,
                )
            except Exception:
                logger.exception(
                    "subscribe_triggers: failed user=%s trigger=%s",
                    user_id,
                    name,
                )

    async def fetch_gmail_message(
        self, user_id: str, message_id: str, include_body: bool = True
    ) -> NormalizedGmailMessage:
        """Fetch one Gmail message and normalize into a vendor-agnostic shape."""
        composio = _composio()
        result = composio.tools.execute(
            "GMAIL_FETCH_MESSAGE_BY_ID",
            user_id=user_id,
            arguments={
                "message_id": message_id,
                "format": "full" if include_body else "metadata",
            },
        )
        return _normalize_gmail(result["data"])

    async def list_gmail_message_ids(
        self,
        user_id: str,
        query: str = "",
        max_results: int = 100,
        page_token: str | None = None,
    ) -> tuple[list[str], str | None]:
        """Page through Gmail message IDs by query string.

        Returns (ids, next_page_token). next_page_token=None means EOF.
        """
        composio = _composio()
        result = composio.tools.execute(
            "GMAIL_LIST_MESSAGES",
            user_id=user_id,
            arguments={
                "q": query,
                "max_results": max_results,
                "page_token": page_token,
            },
        )
        data = result.get("data") or {}
        ids = [m["id"] for m in data.get("messages", [])]
        next_token = data.get("nextPageToken")
        return ids, next_token

    async def list_calendar_events(
        self,
        user_id: str,
        time_min: datetime,
        time_max: datetime,
        max_results: int = 250,
    ) -> list[dict]:
        """List primary-calendar events in [time_min, time_max). Single events,
        i.e. recurring instances are expanded."""
        composio = _composio()
        result = composio.tools.execute(
            "GOOGLECALENDAR_LIST_EVENTS",
            user_id=user_id,
            arguments={
                "calendar_id": "primary",
                "time_min": time_min.isoformat() + "Z",
                "time_max": time_max.isoformat() + "Z",
                "max_results": max_results,
                "single_events": True,
            },
        )
        return (result.get("data") or {}).get("items", [])
