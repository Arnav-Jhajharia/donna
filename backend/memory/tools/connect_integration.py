"""connect_integration — get a SINGLE OAuth URL for any Composio toolkit(s).

Builds a Composio redirect chain so the user only taps once even when we
need multiple toolkits at the same time (e.g. gmail + calendar + drive,
or slack + notion). Each toolkit's ``callback_url`` points to the next
toolkit's ``redirect_url`` so the browser walks the chain after a single
OAuth approval. Backed by ``composio_meta.resolve_auth_configs``
(auto-provisions managed toolkits on first use) and
``composio_meta.initiate_oauth_chain``.

Mirror state in our own ``integrations`` table so the [INTEGRATIONS]
context block stays informative without polling Composio. Google
toolkits keep their friendly ``provider="google"`` rows so the existing
[INTEGRATIONS] line-format and downstream typed tools (gmail / calendar)
stay readable; everything else lands as ``provider="composio"`` with
the toolkit slug as the product.
"""
from __future__ import annotations

import os
from typing import Any

from backend.integrations import composio_meta, state
from donna_runtime.observability import instrument_memory_op


def _donna_final_callback() -> str | None:
    """Where the OAuth chain lands after the last toolkit completes.

    Without this, ``initiate_oauth_chain`` defaults to Composio's own
    dashboard ``platform.composio.dev/dashboard`` — which is jarring for
    the user (they expect to land back on Donna). We point at the Donna
    dashboard root: authed users see their canvas, unauthed users see
    the landing page. Either is better than Composio's UI.
    """
    base = (os.environ.get("DASHBOARD_BASE_URL") or "").rstrip("/")
    if not base:
        return None
    return f"{base}/?integration=connected"

DESCRIPTION = (
    "Generate a one-tap connect link for one or more Composio toolkits. "
    "Pass any toolkit slug(s): google's are gmail, googlecalendar, "
    "googledrive; others include slack, notion, linear, github, asana, "
    "hubspot, salesforce, intercom, etc. Use when:\n"
    "  - the [INTEGRATIONS] context block shows a needed toolkit as not_connected\n"
    "  - the user asks for something requiring an integration that is not connected\n"
    "  - the user explicitly asks to connect a service\n"
    "Do NOT use when:\n"
    "  - the toolkit is already connected (check [INTEGRATIONS] first)\n"
    "  - status is 'pending' — a link is already in flight; do not nag\n"
    "  - the user is mid-task and a connect prompt would derail them\n"
    "Returns a one-line consent message containing a SINGLE URL — the "
    "redirect chain covers every requested toolkit. Forward verbatim."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "toolkits": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": (
                "Composio toolkit slug(s). Examples: gmail, googlecalendar, "
                "googledrive, slack, notion, linear, github, asana."
            ),
        },
    },
    "required": ["toolkits"],
}

# Friendly product alias -> Composio toolkit slug. Lets the model pass
# "calendar" or "drive" and still get the right google toolkit. All other
# toolkits use their composio slug verbatim.
_ALIAS_TO_TOOLKIT: dict[str, str] = {
    "gmail": "gmail",
    "calendar": "googlecalendar",
    "googlecalendar": "googlecalendar",
    "drive": "googledrive",
    "googledrive": "googledrive",
}

# The reverse mapping lets us label google rows with friendly product names
# in the integrations table so the [INTEGRATIONS] block stays clean
# (google_gmail, google_calendar, google_drive).
_GOOGLE_TOOLKIT_TO_PRODUCT: dict[str, str] = {
    "gmail": "gmail",
    "googlecalendar": "calendar",
    "googledrive": "drive",
}

_LABELS: dict[str, str] = {
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
}


def _normalize_toolkits(raw: list[str]) -> list[str]:
    """De-duplicate while preserving order, applying friendly aliases."""
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        slug = _ALIAS_TO_TOOLKIT.get(item, item)
        if slug in seen:
            continue
        seen.add(slug)
        out.append(slug)
    return out


def _provider_product(toolkit: str) -> tuple[str, str]:
    """Map a toolkit slug to (provider, product) for the integrations table.

    Google toolkits keep ``provider="google"`` so the existing [INTEGRATIONS]
    block + downstream typed tools (list_gmail_recent, list_calendar) stay
    coherent. Everything else lands under ``provider="composio"``.
    """
    if toolkit in _GOOGLE_TOOLKIT_TO_PRODUCT:
        return "google", _GOOGLE_TOOLKIT_TO_PRODUCT[toolkit]
    return "composio", toolkit


def _label(toolkit: str) -> str:
    return _LABELS.get(toolkit, toolkit)


