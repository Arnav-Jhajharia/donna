from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .data import LIVING_PROFILE


@dataclass(frozen=True)
class DonnaUserContext:
    user_id: str | None
    living_profile: str
    tracker_snapshot: dict[str, Any]

    def render_system_context(self) -> str:
        lines = [
            "## Runtime Context",
            f"User id: {self.user_id or 'unknown'}",
            "",
            "## Tracker Snapshot",
            json.dumps(self.tracker_snapshot, indent=2, sort_keys=True),
        ]
        return "\n".join(lines)


def build_user_context(user_id: str | None = None) -> DonnaUserContext:
    return DonnaUserContext(
        user_id=user_id,
        living_profile=LIVING_PROFILE,
        tracker_snapshot={},
    )
