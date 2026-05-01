"""Tests for the worth-telling judge."""
from __future__ import annotations

from typing import Any

import pytest

from backend.web.proactive import judge as judge_mod
from backend.web.proactive.types import (
    ProactiveContext,
    ProactiveMove,
    ProactiveResult,
)


def _ctx() -> ProactiveContext:
    return ProactiveContext(
        user_id="u",
        profile_blurb="user mentioned poke vs limitless 3d ago",
        situation_brief="open loop: pitch hardware decision",
        recent_thread="user: still picking",
        current_datetime="2026-04-25T14:00:00",
    )


def _move(**overrides: Any) -> ProactiveMove:
    base: dict[str, Any] = {
        "rationale": "user comparing poke vs limitless.",
        "tool": "search",
        "query": "poke v2 launch",
        "params": {},
        "urgency": 0.7,
        "render_hint": "short_text",
        "dedup_key": "watch:poke",
    }
    base.update(overrides)
    return ProactiveMove(**base)


def _result(
    status: str = "ok",
    payload: Any | None = None,
    skipped_reason: str | None = None,
) -> ProactiveResult:
    if payload is None and status == "ok":
        payload = {
            "results": [
                {
                    "url": "https://techcrunch.com/poke-v2",
                    "title": "Poke ships v2 with improved mic array",
                    "highlights": ["new mic array", "ship date 2026-04-25"],
                    "publishedDate": "2026-04-25",
                }
            ]
        }
    return ProactiveResult(
        move=_move(),
        status=status,  # type: ignore[arg-type]
        payload=payload,
        elapsed_ms=120,
        skipped_reason=skipped_reason,
    )


class _Out:
    def __init__(self, decision: str, draft: str = "", reason: str = ""):
        self.decision = decision
        self.draft = draft
        self.reason = reason


def _patch(monkeypatch: pytest.MonkeyPatch, returned: Any) -> None:
    async def fake(**kwargs: Any) -> Any:
        return returned

    monkeypatch.setattr(judge_mod, "call_structured", fake)


# ---------------------------------------------------------------------------
# pre-check shortcuts (no LLM)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_hits_status_short_circuits_to_silence(monkeypatch):
    called = {"n": 0}

    async def fake(**kwargs: Any) -> Any:
        called["n"] += 1
        return None

    monkeypatch.setattr(judge_mod, "call_structured", fake)
    verdict = await judge_mod.judge_result(
        context=_ctx(),
        result=_result(status="no_hits", payload={"results": []}),
    )
    assert verdict.decision == "silence"
    assert "no_hits" in verdict.reason
    assert called["n"] == 0  # never asked the model


