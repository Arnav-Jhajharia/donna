"""Step 1 tests: stance block landed in system prompt + image @tool stub exists.

At this step the tool handler raises NotImplementedError on call, and `image`
is intentionally NOT in DONNA_TOOLS. Later steps wire it in.
"""
from __future__ import annotations

import asyncio

import pytest

from donna_runtime.prompt import STAGE_0_5_PROMPT, STAGE_0_PROMPT
from donna_runtime import tools as runtime_tools


class TestPromptStructureV3:
    """Fix 4 — distilled prompt around the four non-negotiables.

    The old "WHATSAPP IS THE INTERFACE" stance block (with worked image
    examples like "meds eleven days") was removed as part of the
    compression. Image guidance now lives in WHAT YOU CAN DO and the
    image tool's own description. These tests assert the new structure.
    """

    def test_prompt_has_identity_and_four_non_negotiables(self) -> None:
        p = STAGE_0_5_PROMPT
        assert "# WHO YOU ARE" in p
        assert "stay on top of their life" in p
        assert "handle things" in p
        assert "know their situation" in p
        assert "doing your best" in p

    def test_prompt_has_read_to_act_block(self) -> None:
        p = STAGE_0_5_PROMPT
        assert "# READ → ACT" in p
        assert "Recall on disagreement" in p
        assert "Attend silently" in p
        assert "Speak what you did" in p

    def test_prompt_has_whatsapp_shape_block(self) -> None:
        """Widget catalog renamed from 'WHATSAPP IS THE INTERFACE' to
        'WHATSAPP SHAPE'. Still carries the widget rules."""
        p = STAGE_0_5_PROMPT
        assert "# WHATSAPP SHAPE" in p
        assert "voice_response" in p
        assert "cta_url" in p

    def test_prompt_size_under_budget(self) -> None:
        """Compression target: _DONNA_CORE under 13000 chars (down from
        ~19,862 in the previous version, ~35% reduction). Most of the
        floor is the INTEGRATIONS block (precise composio parsing +
        connect-with-intent rule) and the BURST SHAPE block (necessary
        for multi-bubble rhythm)."""
        assert len(STAGE_0_5_PROMPT) < 13000, (
            f"prompt grew past budget ({len(STAGE_0_5_PROMPT)} chars)"
        )

    def test_stage_aliases_are_identical(self) -> None:
        """STAGE_0_PROMPT and STAGE_0_5_PROMPT now alias the same content
        (Fix 4 — Stage 0 / no-memory-tools path was dead in production)."""
        assert STAGE_0_PROMPT == STAGE_0_5_PROMPT


class TestImageToolStub:
    def test_image_tool_is_exposed_on_module(self) -> None:
        assert hasattr(runtime_tools, "image")

    def test_image_tool_is_registered_after_step_7(self) -> None:
        names = {t.name for t in runtime_tools.DONNA_TOOLS}
        assert "image" in names

    def test_image_tool_schema_requires_intent_and_caption_only(self) -> None:
        schema = runtime_tools.image.input_schema
        assert schema["required"] == ["intent", "caption"]
        assert set(schema["properties"].keys()) == {"intent", "caption"}
        assert "style" not in schema["properties"]

    def test_image_tool_description_covers_mechanics(self) -> None:
        desc = runtime_tools.image.description
        assert "intent" in desc
        assert "caption" in desc
        assert "send_burst" in desc
        assert "media_id" in desc
        assert "cooldown" in desc.lower()
        assert "one image per turn" in desc.lower()

    def test_image_tool_description_lists_hard_negatives(self) -> None:
        desc = runtime_tools.image.description
        assert "photorealism" in desc.lower() or "photorealistic" in desc.lower()
        assert "diagrams" in desc.lower()

    def test_image_tool_description_does_not_duplicate_stance(self) -> None:
        """Tool description should carry mechanics only. Stance examples live in
        the system prompt. Keeping them separate is the whole point."""
        desc = runtime_tools.image.description.lower()
        assert "show me" not in desc
        assert "eleven days" not in desc
        assert "paint the picture" not in desc

    def test_image_tool_handler_is_callable(self) -> None:
        # After step 7 the handler is real; the missing-user_id branch is the
        # cheapest path to exercise without mocking. Full behavior is covered
        # in tests/test_image_tool_step7.py.
        async def run() -> str:
            result = await runtime_tools.image.handler(
                {"intent": "x", "caption": "y"}
            )
            return result["content"][0]["text"]

        text = asyncio.run(run())
        assert "image unavailable" in text
