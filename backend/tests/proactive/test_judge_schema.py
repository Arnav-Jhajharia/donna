"""JudgeResult schema — channel_hint and reclassify_speech_act."""
from __future__ import annotations

from proactive.events import SpeechAct
from proactive.judge import JudgeResult, JudgeOutput


def test_judge_result_default_channel_hint_is_none():
    j = JudgeResult(
        action="ping",
        register="alert",
        draft="luca replied to the term sheet thread",
        tie_in=("luca",),
        needs_tools=False,
        reasoning="ok",
        raw_response="{}",
    )
    assert j.channel_hint is None
    assert j.reclassify_speech_act is None


def test_judge_result_accepts_channel_hint():
    j = JudgeResult(
        action="ping",
        register="alert",
        draft="x",
        tie_in=(),
        needs_tools=False,
        reasoning="",
        raw_response="",
        channel_hint="whatsapp",
    )
    assert j.channel_hint == "whatsapp"


def test_judge_result_accepts_reclassify():
    sa: SpeechAct = "heads_up"
    j = JudgeResult(
        action="ping",
        register=None,
        draft=None,
        tie_in=(),
        needs_tools=False,
        reasoning="",
        raw_response="",
        reclassify_speech_act=sa,
    )
    assert j.reclassify_speech_act == "heads_up"


def test_judge_output_pydantic_accepts_new_fields():
    out = JudgeOutput(
        action="ping",
        register="soft",
        draft="hey",
        tie_in=["x"],
        needs_tools=False,
        reasoning="",
        channel_hint="dashboard",
        reclassify_speech_act="i_noticed",
    )
    assert out.channel_hint == "dashboard"
    assert out.reclassify_speech_act == "i_noticed"


def test_judge_output_pydantic_back_compat_omits_new_fields():
    out = JudgeOutput(
        action="drop",
        register=None,
        draft=None,
        tie_in=[],
        needs_tools=False,
        reasoning="not interesting",
    )
    assert out.channel_hint is None
    assert out.reclassify_speech_act is None
