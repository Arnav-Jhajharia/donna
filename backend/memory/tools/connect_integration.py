"""connect_integration — get an OAuth URL for an external provider."""
from __future__ import annotations

from typing import Any

from backend.integrations import state
from backend.integrations.composio_client import (
    APP_GMAIL,
    APP_GOOGLE_CALENDAR,
    ComposioClient,
)
from config import settings
from donna_runtime.observability import instrument_memory_op

DESCRIPTION = (
    "Generate a connect link for an external provider (currently: google, "
    "covering calendar and gmail). Use when:\n"
    "  - the [INTEGRATIONS] context block shows the integration as not_connected\n"
    "  - the user asks for something requiring an integration that is not connected\n"
    "  - the user explicitly asks to connect a provider\n"
    "Do NOT use when:\n"
    "  - the integration is already connected (check [INTEGRATIONS] first)\n"
    "  - status is 'pending' — a link is already in flight; do not nag\n"
    "  - the user is mid-task and a connect prompt would derail them\n"
    "Returns a URL plus a one-line consent message. The consent statement "
    "in `message` MUST be preserved when forwarded to the user."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "provider": {"type": "string", "enum": ["google"]},
        "products": {
            "type": "array",
            "items": {"type": "string", "enum": ["calendar", "gmail"]},
            "minItems": 1,
        },
    },
    "required": ["provider", "products"],
}


_PRODUCT_TO_APP = {
    "calendar": APP_GOOGLE_CALENDAR,
    "gmail": APP_GMAIL,
}


def _client() -> ComposioClient:
    return ComposioClient(api_key=settings.composio_api_key)


_CONSENT_MESSAGE = (
    "need gmail + calendar to be useful. one-time read of today's inbox "
    "+ a sample of important mail to learn who matters to you. tap: {url}"
)


@instrument_memory_op("integrations.connect")
async def connect_integration(
    user_id: str, provider: str, products: list[str]
) -> dict[str, Any]:
    if provider != "google":
        return {
            "status": "error",
            "url": None,
            "message": f"provider {provider!r} not supported yet",
        }

    existing_statuses = []
    for product in products:
        row = await state.get_integration_status(user_id, provider, product)
        existing_statuses.append((product, row.status if row else "absent"))

    if all(s == "connected" for _, s in existing_statuses):
        return {
            "status": "already_connected",
            "url": None,
            "message": "already connected",
        }

    client = _client()
    # Composio's OAuth consent screen for Google can authorize multiple
    # scopes in one click when both apps share a Google account, so we
    # surface a SINGLE link (the first product that needs authorization).
    # The webhook handler completes both products on connection.complete.
    target_product = next(
        (p for p, s in existing_statuses if s != "connected"), products[0]
    )
    app = _PRODUCT_TO_APP[target_product]
    connection_id, url = await client.get_or_create_connection(
        user_id=user_id, app=app
    )

    for product in products:
        await state.upsert_pending(user_id, provider, product)

    return {
        "status": "url_sent",
        "url": url,
        "message": _CONSENT_MESSAGE.format(url=url),
        "connection_id": connection_id,
    }
