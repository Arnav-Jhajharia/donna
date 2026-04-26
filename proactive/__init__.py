"""Proactive engine — Tiered Judgment + Hold Lane (v1).

See ``docs/superpowers/specs/2026-04-26-proactive-engine-design.md`` for the
full design. The package is the unified path for any source (gmail webhook,
attention fire, attention offer, future calendar/pattern noticer) to surface
something to the user. Tier 1 deterministic scorers feed a canonical
``ProactiveEvent`` envelope into ``dispatcher.dispatch``, which:

  1. consults the unified arbiter (quota / cooldown / quiet hours / topic
     cooldown / active-chat),
  2. asks the cheap Tier 2 judge (Haiku 4.5) ping / hold / drop,
  3. ships, holds, or escalates to the Tier 3 brain.

Phase 0 lays the scaffold. Phase 1 wires email mirror-mode. Phase 2 flips
``DONNA_PROACTIVE_TIERED=1`` and the dispatcher actually ships drafts.
"""
from __future__ import annotations

from proactive.events import (
    ProactiveEvent,
    ProactiveSource,
    make_event_from_email,
)
from proactive.judge import JudgeResult, judge_event

__all__ = (
    "ProactiveEvent",
    "ProactiveSource",
    "JudgeResult",
    "judge_event",
    "make_event_from_email",
)
