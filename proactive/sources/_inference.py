"""Infer ProactiveEvent.speech_act from source + payload + signals.

The mapping is intentionally narrow and explicit. Source adapters call
this when they don't have a more specific reason to set speech_act
themselves.
"""
from __future__ import annotations

from typing import Any

from proactive.events import ProactiveSource, SpeechAct


_DEFAULT: SpeechAct = "thought_youd_want"


def infer_speech_act(
    source: ProactiveSource,
    payload: dict[str, Any],
    signals: dict[str, Any],
) -> SpeechAct:
    """Return the speech_act for an event whose adapter didn't set one.

    Today's mappings:
      email             -> heads_up
      calendar          -> heads_up
      attention_fire    -> based on origin: USER_REQUESTED+PING -> dont_forget,
                           DONNA_ANTICIPATED -> now_the_moment,
                           SHADOW_INFERRED + ObservationFrequencyProposer
                              -> i_noticed,
                           else -> thought_youd_want
      system_b_web      -> heads_up if signals.is_urgent_signal else
                           thought_youd_want
      attention_offer   -> thought_youd_want (offered cards are passive)
      pattern           -> thought_youd_want (cross-source patterns are
                           low-confidence by default)
    """
    if source == "email":
        return "heads_up"
    if source == "calendar":
        return "heads_up"
    if source == "attention_fire":
        return _infer_attention_fire(payload)
    if source == "system_b_web":
        return "heads_up" if signals.get("is_urgent_signal") else "thought_youd_want"
    if source in {"attention_offer", "pattern"}:
        return "thought_youd_want"
    return _DEFAULT


def _infer_attention_fire(payload: dict[str, Any]) -> SpeechAct:
    origin = str(payload.get("origin") or "").upper()
    card = str(payload.get("card") or "").upper()
    proposer = str(payload.get("proposer") or "")
    if origin == "USER_REQUESTED" and card == "PING":
        return "dont_forget"
    if origin == "DONNA_ANTICIPATED":
        return "now_the_moment"
    if origin == "SHADOW_INFERRED" and proposer == "ObservationFrequencyProposer":
        return "i_noticed"
    return _DEFAULT
