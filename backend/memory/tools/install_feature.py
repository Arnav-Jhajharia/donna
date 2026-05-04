"""install_feature — install a system feature manifest for the user.

Wraps ``backend.features.install.install_feature``. The BRAIN tool
surface (registered in ``donna_runtime.tools``) calls this with the
template_id and an optional config override map. Returns a short status
string the BRAIN can fold into a send_burst.

Re-installing the same template is a no-op that returns "already
installed". Missing required integrations fail with a clear "connect X
first" message rather than a generic error.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.memory.tools._shape import ToolResult, degraded, ok
from donna_runtime.observability import instrument_memory_op

logger = logging.getLogger(__name__)


DESCRIPTION = (
    "Install a system feature for the user (e.g. hydration tracker). "
    "A feature ties together attentions + observations + cron + dashboard "
    "cards into one composable unit. Pass `template_id` (the slug from the "
    "feature library — e.g. 'hydration_tracker') and optional `config` to "
    "override the manifest's defaults (e.g. {'target_glasses': 10}). "
    "Re-installing the same template for the same user is a safe no-op. "
    "Use when the user explicitly opts into a feature (\"track my water\") "
    "or accepts an offer. Do NOT use to install an unknown template — call "
    "with a known slug only. Do NOT use to mutate config of an already-"
    "installed feature; that is a Phase 2 surface."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "template_id": {
            "type": "string",
            "description": (
                "Feature template slug (e.g. 'hydration_tracker')."
            ),
        },
        "config": {
            "type": "object",
            "description": (
                "Optional config overrides. Keys must match the manifest's "
                "config_schema (e.g. {'target_glasses': 10})."
            ),
        },
    },
    "required": ["template_id"],
}


@instrument_memory_op("features.install")
async def install_feature(
    user_id: str,
    template_id: str,
    config: dict[str, Any] | None = None,
) -> ToolResult:
    """Install a feature for ``user_id``.

    Returns ``ok`` with a short status string + the feature id on
    success, ``degraded`` on a missing integration or unknown template
    so the BRAIN can surface a clear next step instead of silently
    succeeding.
    """
    if not user_id or not template_id:
        return degraded("missing user_id or template_id")
    try:
        from backend.features.install import (
            MissingIntegrationError,
            install_feature as _install_feature,
        )
    except Exception as exc:
        logger.exception("install_feature: import failed")
        return degraded(f"feature subsystem unavailable: {exc}")

    try:
        result = await _install_feature(
            user_id=user_id,
            template_id=template_id,
            config_overrides=config or None,
        )
    except MissingIntegrationError as exc:
        return degraded(
            f"connect {', '.join(exc.missing)} first to install this feature"
        )
    except ValueError as exc:
        return degraded(str(exc))
    except Exception as exc:
        logger.exception("install_feature failed")
        return degraded(f"install failed: {exc}")

    if not result.created:
        return ok(
            {
                "status": "already_installed",
                "feature_id": result.feature_id,
                "template_id": template_id,
                "message": f"{template_id} is already on for you",
            }
        )
    return ok(
        {
            "status": "installed",
            "feature_id": result.feature_id,
            "template_id": template_id,
            "attention_ids": list(result.attention_ids),
            "schedule_ids": list(result.schedule_ids),
            "message": f"{template_id} is on. carry on.",
        }
    )
