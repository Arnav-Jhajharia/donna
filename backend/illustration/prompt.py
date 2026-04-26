"""Compose the fal.ai prompt + style for the Day 1 illustration.

The prompt is deliberately *simple*. We do not try to art-direct in words —
we let Recraft's ``style`` parameter carry the look. Words go to subject +
mood + atmosphere only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from backend.illustration.cities import TimeBand, descriptor_for

Weather = Literal["clear", "rain", "cloud", "snow", "fog", "heat"]

# Recraft v3 style preset — "hand_drawn" matches the warm, inviting brief.
DEFAULT_STYLE = "digital_illustration/hand_drawn"
DEFAULT_IMAGE_SIZE = "landscape_16_9"


@dataclass(frozen=True)
class IllustrationRequest:
    """Inputs for one Day 1 illustration."""

    city: str | None
    time_band: TimeBand
    weather: Weather = "clear"


@dataclass(frozen=True)
class FalArguments:
    """The exact dict we pass to ``fal_client.subscribe_async``."""

    prompt: str
    image_size: str
    style: str

    def to_dict(self) -> dict[str, str]:
        return {"prompt": self.prompt, "image_size": self.image_size, "style": self.style}


_TIME_MOOD: dict[TimeBand, str] = {
    "dawn": "soft pre-dawn blue-grey light, very early, calm",
    "morning": "warm soft morning sunlight, golden",
    "midday": "bright clean midday light, neutral",
    "evening": "warm low-angle evening light, amber",
    "late": "low warm lamplight against deep night, intimate",
}

_WEATHER_TEXTURE: dict[Weather, str] = {
    "clear": "",
    "rain": "with soft raindrops on the window glass behind",
    "cloud": "with a soft overcast diffuse light",
    "snow": "with gentle snow falling outside the window behind",
    "fog": "with a soft fog haze in the background",
    "heat": "with a soft warm haze in the background",
}


def time_band_for_hour(hour: int) -> TimeBand:
    """Coarse clock-hour fallback. Replace with sun-position math later."""
    if 4 <= hour < 7:
        return "dawn"
    if 7 <= hour < 11:
        return "morning"
    if 11 <= hour < 16:
        return "midday"
    if 16 <= hour < 21:
        return "evening"
    return "late"


def time_band_for_local(now: datetime) -> TimeBand:
    return time_band_for_hour(now.hour)


def build_arguments(request: IllustrationRequest) -> FalArguments:
    """Compose the fal arguments for one illustration request."""
    subject = descriptor_for(request.city, request.time_band)
    mood = _TIME_MOOD[request.time_band]
    texture = _WEATHER_TEXTURE[request.weather]

    parts = [
        subject,
        mood,
        texture,
        "minimal background, intimate close-up, simple painterly illustration, soft brushstrokes, no text, no people",
    ]
    prompt = ", ".join(p for p in parts if p)
    return FalArguments(
        prompt=prompt,
        image_size=DEFAULT_IMAGE_SIZE,
        style=DEFAULT_STYLE,
    )
