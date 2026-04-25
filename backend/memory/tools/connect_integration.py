"""connect_integration — get OAuth URL(s) for an external provider.

Delegates to Composio's COMPOSIO_MANAGE_CONNECTIONS meta-tool which handles
auth-config selection and per-toolkit OAuth init in one call. We keep our
own pending/connected mirror in the integrations table so the
[INTEGRATIONS] context block stays informative without polling Composio.
"""
from __future__ import annotations

from typing import Any

from backend.integrations import composio_meta, state
from donna_runtime.observability import instrument_memory_op

DESCRIPTION = (
    "Generate connect link(s) for an external provider (currently: google, "
    "covering calendar and gmail). Use when:\n"
    "  - the [INTEGRATIONS] context block shows the integration as not_connected\n"
    "  - the user asks for something requiring an integration that is not connected\n"
    "  - the user explicitly asks to connect a provider\n"
    "Do NOT use when:\n"
    "  - the integration is already connected (check [INTEGRATIONS] first)\n"
    "  - status is 'pending' — a link is already in flight; do not nag\n"
    "  - the user is mid-task and a connect prompt would derail them\n"
    "Returns a one-line consent message containing one URL per requested "
    "product. Forward verbatim. The user must tap each link."
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

_PRODUCT_TO_TOOLKIT = {
    "gmail": "gmail",
    "calendar": "googlecalendar",
}
_TOOLKIT_TO_PRODUCT = {v: k for k, v in _PRODUCT_TO_TOOLKIT.items()}
_PRODUCT_LABEL = {"gmail": "gmail", "calendar": "calendar"}


def _consent_message(product_links: list[tuple[str, str]]) -> str:
    """Build the consent message. Composio requires one OAuth click per
    toolkit (gmail and calendar are separate auth configs even on the same
    google account), so we include one tap line per pending product."""
    if len(product_links) == 1:
        product, url = product_links[0]
        return (
            f"need {_PRODUCT_LABEL[product]} to be useful. one-time read "
            f"so i learn who matters to you. tap: {url}"
        )
    products = " + ".join(_PRODUCT_LABEL[p] for p, _ in product_links)
    lines = [
        f"need {products} to be useful. one tap per service "
        f"(google requires a separate consent for each). then we're set:"
    ]
    for product, url in product_links:
        lines.append(f"  {_PRODUCT_LABEL[product]}: {url}")
    return "\n".join(lines)


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

    res = await composio_meta.manage_connections(
        user_id=user_id, toolkits=toolkits
    )

    # Preserve request order so the consent message reads in the order the
    # caller asked for (gmail first, calendar second, etc.). Composio's
    # results dict ordering is not guaranteed.
    results = res.get("results") or {}
    product_links: list[tuple[str, str]] = []
    for product in pending_products:
        toolkit = _PRODUCT_TO_TOOLKIT[product]
        payload = results.get(toolkit) or {}
        url = payload.get("redirect_url")
        if url:
            product_links.append((product, url))

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
        "url": product_links[0][1],  # primary url, kept for back-compat
        "urls": {p: u for p, u in product_links},
        "message": _consent_message(product_links),
    }
