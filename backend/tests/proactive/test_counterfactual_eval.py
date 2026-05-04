"""Counterfactual eval — pure-function summarizer + report formatting."""
from __future__ import annotations

from types import SimpleNamespace

from scripts.proactive_counterfactual_eval import _summarize


def _row(
    *,
    speech_act="heads_up",
    source="email",
    outcome="input_built",
    legacy_count=1,
    elapsed_ms=5,
    error=None,
):
    return SimpleNamespace(
        speech_act=speech_act,
        source=source,
        counterfactual_fat_contract_outcome=outcome,
        counterfactual_legacy_outbound_count=legacy_count,
        counterfactual_fat_contract_elapsed_ms=elapsed_ms,
        counterfactual_fat_contract_error=error,
    )


def test_summarize_empty_rows_returns_zeros():
    summary = _summarize([])
    assert summary["total"] == 0
    assert summary["input_built"] == 0
    assert summary["input_failed"] == 0
    assert summary["legacy_ships"] == 0
    assert summary["elapsed_ms_p50"] is None
    assert summary["elapsed_ms_p95"] is None
    assert summary["top_errors"] == []


def test_summarize_counts_input_built_and_failed():
    rows = [
        _row(outcome="input_built"),
        _row(outcome="input_built"),
        _row(outcome="input_failed", error="ValueError: stub failure"),
    ]
    summary = _summarize(rows)
    assert summary["total"] == 3
    assert summary["input_built"] == 2
    assert summary["input_failed"] == 1


def test_summarize_per_speech_act_breakdown():
    rows = [
        _row(speech_act="heads_up"),
        _row(speech_act="heads_up"),
        _row(speech_act="i_noticed"),
    ]
    summary = _summarize(rows)
    assert summary["by_speech_act"]["heads_up"]["n"] == 2
    assert summary["by_speech_act"]["i_noticed"]["n"] == 1


def test_summarize_per_source_breakdown():
    rows = [
        _row(source="email"),
        _row(source="system_b_web"),
        _row(source="system_b_web"),
    ]
    summary = _summarize(rows)
    assert summary["by_source"]["email"]["n"] == 1
    assert summary["by_source"]["system_b_web"]["n"] == 2


def test_summarize_elapsed_p50_p95():
    rows = [_row(elapsed_ms=ms) for ms in [1, 5, 10, 20, 100]]
    summary = _summarize(rows)
    # p50 should be in the middle, p95 near the top
    assert summary["elapsed_ms_p50"] is not None
    assert summary["elapsed_ms_p95"] is not None
    assert summary["elapsed_ms_p50"] <= summary["elapsed_ms_p95"]


def test_summarize_top_errors_groups_by_exception_type():
    rows = [
        _row(outcome="input_failed", error="ValueError: missing key"),
        _row(outcome="input_failed", error="ValueError: bad shape"),
        _row(outcome="input_failed", error="KeyError: foo"),
    ]
    summary = _summarize(rows)
    assert dict(summary["top_errors"]) == {"ValueError": 2, "KeyError": 1}


def test_summarize_legacy_ships_counts_only_with_outbound():
    rows = [
        _row(legacy_count=1),
        _row(legacy_count=0),
        _row(legacy_count=2),
    ]
    summary = _summarize(rows)
    assert summary["legacy_ships"] == 2  # only the rows with legacy_count > 0
