"""Step 7 tests: `image` tool handler end-to-end with everything mocked.

Covers:
  - registration in DONNA_TOOLS + ALLOWED_TOOLS
  - happy path returns "image ready: <media_id>" text
  - user_id guard (fall-through when scope missing)
  - intent/caption required guard
  - mapping of each typed ImageGenerationError to the spec fall-through string
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from donna_runtime import tools as runtime_tools
from donna_runtime.config import ALLOWED_TOOLS
from donna_runtime.hooks import _CURRENT_USER_ID
from donna_runtime.image_client import (
    ImageProviderError,
    ImageResult,
    ImageSafetyError,
    ImageUploadError,
)


OK_RESULT = ImageResult(
    media_id="wa_media_42",
    fal_request_id="fal_req_abc",
    mime_type="image/jpeg",
    final_prompt="a warm hearth, soft edges",
)


def _run_image(args: dict, user_id: str | None = "user_1") -> str:
    async def body() -> str:
        token = _CURRENT_USER_ID.set(user_id)
        try:
            result = await runtime_tools.image.handler(args)
        finally:
            _CURRENT_USER_ID.reset(token)
        return result["content"][0]["text"]

    return asyncio.run(body())


@pytest.fixture
def patched_generate():
    """Patch compose_image_prompt + generate_and_upload + WhatsAppChannel()."""
    with patch(
        "donna_runtime.tools.compose_image_prompt",
        new=AsyncMock(return_value="composed prompt"),
    ) as compose, patch(
        "donna_runtime.image_client.generate_and_upload",
        new=AsyncMock(return_value=OK_RESULT),
    ) as gen, patch(
        "delivery.whatsapp.WhatsAppChannel",
        return_value=MagicMock(),
    ):
        yield compose, gen


class TestRegistration:
    def test_image_in_donna_tools(self) -> None:
        names = {t.name for t in runtime_tools.DONNA_TOOLS}
        assert "image" in names

    def test_image_in_allowed_tools(self) -> None:
        assert "mcp__donna__image" in ALLOWED_TOOLS

    def test_send_burst_still_terminates_tool_list(self) -> None:
        # Conceptually: image should appear before send_burst so the ordering
        # reads "retrieval → action → image → TERMINATOR". Enforce lightly —
        # just confirm send_burst is the final entry.
        assert runtime_tools.DONNA_TOOLS[-1].name == "send_burst"


class TestGuards:
    def test_missing_user_id_falls_through(self) -> None:
        text = _run_image({"intent": "x", "caption": "y"}, user_id=None)
        assert "runtime user scope missing" in text
        assert "go text" in text

    def test_empty_intent_falls_through(self) -> None:
        text = _run_image({"intent": "  ", "caption": "y"})
        assert "intent and caption are both required" in text

    def test_empty_caption_falls_through(self) -> None:
        text = _run_image({"intent": "x", "caption": ""})
        assert "intent and caption are both required" in text


class TestHappyPath:
    def test_returns_media_id_text(self, patched_generate) -> None:
        text = _run_image({"intent": "a warm hearth", "caption": "holding."})
        assert "image ready: wa_media_42" in text
        assert "media_id=wa_media_42" in text
        assert "caption unchanged" in text

    def test_calls_compose_with_user_id_and_intent(self, patched_generate) -> None:
        compose, _ = patched_generate
        _run_image({"intent": "a warm hearth", "caption": "holding."})
        compose.assert_awaited_once_with("user_1", "a warm hearth")

    def test_calls_generate_and_upload_with_composed_prompt(
        self, patched_generate
    ) -> None:
        _, gen = patched_generate
        _run_image({"intent": "x", "caption": "y"})
        args, _ = gen.call_args
        assert args[0] == "composed prompt"


class TestErrorMapping:
    def _run_with_error(self, exc: Exception) -> str:
        with patch(
            "donna_runtime.tools.compose_image_prompt",
            new=AsyncMock(return_value="prompt"),
        ), patch(
            "donna_runtime.image_client.generate_and_upload",
            new=AsyncMock(side_effect=exc),
        ), patch(
            "delivery.whatsapp.WhatsAppChannel",
            return_value=MagicMock(),
        ):
            return _run_image({"intent": "x", "caption": "y"})

    def test_safety_error_maps_to_safety_text(self) -> None:
        text = self._run_with_error(ImageSafetyError("blocked"))
        assert "rejected by safety filter" in text

    def test_upload_error_maps_to_upload_text(self) -> None:
        text = self._run_with_error(ImageUploadError("meta 413"))
        assert "whatsapp media upload failed" in text

    def test_provider_error_maps_to_provider_text(self) -> None:
        text = self._run_with_error(ImageProviderError("fal down"))
        assert "provider timeout" in text
        assert "skip the image" in text

    def test_unexpected_error_falls_through(self) -> None:
        text = self._run_with_error(RuntimeError("wat"))
        assert "unexpected failure" in text

    def test_compose_value_error_maps_cleanly(self) -> None:
        with patch(
            "donna_runtime.tools.compose_image_prompt",
            new=AsyncMock(side_effect=ValueError("empty")),
        ):
            text = _run_image({"intent": "x", "caption": "y"})
        assert "intent invalid" in text