def _consent_message(toolkit_links: list[tuple[str, str]]) -> str:
    """Build the consent message.

    Single toolkit: classic 'tap: <url>' phrasing.
    Multi toolkit: only the FIRST URL is exposed because the redirect
    chain walks the rest after a single tap.

    Donna voice; the donna_runtime tool wrapper forwards this verbatim,
    so it's the line the user actually sees.
    """
    if len(toolkit_links) == 1:
        toolkit, url = toolkit_links[0]
        return (
            f"need {_label(toolkit)} to be useful. one-time read "
            f"so i learn who matters to you. tap: {url}\n"
            f"link's good for a few minutes."
        )
    products = " + ".join(_label(t) for t, _ in toolkit_links)
    first_url = toolkit_links[0][1]
    return (
        f"need {products} to be useful. one tap covers all of them: "
        f"{first_url}\nlink's good for a few minutes."
    )


@instrument_memory_op("integrations.connect")
async def connect_integration(
    user_id: str,
    toolkits: list[str] | None = None,
    *,
    provider: str | None = None,
    products: list[str] | None = None,
) -> dict[str, Any]:
    """Build a one-tap OAuth chain for the given toolkit(s).

    Accepts either ``toolkits=[...]`` (preferred, generic) or the legacy
    ``provider="google", products=[...]`` shape (still callable from older
    code paths and tests).
    """
    raw: list[str] = []
    if toolkits:
        raw = list(toolkits)
    elif products:
        raw = list(products)

    requested = _normalize_toolkits([str(t).strip() for t in raw if str(t).strip()])
    if not requested:
        return {
            "status": "error",
            "url": None,
            "message": "no toolkits specified",
        }

    # Read existing rows for the requested toolkits in one pass so we can
    # decide between cached-URL reuse, fresh issuance, and short-circuit.
    rows: dict[str, object] = {}
    statuses: list[tuple[str, str]] = []
    for tk in requested:
        prov, prod = _provider_product(tk)
        row = await state.get_integration_status(user_id, prov, prod)
        rows[tk] = row
        statuses.append((tk, row.status if row else "absent"))

    if all(s == "connected" for _, s in statuses):
        return {
            "status": "already_connected",
            "url": None,
            "message": "already connected",
        }

    # If every NOT-yet-connected toolkit has a fresh cached URL pointing
    # at the same chain head, hand back the same URL. The chain walks the
    # remaining toolkits after the user taps once.
    pending_rows = [rows[tk] for tk, s in statuses if s != "connected"]
    if pending_rows and all(state.is_redirect_url_fresh(r) for r in pending_rows):
        urls = {tk: rows[tk].redirect_url for tk, s in statuses if s != "connected"}
        # Defensive: if the rows happen to disagree on URL (shouldn't,
        # since we wrote them in the same call), fall through and re-issue.
        head_url = next(iter(urls.values()))
        if all(u == head_url for u in urls.values()):
            ordered = [(tk, urls[tk]) for tk in requested if tk in urls]
            return {
                "status": "url_sent",
                "url": head_url,
                "toolkits": [t for t, _ in ordered],
                "urls": {t: u for t, u in ordered},
                "message": _consent_message(ordered),
                "cached": True,
            }

    pending_toolkits = [tk for tk, s in statuses if s != "connected"]

    toolkit_to_ac = await composio_meta.resolve_auth_configs(
        toolkits=pending_toolkits, user_id=user_id
    )
    chain_kwargs: dict[str, Any] = {
        "user_id": user_id,
        "toolkit_to_auth_config": toolkit_to_ac,
    }
    final_callback = _donna_final_callback()
    if final_callback:
        chain_kwargs["final_callback_url"] = final_callback
    chain = await composio_meta.initiate_oauth_chain(**chain_kwargs)

    toolkit_links: list[tuple[str, str]] = []
    for entry in chain["chain"]:
        toolkit_links.append((entry["toolkit"], entry["redirect_url"]))

    if not toolkit_links:
        return {
            "status": "error",
            "url": None,
            "message": "couldn't generate the connect link, try again in a sec",
        }

    # Cache the chain HEAD URL on every requested-toolkit row so any
    # follow-up call within the freshness window returns the same URL.
    head_url = toolkit_links[0][1]
    for tk in requested:
        prov, prod = _provider_product(tk)
        await state.upsert_pending(
            user_id, prov, prod, redirect_url=head_url
        )

    return {
        "status": "url_sent",
        "url": head_url,
        "toolkits": [t for t, _ in toolkit_links],
        # Keep "urls" keyed by toolkit slug for downstream consumers.
        # Watcher + post-tool hook now consume slugs directly.
        "urls": {t: u for t, u in toolkit_links},
        "message": _consent_message(toolkit_links),
        "cached": False,
    }
