"""Tests for the proactive query-creation reasoner.

The Haiku seam (``call_structured``) is monkey-patched. We never hit the
network. These tests verify validation, clamping, truncation, and the
zero-move-is-valid contract.
"""
from __future__ import annotations

from typing import Any

import pytest

from backend.web.proactive import query_creation as qc
from backend.web.proactive.types import ProactiveContext


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _ctx(**overrides: Any) -> ProactiveContext:
    base: dict[str, Any] = {
        "user_id": "u_test",
        "profile_blurb": "user is building donna; mentions poke + limitless",
        "situation_brief": "open loop: pick pitch hardware before antler",
        "recent_thread": "user: poke just shipped a new revision",
        "current_datetime": "2026-04-25T14:00:00",
    }
    base.update(overrides)
    return ProactiveContext(**base)


class _Raw:
    """Mimics a pydantic _RawMove without invoking validation paths."""

    def __init__(
        self,
        *,
        rationale: str = "user mentioned poke 2 days ago; new launch today.",
        tool: str = "search",
        query: str = "poke ai hardware launch 2026-04-25",
        params: dict[str, Any] | None = None,
        urgency: float | str = 0.8,
        render_hint: str = "short_text",
        dedup_key: str = "watch:poke_launch",
    ) -> None:
        self.rationale = rationale
        self.tool = tool
        self.query = query
        self.params = params or {}
        self.urgency = urgency
        self.render_hint = render_hint
        self.dedup_key = dedup_key


class _Out:
    def __init__(self, moves: list[_Raw]) -> None:
        self.moves = moves


def _patch(monkeypatch: pytest.MonkeyPatch, result: Any) -> None:
    async def fake(**kwargs: Any) -> Any:
        return result

    monkeypatch.setattr(qc, "call_structured", fake)


# ---------------------------------------------------------------------------
# Haiku-unavailable / silence paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_empty_when_call_structured_returns_none(monkeypatch):
    _patch(monkeypatch, None)
    moves = await qc.create_proactive_moves(_ctx())
    assert moves == []


@pytest.mark.asyncio
async def test_returns_empty_when_call_structured_raises(monkeypatch):
    async def boom(**kwargs: Any) -> Any:
        raise RuntimeError("haiku down")

    monkeypatch.setattr(qc, "call_structured", boom)
    moves = await qc.create_proactive_moves(_ctx())
    assert moves == []


@pytest.mark.asyncio
async def test_zero_moves_is_valid(monkeypatch):
    _patch(monkeypatch, _Out(moves=[]))
    moves = await qc.create_proactive_moves(_ctx())
    assert moves == []


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_emits_validated_moves(monkeypatch):
    raws = [
        _Raw(
            rationale="user said pitch hardware decision pending; poke launched today.",
            tool="search",
            query="poke v2 launch coverage 2026-04-25",
            params={"category": "company", "maxAgeHours": 24},
            urgency=0.9,
            render_hint="card",
            dedup_key="watch:poke_launch",
        ),
        _Raw(
            rationale="user comparing poke vs limitless 3 days ago.",
            tool="research",
            query="how do poke and limitless ai differ as pitch hardware",
            params={},
            urgency=0.4,
            render_hint="long_text",
            dedup_key="compare:poke_vs_limitless",
        ),
    ]
    _patch(monkeypatch, _Out(moves=raws))
    moves = await qc.create_proactive_moves(_ctx())
    assert len(moves) == 2
    first, second = moves
    assert first.tool == "search"
    assert first.urgency == 0.9
    assert first.render_hint == "card"
    assert first.dedup_key == "watch:poke_launch"
    assert first.params == {"category": "company", "maxAgeHours": 24}
    assert second.tool == "research"
    assert second.render_hint == "long_text"


# ---------------------------------------------------------------------------
# field-level validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_tool_dropped(monkeypatch):
    raws = [
        _Raw(tool="nonsense", dedup_key="x"),
        _Raw(tool="search", dedup_key="y"),
    ]
    _patch(monkeypatch, _Out(moves=raws))
    moves = await qc.create_proactive_moves(_ctx())
    assert len(moves) == 1
    assert moves[0].dedup_key == "y"


