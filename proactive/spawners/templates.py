"""Templates loader — single source of truth for spawner mappings.

Loaded once at module import. Tunable as a config change rather than
a code change. ``DONNA_SPAWNER_TEMPLATES_PATH`` overrides the location
for tests.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _default_path() -> Path:
    env = os.environ.get("DONNA_SPAWNER_TEMPLATES_PATH")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent / "templates.json"


def _load_templates(path: Path | None = None) -> dict[str, Any]:
    p = path or _default_path()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("spawner: templates.json missing at %s", p)
        return {"calendar": {}, "observation": {}}
    except json.JSONDecodeError:
        logger.exception("spawner: templates.json invalid JSON at %s", p)
        return {"calendar": {}, "observation": {}}


_CACHED: dict[str, Any] | None = None


def calendar_templates() -> dict[str, Any]:
    return _all().get("calendar", {})


def observation_templates() -> dict[str, Any]:
    return _all().get("observation", {})


def _all() -> dict[str, Any]:
    global _CACHED
    if _CACHED is None:
        _CACHED = _load_templates()
    return _CACHED


def reload() -> None:
    """Force re-read of the templates file. Used by tests."""
    global _CACHED
    _CACHED = _load_templates()
