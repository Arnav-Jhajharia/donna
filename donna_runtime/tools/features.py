"""BRAIN tools for the Features primitive.

Wraps ``backend.features.install`` + ``backend.features.lifecycle`` with
``@tool`` registrations so the SDK loop can call them. Each tool is a
thin adapter: parses args, calls the backend, formats a short response.
The backend functions own all side-effects and validation — the tool
layer only translates between the BRAIN's JSON arg shape and the typed
backend signatures.

Tools registered here:
  - install_feature
  - pause_feature / resume_feature / archive_feature
  - list_features
  - update_feature_config
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from claude_agent_sdk import tool

from ..langsmith_tracing import traceable
from ..tool_logic import text_content
from ._shared import _current_user_id

logger = logging.getLogger(__name__)


# -- install_feature --------------------------------------------------------


@tool(
    "install_feature",
    (
        "Install a system feature for the user (hydration tracker, "
        "gratitude practice, inbox brief, etc.). A feature ties together "
        "attentions + observations + cron + dashboard cards into one "
        "composable unit so the user can pause/resume/archive it as a "
        "whole.\n\n"
        "Pass `template_id` (the slug from the feature library — e.g. "
        "'hydration_tracker') and optional `config` to override the "
        "manifest's defaults (e.g. {'target_glasses': 10}). Re-installing "
        "the same template for the same user is a safe no-op.\n\n"
        "Use when the user explicitly opts into a feature ('track my water', "
        "'start a gratitude practice') or accepts an offer Donna made. "
        "Do NOT use for unknown templates — call only with a known slug. "
        "Do NOT use to mutate config of an already-installed feature; use "
        "update_feature_config instead."
    ),
    {
        "type": "object",
        "required": ["template_id"],
        "properties": {
            "template_id": {
                "type": "string",
                "description": "Feature template slug (e.g. 'hydration_tracker').",
            },
            "config": {
                "type": "object",
                "description": (
                    "Optional config overrides. Keys must match the "
                    "manifest's config_schema (e.g. {'target_glasses': 10})."
                ),
            },
        },
    },
)
@traceable(name="donna.tool.install_feature", run_type="tool")
async def install_feature(args):
    user_id = _current_user_id()
    if not user_id:
        return text_content("install failed: no user_id in scope.")

    template_id = str(args.get("template_id") or "").strip()
    config = args.get("config") or None
    if not template_id:
        return text_content("install failed: 'template_id' is required.")
    if config is not None and not isinstance(config, dict):
        return text_content("install failed: 'config' must be an object.")

    try:
        from backend.features.install import (
            MissingIntegrationError,
            install_feature as _install_feature,
        )
    except Exception:
        logger.exception("install_feature: import failed")
        return text_content("install failed: feature subsystem unavailable.")

    try:
        result = await _install_feature(
            user_id=user_id,
            template_id=template_id,
            config_overrides=config,
        )
    except MissingIntegrationError as exc:
        return text_content(
            f"connect {', '.join(exc.missing)} first to install {template_id}."
        )
    except ValueError as exc:
        return text_content(f"install failed: {exc}")
    except Exception:
        logger.exception("install_feature: backend failed")
        return text_content("install failed: backend error.")

    if not result.created:
        return text_content(f"{template_id} already on. carry on.")
    return text_content(
        f"{template_id} installed (feature_id={result.feature_id}, "
        f"{len(result.attention_ids)} attention(s), "
        f"{len(result.schedule_ids)} schedule(s))."
    )


# -- pause_feature ----------------------------------------------------------


@tool(
    "pause_feature",
    (
        "Pause a feature: stop firing reminders + cron, freeze attentions, "
        "but keep observations + state intact. Optional `until` ISO "
        "timestamp schedules an auto-resume (vacation mode).\n\n"
        "Pass either `template_id` ('hydration_tracker') OR `feature_id`. "
        "Use when the user says 'pause my water tracking', 'mute hydration "
        "for the week', 'stop the gratitude prompts'. Use template_id if "
        "the user mentioned the feature by name — feature_id is for "
        "internal flows.\n\n"
        "Do NOT use to dismiss a single reminder — that is cancel_reminder "
        "or snooze_attention. Do NOT use to delete data — that is "
        "archive_feature."
    ),
    {
        "type": "object",
        "properties": {
            "template_id": {"type": "string"},
            "feature_id": {"type": "string"},
            "until": {
                "type": "string",
                "description": (
                    "Optional ISO8601 UTC timestamp for auto-resume. "
                    "Leave empty to pause indefinitely."
                ),
            },
        },
    },
)
@traceable(name="donna.tool.pause_feature", run_type="tool")
async def pause_feature(args):
    user_id = _current_user_id()
    if not user_id:
        return text_content("pause failed: no user_id in scope.")

    template_id = (args.get("template_id") or "").strip() or None
    feature_id = (args.get("feature_id") or "").strip() or None
    until_raw = (args.get("until") or "").strip()

    if not (template_id or feature_id):
        return text_content("pause failed: pass template_id or feature_id.")

    until: datetime | None = None
    if until_raw:
        try:
            until = datetime.fromisoformat(until_raw.replace("Z", "+00:00"))
            until = until.astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            return text_content(f"pause failed: bad 'until' = {until_raw!r}.")

    try:
        from backend.features.lifecycle import pause_feature as _pause
    except Exception:
        logger.exception("pause_feature: import failed")
        return text_content("pause failed: feature subsystem unavailable.")

    feature = await _pause(
        user_id=user_id,
        feature_id=feature_id,
        template_id=template_id,
        until=until,
    )
    if feature is None:
        ref = template_id or feature_id
        return text_content(f"pause failed: feature {ref!r} not installed.")
    until_str = f" until {until.isoformat()}" if until else ""
    return text_content(f"{feature.template_id or feature.name} paused{until_str}.")


# -- resume_feature ---------------------------------------------------------


@tool(
    "resume_feature",
    (
        "Resume a previously paused feature: re-enable attentions, "
        "re-materialise the next cron fire, clear paused_until.\n\n"
        "Pass either `template_id` OR `feature_id`. Use when the user "
        "says 'turn hydration back on', 'resume gratitude', 'start tracking "
        "water again'. No-op if the feature was already active.\n\n"
        "Do NOT use to install a feature — that is install_feature."
    ),
    {
        "type": "object",
        "properties": {
            "template_id": {"type": "string"},
            "feature_id": {"type": "string"},
        },
    },
)
@traceable(name="donna.tool.resume_feature", run_type="tool")
async def resume_feature(args):
    user_id = _current_user_id()
    if not user_id:
        return text_content("resume failed: no user_id in scope.")

    template_id = (args.get("template_id") or "").strip() or None
    feature_id = (args.get("feature_id") or "").strip() or None
    if not (template_id or feature_id):
        return text_content("resume failed: pass template_id or feature_id.")

    try:
        from backend.features.lifecycle import resume_feature as _resume
    except Exception:
        logger.exception("resume_feature: import failed")
        return text_content("resume failed: feature subsystem unavailable.")

    feature = await _resume(
        user_id=user_id, feature_id=feature_id, template_id=template_id
    )
    if feature is None:
        ref = template_id or feature_id
        return text_content(f"resume failed: feature {ref!r} not installed.")
    return text_content(f"{feature.template_id or feature.name} resumed.")


# -- archive_feature --------------------------------------------------------


@tool(
    "archive_feature",
    (
        "Archive a feature: stop firing forever, transition all owned "
        "attentions to quietly_archived, cancel pending schedules. The "
        "feature row is kept (so a future re-install can re-attach to "
        "history) but the user feels it as 'gone'.\n\n"
        "Pass either `template_id` OR `feature_id`. Use when the user "
        "says 'I'm done tracking water', 'archive hydration', 'kill the "
        "gratitude practice'. Stronger than pause — only suggest when the "
        "user signals permanence. Re-installable later via install_feature.\n\n"
        "Do NOT use to silence a single reminder — that is snooze_attention "
        "or cancel_reminder."
    ),
    {
        "type": "object",
        "properties": {
            "template_id": {"type": "string"},
            "feature_id": {"type": "string"},
        },
    },
)
@traceable(name="donna.tool.archive_feature", run_type="tool")
async def archive_feature(args):
    user_id = _current_user_id()
    if not user_id:
        return text_content("archive failed: no user_id in scope.")

    template_id = (args.get("template_id") or "").strip() or None
    feature_id = (args.get("feature_id") or "").strip() or None
    if not (template_id or feature_id):
        return text_content("archive failed: pass template_id or feature_id.")

    try:
        from backend.features.lifecycle import archive_feature as _archive
    except Exception:
        logger.exception("archive_feature: import failed")
        return text_content("archive failed: feature subsystem unavailable.")

    feature = await _archive(
        user_id=user_id, feature_id=feature_id, template_id=template_id
    )
    if feature is None:
        ref = template_id or feature_id
        return text_content(f"archive failed: feature {ref!r} not installed.")
    return text_content(f"{feature.template_id or feature.name} archived.")


# -- list_features ----------------------------------------------------------


@tool(
    "list_features",
    (
        "List features installed for the user with their status, surface, "
        "and current config. Optional `status` filter ('active', 'paused', "
        "'archived'). Use when the user asks 'what am I tracking?', "
        "'what's on?', 'what features do I have?'. Use before pause / "
        "archive / update_feature_config to discover the right "
        "template_id.\n\n"
        "Do NOT use as a fishing tool — only call when the user asked or "
        "you genuinely need to discover a feature_id."
    ),
    {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["active", "paused", "archived"],
                "description": "Optional status filter.",
            },
        },
    },
)
@traceable(name="donna.tool.list_features", run_type="tool")
async def list_features(args):
    user_id = _current_user_id()
    if not user_id:
        return text_content("no features (no user_id).")

    status = (args.get("status") or "").strip() or None

    try:
        from backend.features.lifecycle import list_features as _list
    except Exception:
        logger.exception("list_features: import failed")
        return text_content("no features (subsystem unavailable).")

    rows = await _list(user_id=user_id, status=status)
    if not rows:
        return text_content("no features installed.")

    lines = ["features:"]
    for f in rows[:30]:
        cfg_summary = ", ".join(
            f"{k}={v}"
            for k, v in (f.config or {}).items()
            if not isinstance(v, dict)
        )[:80]
        line = (
            f"- {f.template_id or 'custom'} ({f.status}) — {f.name} "
            f"[{f.surface or 'no_surface'}]"
        )
        if cfg_summary:
            line += f"  config: {cfg_summary}"
        lines.append(line)
    if len(rows) > 30:
        lines.append(f"(showing 30 of {len(rows)})")
    return text_content("\n".join(lines))


# -- update_feature_config --------------------------------------------------


@tool(
    "update_feature_config",
    (
        "Patch a feature's user-config (e.g. change target_glasses from 8 "
        "to 10, push remind_every_min from 120 to 90). Only keys declared "
        "in the manifest's config_schema are accepted; unknown keys are "
        "rejected. Numeric values are clamped to declared min/max.\n\n"
        "Pass `template_id` OR `feature_id`, plus a `patch` object with "
        "the keys to update. Use when the user adjusts a feature's behavior "
        "('water target should be 10', 'remind me every 90 minutes', 'set "
        "quiet hours to 22-7'). Re-running install_feature does NOT update "
        "config — use this tool instead.\n\n"
        "Do NOT use to install or pause; those are install_feature / "
        "pause_feature."
    ),
    {
        "type": "object",
        "required": ["patch"],
        "properties": {
            "template_id": {"type": "string"},
            "feature_id": {"type": "string"},
            "patch": {
                "type": "object",
                "description": (
                    "Object with keys to update. e.g. {'target_glasses': 10}."
                ),
            },
        },
    },
)
@traceable(name="donna.tool.update_feature_config", run_type="tool")
async def update_feature_config(args):
    user_id = _current_user_id()
    if not user_id:
        return text_content("update failed: no user_id in scope.")

    template_id = (args.get("template_id") or "").strip() or None
    feature_id = (args.get("feature_id") or "").strip() or None
    patch = args.get("patch")
    if not (template_id or feature_id):
        return text_content("update failed: pass template_id or feature_id.")
    if not isinstance(patch, dict) or not patch:
        return text_content("update failed: 'patch' must be a non-empty object.")

    try:
        from backend.features.lifecycle import (
            update_feature_config as _update,
        )
    except Exception:
        logger.exception("update_feature_config: import failed")
        return text_content("update failed: feature subsystem unavailable.")

    try:
        feature = await _update(
            user_id=user_id,
            feature_id=feature_id,
            template_id=template_id,
            config_patch=patch,
        )
    except ValueError as exc:
        return text_content(f"update failed: {exc}")

    if feature is None:
        ref = template_id or feature_id
        return text_content(f"update failed: feature {ref!r} not installed.")
    cfg_summary = ", ".join(
        f"{k}={v}"
        for k, v in (feature.config or {}).items()
        if not isinstance(v, dict)
    )[:200]
    return text_content(
        f"{feature.template_id or feature.name} config updated: {cfg_summary}"
    )
