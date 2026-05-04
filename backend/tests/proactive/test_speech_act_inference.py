"""Speech-act inference per source/payload."""
from __future__ import annotations

from proactive.sources._inference import infer_speech_act


def test_email_defaults_to_heads_up():
    assert infer_speech_act("email", payload={}, signals={}) == "heads_up"


def test_attention_fire_user_requested_ping_is_dont_forget():
    payload = {"origin": "USER_REQUESTED", "card": "PING"}
    assert infer_speech_act("attention_fire", payload, {}) == "dont_forget"


def test_attention_fire_donna_anticipated_is_now_the_moment():
    payload = {"origin": "DONNA_ANTICIPATED"}
    assert infer_speech_act("attention_fire", payload, {}) == "now_the_moment"


def test_attention_fire_observation_frequency_is_i_noticed():
    payload = {
        "origin": "SHADOW_INFERRED",
        "proposer": "ObservationFrequencyProposer",
    }
    assert infer_speech_act("attention_fire", payload, {}) == "i_noticed"


def test_calendar_is_heads_up():
    assert infer_speech_act("calendar", payload={}, signals={}) == "heads_up"


def test_system_b_web_default_is_thought_youd_want():
    assert (
        infer_speech_act("system_b_web", payload={}, signals={})
        == "thought_youd_want"
    )


def test_system_b_web_upgrades_to_heads_up_when_urgent():
    sa = infer_speech_act(
        "system_b_web",
        payload={"angle": "postmortem"},
        signals={"is_urgent_signal": True},
    )
    assert sa == "heads_up"


def test_pattern_is_thought_youd_want():
    assert infer_speech_act("pattern", payload={}, signals={}) == "thought_youd_want"


def test_attention_offer_is_thought_youd_want():
    assert (
        infer_speech_act("attention_offer", payload={}, signals={})
        == "thought_youd_want"
    )


def test_truly_unknown_source_falls_back_to_default():
    """A source string not in ProactiveSource hits the final fallback."""
    assert (
        infer_speech_act(
            "sms",  # type: ignore[arg-type]
            payload={},
            signals={},
        )
        == "thought_youd_want"
    )