@pytest.mark.asyncio
async def test_degraded_status_short_circuits(monkeypatch):
    monkeypatch.setattr(
        judge_mod,
        "call_structured",
        lambda **kw: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    verdict = await judge_mod.judge_result(
        context=_ctx(),
        result=_result(status="degraded", skipped_reason="exa 503"),
    )
    assert verdict.decision == "silence"
    assert "exa 503" in verdict.reason


@pytest.mark.asyncio
async def test_skipped_status_short_circuits(monkeypatch):
    monkeypatch.setattr(
        judge_mod,
        "call_structured",
        lambda **kw: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    verdict = await judge_mod.judge_result(
        context=_ctx(),
        result=_result(status="skipped", skipped_reason="no exa api key"),
    )
    assert verdict.decision == "silence"


# ---------------------------------------------------------------------------
# happy paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_decision_returns_draft(monkeypatch):
    _patch(
        monkeypatch,
        _Out(decision="send", draft="poke v2 shipped today, mic array got the upgrade you flagged"),
    )
    verdict = await judge_mod.judge_result(context=_ctx(), result=_result())
    assert verdict.decision == "send"
    assert verdict.draft.startswith("poke v2 shipped")
    assert verdict.reason == ""


@pytest.mark.asyncio
async def test_silence_decision_carries_reason(monkeypatch):
    _patch(monkeypatch, _Out(decision="silence", reason="the article is from 2024, stale."))
    verdict = await judge_mod.judge_result(context=_ctx(), result=_result())
    assert verdict.decision == "silence"
    assert "stale" in verdict.reason


# ---------------------------------------------------------------------------
# defensive paths — anything weird collapses to silence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_with_empty_draft_falls_to_silence(monkeypatch):
    _patch(monkeypatch, _Out(decision="send", draft="   "))
    verdict = await judge_mod.judge_result(context=_ctx(), result=_result())
    assert verdict.decision == "silence"
    assert "draft was empty" in verdict.reason


@pytest.mark.asyncio
async def test_unknown_decision_falls_to_silence(monkeypatch):
    _patch(monkeypatch, _Out(decision="abstain"))
    verdict = await judge_mod.judge_result(context=_ctx(), result=_result())
    assert verdict.decision == "silence"
    assert "unknown decision" in verdict.reason


@pytest.mark.asyncio
async def test_judge_unavailable_falls_to_silence(monkeypatch):
    async def boom(**kw: Any) -> Any:
        raise RuntimeError("haiku down")

    monkeypatch.setattr(judge_mod, "call_structured", boom)
    verdict = await judge_mod.judge_result(context=_ctx(), result=_result())
    assert verdict.decision == "silence"
    assert "judge unavailable" in verdict.reason


@pytest.mark.asyncio
async def test_none_response_falls_to_silence(monkeypatch):
    _patch(monkeypatch, None)
    verdict = await judge_mod.judge_result(context=_ctx(), result=_result())
    assert verdict.decision == "silence"


# ---------------------------------------------------------------------------
# truncation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_draft_truncated_at_max_chars(monkeypatch):
    _patch(monkeypatch, _Out(decision="send", draft="x" * 5000))
    verdict = await judge_mod.judge_result(context=_ctx(), result=_result())
    assert verdict.decision == "send"
    assert len(verdict.draft) == 600


# ---------------------------------------------------------------------------
# batch helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_judge_results_preserves_order_and_calls_once_per_result(monkeypatch):
    n_calls = {"v": 0}

    async def fake(**kwargs: Any) -> Any:
        n_calls["v"] += 1
        return _Out(decision="send", draft=f"draft {n_calls['v']}")

    monkeypatch.setattr(judge_mod, "call_structured", fake)
    results = [_result(), _result(), _result()]
    verdicts = await judge_mod.judge_results(context=_ctx(), results=results)
    assert [v.draft for _, v in verdicts] == ["draft 1", "draft 2", "draft 3"]
    assert n_calls["v"] == 3


# ---------------------------------------------------------------------------
# payload summarizer (pure)
# ---------------------------------------------------------------------------


def test_summarize_payload_handles_search_results():
    summary = judge_mod._summarize_payload(_result())
    assert "Poke ships v2" in summary
    assert "techcrunch.com/poke-v2" in summary
    assert "2026-04-25" in summary


def test_summarize_payload_handles_resource_id():
    res = ProactiveResult(
        move=_move(),
        status="ok",
        payload={"id": "ws_42", "status": "running"},
    )
    summary = judge_mod._summarize_payload(res)
    assert "ws_42" in summary


def test_summarize_payload_handles_none():
    res = ProactiveResult(move=_move(), status="ok", payload=None)
    summary = judge_mod._summarize_payload(res)
    assert summary == "(no payload)"


# ---------------------------------------------------------------------------
# surprise check (Task 12)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_judge_silences_when_finding_could_be_inferred_from_profile(
    monkeypatch,
):
    """When the result is something the user could have predicted from their
    profile alone (no surprise), judge silences."""
    from backend.web.proactive import judge as j
    from backend.web.proactive.types import (
        ProactiveContext,
        ProactiveMove,
        ProactiveResult,
    )

    async def fake_call_structured(**kw):
        from backend.web.proactive.judge import _JudgeOut
        return _JudgeOut(
            decision="silence",
            reason="result is something user already infers from profile",
        )

    monkeypatch.setattr(j, "call_structured", fake_call_structured)

    move = ProactiveMove(
        rationale="r",
        tool="search",
        query="q",
        dedup_key="dk",
    )
    result = ProactiveResult(
        move=move,
        status="ok",
        payload={"results": [{"url": "https://x", "title": "obvious"}]},
    )
    verdict = await j.judge_result(
        context=ProactiveContext(user_id="u"),
        result=result,
    )
    assert verdict.decision == "silence"
    assert "infer" in verdict.reason.lower()
