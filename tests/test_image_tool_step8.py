"""Step 8 tests: PreToolUse cap-check + PostToolUse record/emit for `image`.

Directly invokes `pre_tool_hook` / `post_tool_hook` with SDK-shaped payloads,
under a `trace_hook_context` so ContextVars (user_id, trace, image prompt
hash) are populated the same way the runner would set them.

Patches both `backend.memory.tools.image_caps.check` and `.record` — no DB.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from backend.memory.tools.image_caps import CapDecision
from donna_runtime import hooks as hooks_module
from donna_runtime.hooks import (
    _classify_image_outcome,
    _extract_tool_response_text,
    _IMAGE_PROMPT_HASH_KEY,
    post_tool_hook,
    pre_tool_hook,
    set_image_prompt_hash,
    trace_hook_context,
)
from donna_runtime.tracing import TurnTrace


TOOL_NAME = "mcp__donna__image"
USER_ID = "user_abc"


def _trace_for_user() -> TurnTrace:
    return TurnTrace(user_message="make me an image")


def _pre_payload(args: dict | None = None) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": TOOL_NAME,
        "tool_input": args or {"intent": "x", "caption": "y"},
        "tool_use_id": "tu_1",
    }


def _post_payload(text: str, tool_name: str = TOOL_NAME) -> dict:
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": tool_name,
        "tool_input": {"intent": "x", "caption": "y"},
        "tool_response": {"content": [{"type": "text", "text": text}]},
        "tool_use_id": "tu_2",
    }


async def _run_pre(check_mock: AsyncMock, record_mock: AsyncMock) -> dict:
    with patch(
        "backend.memory.tools.image_caps.check", new=check_mock
    ), patch(
        "backend.memory.tools.image_caps.record", new=record_mock
    ):
        with trace_hook_context(_trace_for_user(), user_id=USER_ID):
            return await pre_tool_hook(_pre_payload(), "tu_1", None)


async def _run_post(
    text: str,
    record_mock: AsyncMock,
    *,
    prompt_hash: str | None = "ph_1",
    emit_mock: AsyncMock | None = None,
    tool_name: str = TOOL_NAME,
) -> dict:
    with patch(
        "backend.memory.tools.image_caps.record", new=record_mock
    ), patch(
        "donna_runtime.hooks.emit"
    ) as emit_patch:
        with trace_hook_context(_trace_for_user(), user_id=USER_ID):
            if prompt_hash is not None:
                set_image_prompt_hash(prompt_hash)
            result = await post_tool_hook(_post_payload(text, tool_name), "tu_2", None)
        if emit_mock is not None:
            emit_mock.call_args_list = emit_patch.call_args_list
        return result, emit_patch


class TestExtractText:
    def test_dict_content_flattened(self) -> None:
        assert _extract_tool_response_text(
            {"content": [{"type": "text", "text": "hello"}]}
        ) == "hello"

    def test_list_of_blocks(self) -> None:
        assert (
            _extract_tool_response_text(
                [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]
            )
            == "a b"
        )

    def test_plain_string(self) -> None:
        assert _extract_tool_response_text("hi") == "hi"

    def test_none(self) -> None:
        assert _extract_tool_response_text(None) == ""


class TestClassify:
    def test_sent(self) -> None:
        assert (
            _classify_image_outcome(
                "image ready: wa_1. use it in send_burst ..."
            )
            == "sent"
        )

    def test_safety(self) -> None:
        assert (
            _classify_image_outcome(
                "image rejected by safety filter. rewrite intent..."
            )
            == "failed_safety"
        )

    def test_provider_timeout(self) -> None:
        assert (
            _classify_image_outcome(
                "image unavailable: provider timeout. skip the image..."
            )
            == "failed_provider"
        )

    def test_upload_failed(self) -> None:
        assert (
            _classify_image_outcome(
                "image unavailable: whatsapp media upload failed."
            )
            == "failed_provider"
        )

    def test_unexpected(self) -> None:
        assert (
            _classify_image_outcome(
                "image unavailable: unexpected failure. go text."
            )
            == "failed_provider"
        )

    def test_intent_validation_not_recorded(self) -> None:
        assert (
            _classify_image_outcome(
                "image unavailable: intent and caption are both required. go text."
            )
            is None
        )

    def test_intent_invalid_not_recorded(self) -> None:
        assert (
            _classify_image_outcome("image unavailable: intent invalid. go text.")
            is None
        )

    def test_runtime_user_scope_not_recorded(self) -> None:
        assert (
            _classify_image_outcome(
                "image unavailable: runtime user scope missing. go text."
            )
            is None
        )

    def test_unknown_text(self) -> None:
        assert _classify_image_outcome("something else entirely") is None

    def test_empty(self) -> None:
        assert _classify_image_outcome("") is None


class TestPreHookAllow:
    def test_allow_returns_empty_payload(self) -> None:
        check_mock = AsyncMock(return_value=CapDecision.allow())
        record_mock = AsyncMock()
        result = asyncio.run(_run_pre(check_mock, record_mock))
        assert result == {}
        check_mock.assert_awaited_once_with(USER_ID)
        record_mock.assert_not_called()


class TestPreHookDeny:
    def test_deny_cooldown_returns_permission_deny(self) -> None:
        decision = CapDecision.deny_cooldown(4.0)
        check_mock = AsyncMock(return_value=decision)
        record_mock = AsyncMock()
        result = asyncio.run(_run_pre(check_mock, record_mock))
        output = result.get("hookSpecificOutput") or {}
        assert output.get("permissionDecision") == "deny"
        assert "image cap hit" in output.get("permissionDecisionReason", "")
        record_mock.assert_awaited_once_with(
            USER_ID, "denied_cooldown", prompt_hash=None
        )

    def test_deny_cap_records_denied_cap(self) -> None:
        decision = CapDecision.deny_cap(3.0)
        check_mock = AsyncMock(return_value=decision)
        record_mock = AsyncMock()
        result = asyncio.run(_run_pre(check_mock, record_mock))
        output = result.get("hookSpecificOutput") or {}
        assert output.get("permissionDecision") == "deny"
        record_mock.assert_awaited_once_with(
            USER_ID, "denied_cap", prompt_hash=None
        )


class TestPreHookDegradation:
    def test_missing_user_id_allows(self) -> None:
        record_mock = AsyncMock()
        check_mock = AsyncMock(return_value=CapDecision.allow())
        async def body():
            with patch(
                "backend.memory.tools.image_caps.check", new=check_mock
            ), patch(
                "backend.memory.tools.image_caps.record", new=record_mock
            ):
                with trace_hook_context(_trace_for_user(), user_id=None):
                    return await pre_tool_hook(_pre_payload(), "tu_1", None)
        result = asyncio.run(body())
        assert result == {}
        check_mock.assert_not_called()

    def test_check_raises_allows_fail_open(self) -> None:
        check_mock = AsyncMock(side_effect=RuntimeError("db down"))
        record_mock = AsyncMock()
        result = asyncio.run(_run_pre(check_mock, record_mock))
        assert result == {}
        record_mock.assert_not_called()


class TestPostHookRecords:
    def test_sent_records_sent_and_emits(self) -> None:
        record_mock = AsyncMock()
        _, emit_patch = asyncio.run(
            _run_post("image ready: m_1. use it in send_burst...", record_mock)
        )
        record_mock.assert_awaited_once_with(USER_ID, "sent", "ph_1")
        events = [c.args[0] for c in emit_patch.call_args_list]
        assert "image.generated" in events
        kwargs = next(
            c.kwargs for c in emit_patch.call_args_list if c.args and c.args[0] == "image.generated"
        )
        assert kwargs["status"] == "sent"
        assert kwargs["prompt_hash"] == "ph_1"

    def test_safety_records_failed_safety(self) -> None:
        record_mock = AsyncMock()
        asyncio.run(
            _run_post(
                "image rejected by safety filter. rewrite intent without...",
                record_mock,
            )
        )
        record_mock.assert_awaited_once_with(USER_ID, "failed_safety", "ph_1")

    def test_provider_records_failed_provider(self) -> None:
        record_mock = AsyncMock()
        asyncio.run(
            _run_post(
                "image unavailable: provider timeout. skip the image, reply with text.",
                record_mock,
            )
        )
        record_mock.assert_awaited_once_with(USER_ID, "failed_provider", "ph_1")

    def test_caller_bug_not_recorded(self) -> None:
        record_mock = AsyncMock()
        asyncio.run(
            _run_post(
                "image unavailable: intent and caption are both required. go text.",
                record_mock,
                prompt_hash=None,
            )
        )
        record_mock.assert_not_called()

    def test_non_image_tool_skipped(self) -> None:
        record_mock = AsyncMock()
        async def body():
            with patch(
                "backend.memory.tools.image_caps.record", new=record_mock
            ):
                with trace_hook_context(_trace_for_user(), user_id=USER_ID):
                    return await post_tool_hook(
                        _post_payload("some text", tool_name="mcp__donna__send_burst"),
                        "tu_2",
                        None,
                    )
        asyncio.run(body())
        record_mock.assert_not_called()


class TestPromptHashStash:
    def test_stored_on_trace_metadata(self) -> None:
        trace = _trace_for_user()
        with trace_hook_context(trace, user_id=USER_ID):
            set_image_prompt_hash("abc")
            assert trace.prompt_metadata[_IMAGE_PROMPT_HASH_KEY] == "abc"

    def test_pop_clears_value(self) -> None:
        trace = _trace_for_user()
        with trace_hook_context(trace, user_id=USER_ID):
            set_image_prompt_hash("abc")
            popped = hooks_module._pop_image_prompt_hash()
            assert popped == "abc"
            assert _IMAGE_PROMPT_HASH_KEY not in trace.prompt_metadata

    def test_set_without_trace_is_no_op(self) -> None:
        # No active trace — helper should short-circuit safely.
        set_image_prompt_hash("nope")
        assert hooks_module._pop_image_prompt_hash() is None
