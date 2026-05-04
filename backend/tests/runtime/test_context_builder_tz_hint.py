"""Regression: the timezone-check hint must point at a tool the model has.

Post verb-refactor, `set_timezone` is no longer in ALLOWED_TOOLS — the verb
`remember(kind='timezone', ...)` owns the write path. The hint must steer
the model at the verb, not the bare mechanism tool.
"""
from __future__ import annotations

import pytest

from donna_runtime.context_builder import render_turn_context


@pytest.mark.asyncio
async def test_unconfirmed_tz_hint_points_at_remember():
    state = {
        "user_id": "u-test",
        "_user_name": "Arnav",
        "_user_timezone": "Asia/Singapore",
        "_tz_done": False,
        "_tz_source": "phone_prefix",
        "_tz_guess_prefix": "+65",
        "_is_first_message": False,
    }
    rendered = await render_turn_context(state)
    # The block must steer the model at the current verb surface.
    assert "remember" in rendered, (
        f"tz hint should name the `remember` verb; got:\n{rendered}"
    )
    assert "kind='timezone'" in rendered or "kind=timezone" in rendered or "kind=\"timezone\"" in rendered, (
        f"tz hint should include remember kind=timezone; got:\n{rendered}"
    )
    # It must NOT point at a tool that no longer exists in ALLOWED_TOOLS.
    assert "set_timezone(" not in rendered, (
        "tz hint still references the old mechanism tool set_timezone; "
        "the model cannot call it and will just say 'locked in' without writing"
    )


@pytest.mark.asyncio
async def test_confirmed_tz_skips_hint():
    state = {
        "user_id": "u-test",
        "_user_name": "Arnav",
        "_user_timezone": "Asia/Singapore",
        "_tz_done": True,
        "_is_first_message": False,
    }
    rendered = await render_turn_context(state)
    assert "TIMEZONE CHECK" not in rendered
