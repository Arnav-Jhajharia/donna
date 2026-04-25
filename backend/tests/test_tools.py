"""Tools structural tests — no DB required.

Verifies every tool module exports DESCRIPTION, INPUT_SCHEMA, and a callable
with matching name. Runtime behavior tested separately against a live DB.
"""
from __future__ import annotations

import pytest

from backend.memory.tools import ALL_TOOLS
from backend.memory.tools._shape import degraded, no_hits, ok


def test_all_memory_tools_registered():
    # Original memory surface + temporal situation-brief maintenance +
    # bi-temporal time resolver + composio integrations (connect, gmail
    # list/thread).
    assert len(ALL_TOOLS) == 21


@pytest.mark.parametrize("name", list({
    "recall_episodic", "recall_graph", "recall_document_chunks", "recall_chat_thread",
    "list_observations", "list_open_loops", "list_rules", "list_calendar",
    "list_gmail_recent", "read_gmail_thread",
    "read_situation_brief", "smart_recall", "refresh_situation_brief",
    "log_observation", "track_open_loop", "close_open_loop", "set_timezone", "schedule_reminder",
    "resolve_time_expression", "update_living_profile", "connect_integration",
}))
def test_tool_module_surface(name):
    mod = ALL_TOOLS[name]
    assert isinstance(mod.DESCRIPTION, str) and mod.DESCRIPTION
    assert isinstance(mod.INPUT_SCHEMA, dict)
    assert mod.INPUT_SCHEMA.get("type") == "object"
    fn = getattr(mod, name)
    assert callable(fn)


def test_tool_result_shape_helpers():
    assert ok(1)["status"] == "ok"
    assert no_hits()["status"] == "no_hits"
    assert no_hits()["payload"] == []
    d = degraded("nope")
    assert d["status"] == "degraded"
    assert d["payload"]["reason"] == "nope"


def test_backend_db_imports_root_models():
    from backend.db.models import Base as BackendBase, User as BackendUser
    from backend.db.session import async_session as backend_session
    from db.models import Base as RootBase, User as RootUser
    from db.session import async_session as root_session

    assert BackendBase is RootBase
    assert BackendUser is RootUser
    assert backend_session is root_session


def test_log_observation_coerces_event_time_to_naive_utc():
    from backend.memory.tools.log_observation import _coerce_event_time

    dt = _coerce_event_time("2026-04-21T10:30:00+08:00")

    assert dt.isoformat() == "2026-04-21T02:30:00"


def test_log_observation_coerces_naive_event_time_from_user_timezone():
    from backend.memory.tools.log_observation import _coerce_event_time

    dt = _coerce_event_time("2026-04-21T10:30:00", "Asia/Singapore")

    assert dt.isoformat() == "2026-04-21T02:30:00"
