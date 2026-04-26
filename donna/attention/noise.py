"""Noise filtering for attentions, open-loops, and debug-shape strings.

Single source of truth so the same heuristic isn't duplicated across
the dashboard composer, the brain context builder, the /observe state
panel, and the CLI. Two shapes get filtered:

1. Things named ``test ...`` — clearly test artifacts that shouldn't
   sit on the user's home screen.
2. Content containing a debug-looking opaque token (long alphanumeric
   run with mixed case, no spaces) — the kind of value the user would
   never naturally write.

Apply at every READ surface that exposes attentions or open-loops to
either the user or to a downstream LLM. Do NOT mutate the underlying
store from here — that's a separate cleanup migration's job.
"""
from __future__ import annotations

import re
from typing import Any, Iterable


_TEST_NAME_RE = re.compile(r"\btest\b", re.IGNORECASE)
_DEBUG_TOKEN_MIN_LEN = 16


def looks_like_debug_token(value: Any) -> bool:
    """True for opaque ID-shape strings — no human writes 'vO7hjeAjmsdlGgUd'."""
    text = str(value or "").strip()
    if len(text) < _DEBUG_TOKEN_MIN_LEN or " " in text or "," in text:
        return False
    alpha_or_digit = sum(1 for c in text if c.isalnum())
    has_mixed_case = any(c.islower() for c in text) and any(c.isupper() for c in text)
    return alpha_or_digit / max(1, len(text)) > 0.85 and has_mixed_case


def content_contains_debug_token(content: Any) -> bool:
    """True if any whitespace-split token in ``content`` is debug-shaped."""
    text = str(content or "")
    if not text:
        return False
    for chunk in text.split():
        if looks_like_debug_token(chunk):
            return True
    return False


def is_noise_attention(attention: Any) -> bool:
    """Drop attentions that are obvious test/debug residue.

    Conservative — only filters when the title or subject reads as a
    test artifact or a debug token. Real user trackers like "test plan
    for fundraise" won't match because the regex is word-boundary
    anchored on the standalone word "test".
    """
    spec = getattr(attention, "spec", None)
    if spec is None:
        return False
    title = str(getattr(spec, "title", "") or "").strip()
    subject = str(getattr(getattr(spec, "subject", None), "name", "") or "").strip()
    if _TEST_NAME_RE.search(title) or _TEST_NAME_RE.search(subject):
        return True
    if looks_like_debug_token(title) or looks_like_debug_token(subject):
        return True
    return False


def is_noise_open_loop(loop: Any) -> bool:
    """Drop open_loops whose content is mostly a debug-shape token."""
    content = getattr(loop, "content", None) or ""
    return content_contains_debug_token(content)


def filter_attentions(rows: Iterable[Any]) -> list[Any]:
    return [a for a in rows if not is_noise_attention(a)]


def filter_open_loops(rows: Iterable[Any]) -> list[Any]:
    return [l for l in rows if not is_noise_open_loop(l)]


def is_noise_observation_field_value(value: Any) -> bool:
    """True for values that look like opaque debug tokens — used by the
    brain context builder when rendering observation fields. Same
    heuristic as ``looks_like_debug_token``; named explicitly here so
    the call site reads as intent.
    """
    if not isinstance(value, str):
        return False
    return looks_like_debug_token(value)


# ── tracker label normalisation ─────────────────────────────────────────
# Lives here (rather than a separate module) because ``donna/attention/
# normalize.py`` is already taken for the LLM intent-normalization
# pipeline. Keeping label dedup adjacent to noise filtering also keeps
# all "data hygiene" knobs in one place.

# Common tracker-label aliases that should collapse onto one instance.
# Keep this list short — it's a tiebreaker for obvious near-duplicates,
# not a full thesaurus. Expand only when a new collision shows up in
# /observe with two near-identical instances for the same user.
_TRACKER_LABEL_ALIASES: dict[str, str] = {
    "expenses": "expense",
    "daily expenses": "expense",
    "daily expense": "expense",
    "expense tracker": "expense",
    "money": "expense",
    "spend": "expense",
    "spending": "expense",
    "calories": "calorie",
    "calorie intake": "calorie",
    "daily calories": "calorie",
    "daily calorie intake": "calorie",
    "meals": "meal",
    "food": "meal",
    "diet": "meal",
    "water": "hydration",
    "water intake": "hydration",
    "hydrate": "hydration",
    "sleep hours": "sleep",
    "hours of sleep": "sleep",
    "moods": "mood",
    "mood log": "mood",
    "exercises": "exercise",
    "workouts": "exercise",
    "workout": "exercise",
}


def normalize_tracker_label(label: str) -> str:
    """Collapse a tracker label to a comparable signature.

    Lowercases, strips, and de-pluralises via the alias table. Trailing
    " tracker" is also dropped so "X tracker" collapses with "X".
    Returns empty string when given empty input.
    """
    text = (label or "").strip().lower()
    if not text:
        return ""
    if text in _TRACKER_LABEL_ALIASES:
        return _TRACKER_LABEL_ALIASES[text]
    if text.endswith(" tracker"):
        text = text[: -len(" tracker")].strip()
        if text in _TRACKER_LABEL_ALIASES:
            return _TRACKER_LABEL_ALIASES[text]
    return text
