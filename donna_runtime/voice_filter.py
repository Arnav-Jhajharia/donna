"""Donna voice filter.

Deterministic regex lint for Donna's voice rules. Fail-closed: on violation,
strip/rewrite the offending pattern and record the violation so evals can
catch regressions in the underlying prompt.

Voice rules (from CLAUDE.md):
- lowercase register
- no em dashes
- no semicolons
- no banned filler phrases ("I understand", "Great question",
  "AI assistant", "I'm here to help")

The filter is idempotent: filter(filter(x)) == filter(x).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Pattern


BANNED_PHRASES: tuple[str, ...] = (
    "I understand",
    "Great question",
    "AI assistant",
    "I'm here to help",
)

_BANNED_PATTERNS: tuple[Pattern[str], ...] = tuple(
    re.compile(rf"\b{re.escape(p)}\b[\s,.!:;-]*", re.IGNORECASE) for p in BANNED_PHRASES
)

_EM_DASH = re.compile(r"\s*[—–]\s*")
_SEMICOLON = re.compile(r"\s*;\s*")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")
_SENTENCE_START = re.compile(r"(^|(?<=[.!?]\s))([A-Z])")


@dataclass(frozen=True)
class VoiceFilterResult:
    text: str
    violations: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not self.violations


def filter_text(text: str) -> VoiceFilterResult:
    """Apply voice rules to a single body of text.

    Returns the rewritten text plus a tuple of violation codes. Codes are
    stable strings suitable for logging/eval assertions.
    """
    if not isinstance(text, str) or not text:
        return VoiceFilterResult(text=text or "", violations=())

    violations: list[str] = []
    out = text

    for pat in _BANNED_PATTERNS:
        if pat.search(out):
            violations.append(f"banned_phrase:{pat.pattern}")
            out = pat.sub("", out)

    if _EM_DASH.search(out):
        violations.append("em_dash")
        out = _EM_DASH.sub(", ", out)

    if _SEMICOLON.search(out):
        violations.append("semicolon")
        out = _SEMICOLON.sub(". ", out)

    def _lower(match: re.Match[str]) -> str:
        return f"{match.group(1)}{match.group(2).lower()}"

    lowered = _SENTENCE_START.sub(_lower, out)
    if lowered != out:
        violations.append("uppercase_sentence_start")
        out = lowered

    out = _MULTI_SPACE.sub(" ", out).strip()

    return VoiceFilterResult(text=out, violations=tuple(violations))


def filter_burst_items(items: object) -> tuple[list[object], tuple[str, ...]]:
    """Apply the filter to a raw `send_burst` `messages` payload.

    Accepts the same shape `send_burst_result` receives (strings or schema
    dicts). Returns (new_items, all_violations). Non-text items pass through
    unchanged.
    """
    from collections.abc import Mapping, Sequence

    if not isinstance(items, Sequence) or isinstance(items, str):
        return [], ()

    new_items: list[object] = []
    all_violations: list[str] = []

    for item in items:
        if isinstance(item, str):
            res = filter_text(item)
            all_violations.extend(res.violations)
            new_items.append(res.text)
            continue

        if isinstance(item, Mapping):
            new_item = dict(item)
            body = new_item.get("body")
            if isinstance(body, str) and body:
                res = filter_text(body)
                all_violations.extend(res.violations)
                new_item["body"] = res.text
            caption = new_item.get("caption")
            if isinstance(caption, str) and caption:
                res = filter_text(caption)
                all_violations.extend(res.violations)
                new_item["caption"] = res.text
            new_items.append(new_item)
            continue

        new_items.append(item)

    return new_items, tuple(all_violations)
