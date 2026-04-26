"""Step 6 tests: `_compose_image_prompt` — pure deterministic template.

No DB, no LLM. The async wrapper `compose_image_prompt` is also tested with
`get_user_facts` patched so behavior around the fail-soft branch is covered.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from donna_runtime.config import IMAGE_LOCKED_STYLE
from donna_runtime.tool_logic import (
    _clean_intent,
    _compose_image_prompt,
    _grounding_clause,
    compose_image_prompt,
)


def _fact(value: str) -> dict:
    return {
        "value": value,
        "source": "onboarding_explicit",
        "confidence": "high",
        "updated_at": "2026-01-01",
    }


class TestStyleAndNegatives:
    def test_style_header_always_first(self) -> None:
        out = _compose_image_prompt("x")
        assert out.startswith(IMAGE_LOCKED_STYLE.rstrip("."))

    def test_hard_negatives_always_present(self) -> None:
        out = _compose_image_prompt("anything")
        assert "no embedded text in the image" in out
        assert "no photorealistic faces" in out
        assert "no brand logos" in out

    def test_output_ends_with_period(self) -> None:
        assert _compose_image_prompt("hello").endswith(".")


class TestIntentPassthrough:
    def test_intent_verbatim_when_clean(self) -> None:
        assert "a shelf with eleven bottles" in _compose_image_prompt(
            "a shelf with eleven bottles"
        )

    def test_empty_intent_raises(self) -> None:
        with pytest.raises(ValueError, match="intent is empty"):
            _compose_image_prompt("   ")

    def test_whitespace_collapsed(self) -> None:
        assert "foo bar baz" in _compose_image_prompt("foo   bar\n\n  baz")

    def test_long_intent_truncated(self) -> None:
        long = "a " * 400
        out = _compose_image_prompt(long)
        # grounding empty + style header + hard negatives fit in a short tail;
        # the intent itself cannot blow past ~300 chars + ellipsis.
        assert "…" in out

    def test_clean_intent_helper(self) -> None:
        assert _clean_intent("") == ""
        assert _clean_intent("  a  b  ") == "a b"


class TestGroundingClause:
    def test_empty_when_no_facts(self) -> None:
        assert _grounding_clause({}) == ""

    def test_empty_when_only_preferred_name(self) -> None:
        # name is deliberately excluded — no PII in images
        assert _grounding_clause({"preferred_name": _fact("Anya")}) == ""

    def test_current_city_produces_set_in_clause(self) -> None:
        assert _grounding_clause({"current_city": _fact("delhi")}) == (
            "background: set in delhi"
        )

    def test_home_city_used_when_current_missing(self) -> None:
        assert _grounding_clause({"home_city": _fact("bangalore")}) == (
            "background: set in bangalore"
        )

    def test_current_city_wins_over_home_city(self) -> None:
        out = _grounding_clause(
            {"current_city": _fact("delhi"), "home_city": _fact("bangalore")}
        )
        assert "set in delhi" in out
        assert "bangalore" not in out  # duplicate-value dedupe would also hide it

    def test_up_to_three_slots(self) -> None:
        facts = {
            "current_city": _fact("delhi"),
            "home_city": _fact("bangalore"),
            "life_stage": _fact("early founder"),
            "profession": _fact("engineer"),
        }
        out = _grounding_clause(facts)
        # 3 distinct values at most
        assert out.count(",") == 2

    def test_plain_string_fact_tolerated(self) -> None:
        assert _grounding_clause({"current_city": "delhi"}) == (
            "background: set in delhi"
        )

    def test_long_fact_value_truncated(self) -> None:
        long_city = "x" * 500
        out = _grounding_clause({"current_city": _fact(long_city)})
        assert "…" in out


class TestDeterminism:
    def test_same_inputs_same_output(self) -> None:
        facts = {"current_city": _fact("delhi"), "profession": _fact("founder")}
        assert _compose_image_prompt("the loop closed", facts) == _compose_image_prompt(
            "the loop closed", facts
        )

    def test_no_name_leak_when_facts_unknown(self) -> None:
        out = _compose_image_prompt("a quiet celebration", {})
        assert "background:" not in out

    def test_preferred_name_never_in_output(self) -> None:
        facts = {"preferred_name": _fact("Anya"), "current_city": _fact("delhi")}
        out = _compose_image_prompt("x", facts)
        assert "Anya" not in out
        assert "anya" not in out.lower()


class TestAsyncWrapper:
    def test_compose_with_user_id_pulls_facts(self) -> None:
        fetched = {"current_city": _fact("delhi")}
        with patch(
            "backend.memory.user_facts.api.get_user_facts",
            new=AsyncMock(return_value=fetched),
        ) as mock_fetch:
            out = asyncio.run(compose_image_prompt("user_1", "a warm kitchen"))

        mock_fetch.assert_awaited_once_with("user_1")
        assert "set in delhi" in out
        assert "a warm kitchen" in out

    def test_compose_without_user_id_skips_db(self) -> None:
        with patch(
            "backend.memory.user_facts.api.get_user_facts",
            new=AsyncMock(return_value={}),
        ) as mock_fetch:
            out = asyncio.run(compose_image_prompt(None, "just a scene"))

        mock_fetch.assert_not_called()
        assert "background:" not in out
        assert "just a scene" in out

    def test_compose_fails_soft_when_db_errors(self) -> None:
        with patch(
            "backend.memory.user_facts.api.get_user_facts",
            new=AsyncMock(side_effect=RuntimeError("db down")),
        ):
            out = asyncio.run(compose_image_prompt("user_1", "a quiet moment"))

        # still produces a useful prompt, just without grounding
        assert "a quiet moment" in out
        assert "background:" not in out
        assert "no photorealistic faces" in out
