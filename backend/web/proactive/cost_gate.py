"""Single env switch to pause all automated Exa burn.

Set ``DONNA_EXA_AUTOMATION_PAUSE=1`` in the environment to disable every
recurring code path that calls Exa without an explicit user request:

- ``subscriptions.provision_pending_websets``    (no new websets)
- ``poller.poll_pending_subscriptions``          (no /search, no items GET)
- ``url_similar.poll_url_similar_signals``       (no /findSimilar)
- ``dry_run.ExaWebFetcher``                      (attention probes return [])

User-facing surfaces (BRAIN tools like web_search, recall, research) are
NOT gated by this — those are explicit user actions, not automation, and
the user-experience cost of cutting them is high relative to credit burn.

Use case: emergency stop when Exa burn surprises you. Flip the env on
Railway, automation pauses in <1 min without redeploying.
"""
from __future__ import annotations

import os

_ENV = "DONNA_EXA_AUTOMATION_PAUSE"


def exa_automation_paused() -> bool:
    """True when the operator has paused all automated Exa burn."""
    return os.environ.get(_ENV, "0").strip() == "1"
