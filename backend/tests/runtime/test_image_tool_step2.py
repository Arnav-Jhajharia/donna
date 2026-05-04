"""Step 2 tests: delivery pipe widened to accept media_id.

- ImageMessage constructs cleanly for url-only OR media_id-only; rejects both/neither.
- WhatsAppChannel._render emits {"id": ...} when media_id is set, {"link": ...} otherwise.
- tool_logic._build_outbound routes correctly into ImageMessage from send_burst items.
- No behavior change for existing url-based callers.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from delivery.messages import ImageMessage


class TestImageMessageConstruction:
    def test_url_only_ok(self) -> None:
        msg = ImageMessage(url="https://cdn.example/abc.png", caption="eleven days")
        assert msg.url == "https://cdn.example/abc.png"
        assert msg.media_id is None

    def test_media_id_only_ok(self) -> None:
        msg = ImageMessage(media_id="wa_123abc", caption="eleven days")
        assert msg.media_id == "wa_123abc"
        assert msg.url == ""

    def test_neither_raises(self) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            ImageMessage()

    def test_both_raises(self) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            ImageMessage(url="https://x", media_id="y")

    def test_empty_url_rejected(self) -> None:
        with pytest.raises(ValueError):
            ImageMessage(url="")


@pytest.fixture
def wa_channel():
    """Construct a WhatsAppChannel without requiring real env vars."""
    env = {
        "WHATSAPP_PHONE_NUMBER_ID": "test_phone_id",
        "WHATSAPP_TOKEN": "test_token",
    }
    with patch.dict(os.environ, env, clear=False):
        from delivery.whatsapp import WhatsAppChannel
        return WhatsAppChannel()


class TestRenderBranchesOnMediaId:
    def test_render_url_form(self, wa_channel) -> None:
        msg = ImageMessage(url="https://cdn.example/a.png", caption="hi")
        payload = wa_channel._render("+15551234567", msg)
        assert payload["type"] == "image"
        assert payload["image"]["link"] == "https://cdn.example/a.png"
        assert payload["image"]["caption"] == "hi"
        assert "id" not in payload["image"]

    def test_render_media_id_form(self, wa_channel) -> None:
        msg = ImageMessage(media_id="wa_xyz", caption="eleven days")
        payload = wa_channel._render("+15551234567", msg)
        assert payload["type"] == "image"
        assert payload["image"]["id"] == "wa_xyz"
        assert payload["image"]["caption"] == "eleven days"
        assert "link" not in payload["image"]

    def test_render_media_id_no_caption(self, wa_channel) -> None:
        msg = ImageMessage(media_id="wa_xyz")
        payload = wa_channel._render("+15551234567", msg)
        assert payload["image"]["id"] == "wa_xyz"
        assert "caption" not in payload["image"]


class TestBuildOutboundRoutesImageItems:
    def test_url_item_produces_url_image_message(self) -> None:
        from donna_runtime.tool_logic import _build_outbound
        msg = _build_outbound({
            "type": "image",
            "url": "https://cdn.example/a.png",
            "caption": "done.",
        })
        assert isinstance(msg, ImageMessage)
        assert msg.url == "https://cdn.example/a.png"
        assert msg.media_id is None
        assert msg.caption == "done."

    def test_media_id_item_produces_media_id_image_message(self) -> None:
        from donna_runtime.tool_logic import _build_outbound
        msg = _build_outbound({
            "type": "image",
            "media_id": "wa_xyz",
            "caption": "eleven days. holding.",
        })
        assert isinstance(msg, ImageMessage)
        assert msg.media_id == "wa_xyz"
        assert msg.url == ""
        assert msg.caption == "eleven days. holding."

    def test_empty_image_item_returns_none(self) -> None:
        from donna_runtime.tool_logic import _build_outbound
        assert _build_outbound({"type": "image"}) is None

    def test_media_id_takes_precedence_when_both_sent(self) -> None:
        """Defensive: if Donna somehow sends both, media_id wins (matches _render)."""
        from donna_runtime.tool_logic import _build_outbound
        msg = _build_outbound({
            "type": "image",
            "url": "https://cdn.example/a.png",
            "media_id": "wa_xyz",
            "caption": "x",
        })
        assert isinstance(msg, ImageMessage)
        assert msg.media_id == "wa_xyz"
        assert msg.url == ""


class TestSendBurstSchemaAcceptsBoth:
    """Schema-level check: oneOf on url/media_id is actually present."""
    def test_send_burst_image_schema_has_oneof(self) -> None:
        from donna_runtime.tools import SEND_BURST_INPUT_SCHEMA
        items = SEND_BURST_INPUT_SCHEMA["properties"]["messages"]["items"]["oneOf"]
        image_variant = next(
            v for v in items
            if v["properties"].get("type", {}).get("const") == "image"
        )
        assert "oneOf" in image_variant
        required_keys = {tuple(entry["required"]) for entry in image_variant["oneOf"]}
        assert required_keys == {("url",), ("media_id",)}
