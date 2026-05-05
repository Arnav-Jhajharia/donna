"""Step 9 integration test: image tool end-to-end through hooks + DB + render.

Exercises the full chain with mocked external dependencies (fal.ai, Meta /media,
WhatsAppChannel) but real code for everything in-process:

  PreToolUse → image.handler → _compose_image_prompt (mocked) →
    generate_and_upload (real) → _fal_subscribe / _download_bytes (mocked) →
    WhatsAppChannel.upload_media (mocked) → PostToolUse →
    image_caps.record → send_burst item → _build_outbound → _render

Uses in-memory aiosqlite so image_tool_events rows are real, not stubbed.

Covers:
  (a) happy path: pre-hook allows, tool returns media_id text, post-hook
      writes `sent` row + emits image.generated
  (b) outbound rendering: send_burst image item with media_id produces the
      WhatsApp payload shape `{"image": {"id": <media_id>, "caption": ...}}`
  (c) cooldown: second invocation within 6h → pre-hook denies with the
      image_caps reason string + writes `denied_cooldown` row
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles


@compiles(JSONB, "sqlite")
def _sqlite_jsonb(type_, compiler, **kw):
    return "JSON"


from db.models import Base, ImageToolEvent, User  # noqa: E402
from delivery.whatsapp import WhatsAppChannel as _RealWhatsAppChannel  # noqa: E402
from donna_runtime import tools as runtime_tools  # noqa: E402
from donna_runtime.hooks import (  # noqa: E402
    post_tool_hook,
    pre_tool_hook,
    trace_hook_context,
)
from donna_runtime.tool_logic import _build_outbound  # noqa: E402
from donna_runtime.tracing import TurnTrace  # noqa: E402


TOOL_NAME = "mcp__donna__image"
USER_ID = "u_step9"
WA_MEDIA_ID = "wa_media_ok_123"
FAL_URL = "https://cdn.test/generated.jpg"
FAL_BYTES = b"\x89PNG\r\n\x1a\nfake"


@pytest_asyncio.fixture
async def engine_and_session(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as s:
        s.add(User(id=USER_ID, phone="+15550009999"))
        await s.commit()

    from backend.db import session as backend_session_mod
    from db import session as db_session_mod

    monkeypatch.setattr(backend_session_mod, "async_session", maker)
    monkeypatch.setattr(db_session_mod, "async_session", maker)

    try:
        yield engine, maker
    finally:
        await engine.dispose()


@pytest.fixture
def patched_pipeline():
    """Patch fal + WhatsAppChannel + compose_image_prompt. Let
    generate_and_upload run for real so the whole client code path is covered.
    """
    fal_payload = {
        "images": [{"url": FAL_URL, "content_type": "image/jpeg"}],
        "request_id": "req_abc",
    }
    wa_stub = MagicMock()
    wa_stub.upload_media = AsyncMock(return_value=WA_MEDIA_ID)

    with patch(
        "donna_runtime.image_client._fal_subscribe",
        new=AsyncMock(return_value=fal_payload),
    ), patch(
        "donna_runtime.image_client._download_bytes",
        new=AsyncMock(return_value=FAL_BYTES),
    ), patch(
        "delivery.whatsapp.WhatsAppChannel",
        return_value=wa_stub,
    ), patch(
        "donna_runtime.tools.media.compose_image_prompt",
        new=AsyncMock(
            return_value=(
                "warm hand-drawn illustration, gentle muted palette, soft edges. "
                "a shelf of medicine bottles, holding."
            )
        ),
    ):
        yield wa_stub


async def _invoke_chain(
    args: dict,
) -> tuple[dict, str, dict]:
    """Run pre-hook → tool → post-hook within trace_hook_context. Returns
    (pre_result, tool_text, tool_response_payload)."""
    pre_payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": TOOL_NAME,
        "tool_input": args,
        "tool_use_id": "tu_1",
    }
    pre_result = await pre_tool_hook(pre_payload, "tu_1", None)
    if pre_result.get("hookSpecificOutput", {}).get("permissionDecision") == "deny":
        return pre_result, "", {}

    tool_response = await runtime_tools.image.handler(args)
    tool_text = tool_response["content"][0]["text"]

    post_payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": TOOL_NAME,
        "tool_input": args,
        "tool_response": tool_response,
        "tool_use_id": "tu_1",
    }
    await post_tool_hook(post_payload, "tu_1", None)
    return pre_result, tool_text, tool_response


@pytest.mark.asyncio
async def test_happy_path_writes_sent_row_and_returns_media_id(
    engine_and_session, patched_pipeline
) -> None:
    _engine, maker = engine_and_session
    wa_stub = patched_pipeline

    args = {"intent": "the shelf", "caption": "eleven days. holding."}

    with patch("donna_runtime.hooks.emit") as emit_patch:
        with trace_hook_context(TurnTrace(user_message="show me"), user_id=USER_ID):
            pre_result, tool_text, tool_response = await _invoke_chain(args)

    assert pre_result == {}
    assert f"image ready: {WA_MEDIA_ID}" in tool_text
    assert f"media_id={WA_MEDIA_ID}" in tool_text

    wa_stub.upload_media.assert_awaited_once()
    ((upload_bytes,), upload_kwargs) = wa_stub.upload_media.call_args
    assert upload_bytes == FAL_BYTES
    assert upload_kwargs.get("mime_type") == "image/jpeg"

    async with maker() as s:
        rows = (
            await s.execute(
                select(ImageToolEvent).where(ImageToolEvent.user_id == USER_ID)
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "sent"
    assert isinstance(rows[0].prompt_hash, str) and len(rows[0].prompt_hash) == 64

    events = [c.args[0] for c in emit_patch.call_args_list]
    assert "image.generated" in events
    img_event_kwargs = next(
        c.kwargs for c in emit_patch.call_args_list
        if c.args and c.args[0] == "image.generated"
    )
    assert img_event_kwargs["status"] == "sent"
    assert img_event_kwargs["prompt_hash"] == rows[0].prompt_hash


@pytest.mark.asyncio
async def test_send_burst_item_renders_media_id_payload(
    engine_and_session, patched_pipeline
) -> None:
    """After the tool returns a media_id, Donna threads it into send_burst.
    The outbound payload rendered for Meta must carry {"image": {"id": ...}}."""
    args = {"intent": "the shelf", "caption": "holding."}
    with trace_hook_context(TurnTrace(user_message="show me"), user_id=USER_ID):
        await _invoke_chain(args)

    item = {"type": "image", "media_id": WA_MEDIA_ID, "caption": "holding."}
    message = _build_outbound(item)
    assert message is not None
    assert message.media_id == WA_MEDIA_ID
    assert message.caption == "holding."

    wa = object.__new__(_RealWhatsAppChannel)
    payload = wa._render("+15550009999", message)

    assert payload["type"] == "image"
    assert payload["image"] == {"id": WA_MEDIA_ID, "caption": "holding."}


@pytest.mark.asyncio
async def test_second_call_within_cooldown_is_denied_and_recorded(
    engine_and_session, patched_pipeline
) -> None:
    _engine, maker = engine_and_session

    args = {"intent": "the shelf", "caption": "holding."}

    with trace_hook_context(TurnTrace(user_message="show me"), user_id=USER_ID):
        first_pre, first_text, _ = await _invoke_chain(args)
    assert first_pre == {}
    assert f"image ready: {WA_MEDIA_ID}" in first_text

    with patch("donna_runtime.observability.emit") as emit_patch:
        with trace_hook_context(TurnTrace(user_message="show me again"), user_id=USER_ID):
            second_pre, second_text, _ = await _invoke_chain(args)

    hook_out = second_pre.get("hookSpecificOutput") or {}
    assert hook_out.get("permissionDecision") == "deny"
    reason = hook_out.get("permissionDecisionReason", "")
    assert "image cap hit" in reason
    assert "no image this turn" in reason
    assert second_text == ""

    async with maker() as s:
        rows = (
            await s.execute(
                select(ImageToolEvent)
                .where(ImageToolEvent.user_id == USER_ID)
                .order_by(ImageToolEvent.created_at)
            )
        ).scalars().all()
    statuses = [r.status for r in rows]
    assert statuses == ["sent", "denied_cooldown"]

    events = [c.args[0] for c in emit_patch.call_args_list]
    assert "hook.deny" in events