@pytest.mark.asyncio
async def test_unknown_render_hint_falls_back_to_short_text(monkeypatch):
    raws = [_Raw(render_hint="opera", dedup_key="z")]
    _patch(monkeypatch, _Out(moves=raws))
    moves = await qc.create_proactive_moves(_ctx())
    assert len(moves) == 1
    assert moves[0].render_hint == "short_text"


@pytest.mark.asyncio
async def test_empty_query_dropped(monkeypatch):
    raws = [_Raw(query="   ", dedup_key="a")]
    _patch(monkeypatch, _Out(moves=raws))
    moves = await qc.create_proactive_moves(_ctx())
    assert moves == []


@pytest.mark.asyncio
async def test_empty_dedup_key_dropped(monkeypatch):
    raws = [_Raw(dedup_key="   ")]
    _patch(monkeypatch, _Out(moves=raws))
    moves = await qc.create_proactive_moves(_ctx())
    assert moves == []


# ---------------------------------------------------------------------------
# clamping + truncation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_urgency_clamped_high(monkeypatch):
    raws = [_Raw(urgency=1.5)]
    _patch(monkeypatch, _Out(moves=raws))
    moves = await qc.create_proactive_moves(_ctx())
    assert moves[0].urgency == 1.0


@pytest.mark.asyncio
async def test_urgency_clamped_low(monkeypatch):
    raws = [_Raw(urgency=-0.4)]
    _patch(monkeypatch, _Out(moves=raws))
    moves = await qc.create_proactive_moves(_ctx())
    assert moves[0].urgency == 0.0


@pytest.mark.asyncio
async def test_urgency_unparseable_defaults_to_half(monkeypatch):
    raws = [_Raw(urgency="not-a-number")]
    _patch(monkeypatch, _Out(moves=raws))
    moves = await qc.create_proactive_moves(_ctx())
    assert moves[0].urgency == 0.5


@pytest.mark.asyncio
async def test_rationale_truncated_at_300(monkeypatch):
    raws = [_Raw(rationale="x" * 1000)]
    _patch(monkeypatch, _Out(moves=raws))
    moves = await qc.create_proactive_moves(_ctx())
    assert len(moves[0].rationale) == 300


@pytest.mark.asyncio
async def test_query_truncated_at_500(monkeypatch):
    raws = [_Raw(query="q" * 800)]
    _patch(monkeypatch, _Out(moves=raws))
    moves = await qc.create_proactive_moves(_ctx())
    assert len(moves[0].query) == 500


@pytest.mark.asyncio
async def test_dedup_key_truncated_at_120(monkeypatch):
    raws = [_Raw(dedup_key="k" * 500)]
    _patch(monkeypatch, _Out(moves=raws))
    moves = await qc.create_proactive_moves(_ctx())
    assert len(moves[0].dedup_key) == 120


# ---------------------------------------------------------------------------
# max_moves cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_moves_caps_list(monkeypatch):
    raws = [_Raw(dedup_key=f"k{i}") for i in range(5)]
    _patch(monkeypatch, _Out(moves=raws))
    moves = await qc.create_proactive_moves(_ctx(), max_moves=2)
    assert len(moves) == 2
    assert [m.dedup_key for m in moves] == ["k0", "k1"]


@pytest.mark.asyncio
async def test_max_moves_zero_yields_no_moves(monkeypatch):
    raws = [_Raw(dedup_key="k")]
    _patch(monkeypatch, _Out(moves=raws))
    moves = await qc.create_proactive_moves(_ctx(), max_moves=0)
    assert moves == []


# ---------------------------------------------------------------------------
# context formatting (no LLM involved)
# ---------------------------------------------------------------------------


def test_format_context_includes_all_present_sections():
    ctx = _ctx(last_proactive_at="2026-04-25T09:00:00")
    block = qc._format_context(ctx)
    assert "Current local time: 2026-04-25T14:00:00" in block
    assert "Last proactive turn: 2026-04-25T09:00:00" in block
    assert "## Living Profile" in block
    assert "## Situation Brief" in block
    assert "## Recent thread" in block
    assert "Return moves now" in block


def test_format_context_omits_blank_sections():
    ctx = ProactiveContext(user_id="u", current_datetime="2026-04-25T14:00:00")
    block = qc._format_context(ctx)
    assert "## Living Profile" not in block
    assert "## Situation Brief" not in block
    assert "## Recent thread" not in block
    assert "Current local time" in block
