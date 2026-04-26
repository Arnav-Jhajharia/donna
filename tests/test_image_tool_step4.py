"""Step 4 tests: image caps — pure `_decide` logic + CapDecision shape.

All tests are pure-logic against the `_decide` function and the
`CapDecision` dataclass. No DB; `check()` and `record()` touch SQLAlchemy
and are covered later via the integration test (step 9).

Fixtures seed sent-times relative to a frozen `now`:
  T-2h   — within the 6h cooldown
  T-4h   — within the 6h cooldown
  T-7h   — outside cooldown, inside weekly window
  T-7d   — on the weekly-window boundary
  T-8d   — outside the weekly window entirely
"""
from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone

import pytest

from backend.memory.tools import image_caps
from backend.memory.tools.image_caps import (
    CapDecision,
    _as_naive_utc,
    _decide,
)
from donna_runtime.config import IMAGE_COOLDOWN_HOURS, IMAGE_WEEKLY_CAP


NOW = datetime(2026, 4, 25, 12, 0, 0)  # naive UTC


def _ago(hours: float = 0, days: float = 0) -> datetime:
    return NOW - timedelta(hours=hours, days=days)


class TestCapDecisionShape:
    def test_allow_is_frozen_and_empty_reason(self) -> None:
        d = CapDecision.allow()
        assert d.allowed is True
        assert d.reason == ""
        assert d.status == ""
        with pytest.raises(Exception):
            d.allowed = False  # type: ignore[misc]

    def test_deny_cooldown_reports_hours(self) -> None:
        d = CapDecision.deny_cooldown(4.0)
        assert d.allowed is False
        assert d.status == "denied_cooldown"
        assert "4h" in d.reason
        assert "no image this turn" in d.reason

    def test_deny_cooldown_rounds_minimum_to_1h(self) -> None:
        d = CapDecision.deny_cooldown(0.2)
        assert "1h" in d.reason

    def test_deny_cap_reports_days(self) -> None:
        d = CapDecision.deny_cap(3.0)
        assert d.allowed is False
        assert d.status == "denied_cap"
        assert "3d" in d.reason
        assert "weekly" in d.reason.lower()

    def test_deny_cap_rounds_minimum_to_1d(self) -> None:
        d = CapDecision.deny_cap(0.1)
        assert "1d" in d.reason


class TestDecideAllow:
    def test_no_history_allows(self) -> None:
        assert _decide(NOW, []).allowed is True

    def test_only_old_sent_outside_cooldown_allows(self) -> None:
        # 7h ago is past the 6h cooldown; only one in the window → below cap
        assert _decide(NOW, [_ago(hours=7)]).allowed is True

    def test_sent_older_than_7d_does_not_count(self) -> None:
        # 8 days ago falls outside the weekly window entirely
        sent = [_ago(days=8), _ago(days=8, hours=1), _ago(days=9)]
        assert _decide(NOW, sent).allowed is True


class TestDecideCooldown:
    def test_recent_sent_within_cooldown_denies(self) -> None:
        d = _decide(NOW, [_ago(hours=2)])
        assert d.allowed is False
        assert d.status == "denied_cooldown"

    def test_cooldown_uses_most_recent(self) -> None:
        # Most recent is 2h ago → 4h remaining; older 5h-ago is ignored
        d = _decide(NOW, [_ago(hours=5), _ago(hours=2)])
        assert d.status == "denied_cooldown"
        assert "4h" in d.reason

    def test_exactly_at_cooldown_boundary_allows(self) -> None:
        d = _decide(NOW, [_ago(hours=IMAGE_COOLDOWN_HOURS)])
        assert d.allowed is True


class TestDecideWeeklyCap:
    def test_at_weekly_cap_denies_even_if_cooldown_clear(self) -> None:
        # 3 sends, all outside cooldown, all inside the 7d window → cap
        sent = [_ago(hours=8), _ago(days=2), _ago(days=5)]
        assert len(sent) == IMAGE_WEEKLY_CAP
        d = _decide(NOW, sent)
        assert d.allowed is False
        assert d.status == "denied_cap"

    def test_over_weekly_cap_denies(self) -> None:
        sent = [_ago(hours=8), _ago(days=2), _ago(days=4), _ago(days=6)]
        d = _decide(NOW, sent)
        assert d.status == "denied_cap"

    def test_cap_takes_precedence_over_cooldown(self) -> None:
        # Three recent sends — cap message, not cooldown message
        sent = [_ago(hours=1), _ago(days=2), _ago(days=5)]
        d = _decide(NOW, sent)
        assert d.status == "denied_cap"

    def test_cap_reset_computed_from_oldest(self) -> None:
        # Oldest in window is 5d ago → resets ~2d from now
        sent = [_ago(hours=8), _ago(days=2), _ago(days=5)]
        d = _decide(NOW, sent)
        assert d.status == "denied_cap"
        assert "2d" in d.reason


class TestDecideTimezoneHandling:
    def test_aware_utc_sent_times_coerced(self) -> None:
        aware = datetime(2026, 4, 25, 10, 0, 0, tzinfo=timezone.utc)  # 2h ago
        d = _decide(NOW, [aware])
        assert d.status == "denied_cooldown"

    def test_mixed_naive_and_aware_times(self) -> None:
        times = [
            datetime(2026, 4, 25, 10, 0, 0, tzinfo=timezone.utc),  # 2h ago aware
            _ago(hours=5),  # naive
        ]
        d = _decide(NOW, times)
        # most recent after normalization is 2h ago → cooldown denies
        assert d.status == "denied_cooldown"

    def test_as_naive_utc_passthrough_for_naive(self) -> None:
        t = datetime(2026, 4, 25, 12, 0, 0)
        assert _as_naive_utc(t) is t  # no rewrap

    def test_as_naive_utc_strips_tzinfo_and_shifts(self) -> None:
        t = datetime(2026, 4, 25, 15, 0, 0, tzinfo=timezone(timedelta(hours=5)))
        n = _as_naive_utc(t)
        assert n.tzinfo is None
        assert n == datetime(2026, 4, 25, 10, 0, 0)  # shifted to UTC


class TestModuleImports:
    def test_module_imports_cleanly(self) -> None:
        mod = importlib.import_module("backend.memory.tools.image_caps")
        assert hasattr(mod, "CapDecision")
        assert hasattr(mod, "_decide")
        assert hasattr(mod, "check")
        assert hasattr(mod, "record")

    def test_public_api_names(self) -> None:
        assert callable(image_caps.check)
        assert callable(image_caps.record)
        assert callable(image_caps._decide)
