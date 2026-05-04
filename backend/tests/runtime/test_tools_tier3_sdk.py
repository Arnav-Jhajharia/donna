"""SDK @tool wrappers around the typed tools_tier3 functions."""
from __future__ import annotations

import pytest

from donna_runtime.tools_tier3_sdk import (
    skip_tool,
    kill_attention_tool,
    reshape_attention_tool,
    send_burst_tool,
    quick_check_tool,
    read_external_tool,
    TIER3_SDK_TOOLS,
)


def test_tier3_sdk_tools_includes_all_six():
    names = {t.name for t in TIER3_SDK_TOOLS}
    assert names == {
        "skip",
        "kill_attention",
        "reshape_attention",
        "send_burst",
        "quick_check",
        "read_external",
    }


@pytest.mark.asyncio
async def test_skip_tool_delegates_to_typed_function():
    result = await skip_tool.handler({"reason": "moment is dead"})
    assert result["content"]
    text = result["content"][0]["text"]
    assert "skip" in text
    assert "moment is dead" in text


@pytest.mark.asyncio
async def test_skip_tool_validation_error_returned_as_error():
    """Empty reason → typed function raises ValueError → wrapper packages
    as SDK error result, not a Python exception."""
    result = await skip_tool.handler({"reason": ""})
    assert result.get("isError") is True


@pytest.mark.asyncio
async def test_send_burst_tool_supports_quadrant_matrix():
    result = await send_burst_tool.handler({
        "messages": [{"type": "text", "body": "hi"}],
        "push": False,
        "surface_at": "morning_brief",
    })
    text = result["content"][0]["text"]
    assert "morning_brief" in text
    assert '"push": false' in text or "'push': False" in text


@pytest.mark.asyncio
async def test_kill_attention_tool_returns_outcome():
    result = await kill_attention_tool.handler({
        "attention_id": "att_1",
        "reason": "user already did the thing",
    })
    assert result["content"]
    text = result["content"][0]["text"]
    assert "kill" in text
    assert "att_1" in text


@pytest.mark.asyncio
async def test_quick_check_tool_validates_question():
    result = await quick_check_tool.handler({"question": "", "max_results": 3})
    assert result.get("isError") is True


@pytest.mark.asyncio
async def test_read_external_tool_validates_source():
    result = await read_external_tool.handler({
        "source": "bogus",
        "ref": "x",
    })
    assert result.get("isError") is True
