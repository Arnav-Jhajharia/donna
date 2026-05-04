"""Tests for the Haiku judge client (Phase 4).

Mocks the Anthropic SDK so the test suite never makes a real API call.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts._stress_matrix.haiku_judge import (
    DEFAULT_MODEL,
    HaikuJudge,
    build_judge_from_env,
)


def _fake_response(text: str) -> MagicMock:
    """Build a MagicMock that quacks like an Anthropic Messages response."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


class TestBuildFromEnv:
    def test_returns_none_when_api_key_missing(self) -> None:
        assert build_judge_from_env({}) is None
        assert build_judge_from_env({"ANTHROPIC_API_KEY": "  "}) is None

    def test_constructs_judge_with_default_model(self) -> None:
        judge = build_judge_from_env({"ANTHROPIC_API_KEY": "sk-test"})
        assert judge is not None
        assert judge.api_key == "sk-test"
        assert judge.model == DEFAULT_MODEL

    def test_respects_donna_judge_model_override(self) -> None:
        judge = build_judge_from_env(
            {"ANTHROPIC_API_KEY": "sk-test", "DONNA_JUDGE_MODEL": "claude-haiku-test"}
        )
        assert judge is not None
        assert judge.model == "claude-haiku-test"


class TestHaikuJudgeGrade:
    @pytest.mark.asyncio
    async def test_grade_returns_text_block(self) -> None:
        judge = HaikuJudge(api_key="sk-test")
        fake_response = _fake_response('{"passed": true, "reason": "good"}')

        fake_messages = MagicMock()
        fake_messages.create = AsyncMock(return_value=fake_response)
        fake_client = MagicMock()
        fake_client.messages = fake_messages

        with patch(
            "anthropic.AsyncAnthropic",
            return_value=fake_client,
            create=True,
        ):
            out = await judge.grade("verdict please")

        assert out == '{"passed": true, "reason": "good"}'
        fake_messages.create.assert_awaited_once()
        kwargs = fake_messages.create.await_args.kwargs
        assert kwargs["model"] == DEFAULT_MODEL
        assert kwargs["messages"] == [{"role": "user", "content": "verdict please"}]

    @pytest.mark.asyncio
    async def test_grade_concatenates_multiple_text_blocks(self) -> None:
        judge = HaikuJudge(api_key="sk-test")
        block_a = MagicMock(type="text", text="part one")
        block_b = MagicMock(type="text", text="part two")
        non_text = MagicMock(type="tool_use", text="ignored")
        response = MagicMock(content=[block_a, non_text, block_b])

        fake_messages = MagicMock()
        fake_messages.create = AsyncMock(return_value=response)
        fake_client = MagicMock()
        fake_client.messages = fake_messages

        with patch("anthropic.AsyncAnthropic", return_value=fake_client, create=True):
            out = await judge.grade("p")
        assert out == "part one\npart two"

    @pytest.mark.asyncio
    async def test_grade_raises_on_timeout(self) -> None:
        judge = HaikuJudge(api_key="sk-test", timeout_s=0.01)

        async def slow_create(**_kwargs):
            await asyncio.sleep(1.0)
            return _fake_response("late")

        fake_messages = MagicMock()
        fake_messages.create = slow_create
        fake_client = MagicMock()
        fake_client.messages = fake_messages

        with patch("anthropic.AsyncAnthropic", return_value=fake_client, create=True):
            with pytest.raises(RuntimeError, match="haiku judge timeout"):
                await judge.grade("p")
