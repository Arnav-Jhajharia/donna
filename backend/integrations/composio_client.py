"""Thin wrapper around Composio's Python SDK.

Vendor symbols (class names, app codes, trigger names) live ONLY in this
module. All callers go through ComposioClient. If Composio renames things,
the blast radius is one file.

This module covers auth + signature verification. Ingest, fetch, and
bootstrap helpers are added in later phases.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
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
