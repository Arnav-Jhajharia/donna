"""Step 1 tests: stance block landed in system prompt + image @tool stub exists.

At this step the tool handler raises NotImplementedError on call, and `image`
is intentionally NOT in DONNA_TOOLS. Later steps wire it in.
"""
from __future__ import annotations

import asyncio

import pytest

from donna_runtime.prompt import STAGE_0_5_PROMPT, STAGE_0_PROMPT
from donna_runtime import tools as runtime_tools


class TestStanceBlockLanded:
    def test_stage_0_5_prompt_has_whatsapp_interface_section(self) -> None:
        assert "# WHATSAPP IS THE INTERFACE" in STAGE_0_5_PROMPT

    def test_stage_0_prompt_has_whatsapp_interface_section(self) -> None:
        assert "# WHATSAPP IS THE INTERFACE" in STAGE_0_PROMPT

    def test_stance_block_appears_before_tools_section(self) -> None:
        p = STAGE_0_5_PROMPT
        assert p.index("# WHATSAPP IS THE INTERFACE") < p.index("# TOOLS")

    def test_stance_carries_canonical_examples(self) -> None:
        p = STAGE_0_5_PROMPT
        assert "meds eleven days" in p
        assert "show me" in p
        assert "paint the picture" in p

    def test_stance_names_default_to_text(self) -> None:
        assert "Everything else is text" in STAGE_0_5_PROMPT

    def test_stance_block_is_stance_not_mechanics(self) -> None:
        """Sanity: stance block must not leak tool-description mechanics."""
        p = STAGE_0_5_PROMPT
        stance_start = p.index("# WHATSAPP IS THE INTERFACE")
        stance_end = p.index("# TOOLS", stance_start)
        stance = p[stance_start:stance_end]
        assert "cooldown" not in stance.lower()
        assert "media_id" not in stance.lower()
        assert "intent=" not in stance.lower()
        assert "caption=" not in stance.lower()


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
