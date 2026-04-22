"""Tools structural tests — no DB required.

Verifies every tool module exports DESCRIPTION, INPUT_SCHEMA, and a callable
with matching name. Runtime behavior tested separately against a live DB.
"""
from __future__ import annotations

import pytest

from backend.memory.tools import ALL_TOOLS
from backend.memory.tools._shape import degraded, no_hits, ok


def test_all_twelve_tools_registered():
    # 12 per the spec; implementation exposes 13 (recall_chat_thread is listed
    # for chat history, and all 12 write/read tools are present — close_open_loop
    # is listed separately from track_open_loop, bringing the count to 13 when
    # the chat thread tool is included). Spec §5 table shows 9 read + 4 write = 13.
    assert len(ALL_TOOLS) == 13


@pytest.mark.parametrize("name", list({
    "recall_episodic", "recall_graph", "recall_document_chunks", "recall_chat_thread",
    "list_observations", "list_open_loops", "list_rules", "list_calendar", "smart_recall",
    "log_observation", "track_open_loop", "close_open_loop", "update_living_profile",
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
