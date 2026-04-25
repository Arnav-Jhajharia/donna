"""connect_integration — get a SINGLE OAuth URL for an external provider.

Builds a Composio redirect chain so the user only taps once even when we
need multiple google services (gmail + calendar + drive). Each toolkit's
``callback_url`` points to the next toolkit's ``redirect_url`` so the
browser walks the chain after a single OAuth approval. Backed by
``composio_meta.resolve_auth_configs`` (auto-provisions managed toolkits
like googledrive when missing) and ``composio_meta.initiate_oauth_chain``.

We keep our own pending/connected mirror in the integrations table so
the [INTEGRATIONS] context block stays informative without polling
Composio.
"""
from __future__ import annotations

from typing import Any

from backend.integrations import composio_meta, state
from donna_runtime.observability import instrument_memory_op

DESCRIPTION = (
    "Generate a connect link for an external provider (currently: google, "
    "covering gmail, calendar, and drive). Use when:\n"
    "  - the [INTEGRATIONS] context block shows the integration as not_connected\n"
    "  - the user asks for something requiring an integration that is not connected\n"
    "  - the user explicitly asks to connect a provider\n"
    "Do NOT use when:\n"
    "  - the integration is already connected (check [INTEGRATIONS] first)\n"
    "  - status is 'pending' — a link is already in flight; do not nag\n"
    "  - the user is mid-task and a connect prompt would derail them\n"
    "Returns a one-line consent message containing a SINGLE URL — the chain "
    "covers every requested product. Forward verbatim."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "provider": {"type": "string", "enum": ["google"]},
        "products": {
            "type": "array",
            "items": {"type": "string", "enum": ["calendar", "gmail", "drive"]},
            "minItems": 1,
        },
    },
    "required": ["provider", "products"],
}

_PRODUCT_TO_TOOLKIT = {
    "gmail": "gmail",
    "calendar": "googlecalendar",
    "drive": "googledrive",
}
_TOOLKIT_TO_PRODUCT = {v: k for k, v in _PRODUCT_TO_TOOLKIT.items()}
_PRODUCT_LABEL = {"gmail": "gmail", "calendar": "calendar", "drive": "drive"}


def _consent_message(product_links: list[tuple[str, str]]) -> str:
    """Build the consent message.

    Single product: classic 'tap: <url>' phrasing.
    Multi product: only the FIRST URL is exposed because the redirect
    chain walks the rest after a single tap.
    """
    if len(product_links) == 1:
        product, url = product_links[0]
        return (
            f"need {_PRODUCT_LABEL[product]} to be useful. one-time read "
            f"so i learn who matters to you. tap: {url}"
        )
    products = " + ".join(_PRODUCT_LABEL[p] for p, _ in product_links)
    first_url = product_links[0][1]
    return (
        f"need {products} to be useful. one tap covers all of them: {first_url}"
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

    existing: list[tuple[str, str]] = []
    for product in products:
        row = await state.get_integration_status(user_id, provider, product)
        existing.append((product, row.status if row else "absent"))

    if all(s == "connected" for _, s in existing):
        return {
            "status": "already_connected",
            "url": None,
            "message": "already connected",
        }

    pending_products = [p for p, s in existing if s != "connected"]
    toolkits = [_PRODUCT_TO_TOOLKIT[p] for p in pending_products]

    toolkit_to_ac = await composio_meta.resolve_auth_configs(
        toolkits=toolkits, user_id=user_id
    )
    chain = await composio_meta.initiate_oauth_chain(
        user_id=user_id,
        toolkit_to_auth_config=toolkit_to_ac,
    )

    # chain["chain"] preserves toolkit order from toolkit_to_ac, which we
    # built from pending_products, so this re-projection lines up.
    product_links: list[tuple[str, str]] = []
    for entry in chain["chain"]:
        product = _TOOLKIT_TO_PRODUCT.get(entry["toolkit"])
        if product:
            product_links.append((product, entry["redirect_url"]))

    for product in products:
        await state.upsert_pending(user_id, provider, product)

    if not product_links:
        return {
            "status": "error",
            "url": None,
            "message": "composio returned no redirect urls",
        }

    return {
        "status": "url_sent",
        "url": product_links[0][1],
        "urls": {p: u for p, u in product_links},
        "message": _consent_message(product_links),
    }
