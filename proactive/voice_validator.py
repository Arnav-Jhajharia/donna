"""Deterministic voice net for Tier 2 drafts.

The Tier 2 prompt enforces Donna's voice. This module is a defensive
post-pass that catches drift before any draft reaches the user. It is
intentionally narrow — punctuation strip + uppercase ratio + emoji
detection. Anything subtler stays in the prompt.

Flow used by the dispatcher:

  1. ``validate(draft)`` — fast deterministic check.
  2. If not ok and reason is ``em_dash``/``semicolon`` only, the validator
     ``apply(draft)`` returns a clean string and the dispatcher ships it.
  3. If reason is ``uppercase_ratio`` or ``emoji``, the dispatcher
     re-authors once with explicit guidance, then validates again. A
     second failure is the dispatcher's signal to fall back to Tier 3.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Em-dashes (long + short) and semicolons — banned punctuation. Strip is
# mechanical: replace em-dash with a space, semicolon with a period.
_EM_DASHES = ("—", "–")  # — and –
_SEMICOLON = ";"

# Conservative emoji regex covering the common ranges. Avoids pulling in a
# dependency. Unicode 15.x has more codepoints; this catches the cases
# Tier 2 actually drifts into (smileys, hands, hearts, symbols).
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF"  # misc symbols, supplemental, emoticons
    "\U0001F600-\U0001F64F"   # emoticons
    "\U0001F680-\U0001F6FF"   # transport and map
    "\U0001F700-\U0001F77F"   # alchemical
    "\U0001F900-\U0001F9FF"   # supplemental symbols and pictographs
    "\U0001FA70-\U0001FAFF"   # symbols and pictographs extended-A
    "☀-➿"           # miscellaneous symbols + dingbats
    "]"
)

# 5% of alphabetic chars uppercase = re-author.
_UPPERCASE_RATIO_LIMIT = 0.05


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of running a draft through the voice validator.

    ``ok`` — True when the draft (or its mechanically-stripped form) is
             safe to ship as-is. False when the draft needs an LLM
             re-author (uppercase / emoji).
    ``reasons`` — every rule the original draft tripped, in order.
                  Useful for telemetry even when ``ok`` is True.
    ``cleaned`` — the final text to ship when ``ok`` is True. Mechanical
                  strips (em-dash, semicolon) are already applied.
    """

    ok: bool
    reasons: tuple[str, ...]
    cleaned: str


def _has_em_dash(text: str) -> bool:
    return any(d in text for d in _EM_DASHES)


def _has_semicolon(text: str) -> bool:
    return _SEMICOLON in text


def _has_emoji(text: str) -> bool:
    return bool(_EMOJI_RE.search(text))


def _uppercase_ratio(text: str) -> float:
    alpha = [c for c in text if c.isalpha()]
    if not alpha:
        return 0.0
    upper = sum(1 for c in alpha if c.isupper())
    return upper / len(alpha)


def apply_mechanical_strips(text: str) -> str:
    """Replace em-dashes with spaces, semicolons with periods.

    Used both inside ``validate`` and as a public helper so callers can
    sanitize a string they intend to ship without re-running the full check.
    """
    out = text
    for dash in _EM_DASHES:
        out = out.replace(dash, " ")
    out = out.replace(_SEMICOLON, ".")
    # Collapse any double spaces the dash strip introduced. Keeps lines tidy
    # without rewriting whitespace policy.
    out = re.sub(r" {2,}", " ", out)
    return out


def validate(text: str) -> ValidationResult:
    """Run the deterministic checks on a Tier 2 draft.

    Always returns a ``ValidationResult`` with ``cleaned`` populated. When
    ``ok`` is ``False`` the ``reasons`` tuple lists why; the dispatcher
    decides whether to ship ``cleaned`` (em-dash / semicolon only) or
    re-author (uppercase / emoji).
    """
    reasons: list[str] = []

    if _has_em_dash(text):
        reasons.append("em_dash")
    if _has_semicolon(text):
        reasons.append("semicolon")
    if _has_emoji(text):
        reasons.append("emoji")
    if _uppercase_ratio(text) > _UPPERCASE_RATIO_LIMIT:
        reasons.append("uppercase_ratio")

    cleaned = apply_mechanical_strips(text)

    # ``ok`` is True only when there are no reasons OR all reasons are
    # mechanically fixable AND the cleaned text passes the residual
    # checks. Uppercase / emoji are not mechanically repaired here — they
    # require an LLM re-author, not a strip.
    fixable = {"em_dash", "semicolon"}
    if not reasons:
        return ValidationResult(ok=True, reasons=(), cleaned=cleaned)
    if set(reasons).issubset(fixable):
        # Defensive: re-check the cleaned text didn't somehow violate a
        # different rule. (Stripping em-dashes will not introduce one.)
        residual: list[str] = []
        if _has_emoji(cleaned):
            residual.append("emoji")
        if _uppercase_ratio(cleaned) > _UPPERCASE_RATIO_LIMIT:
            residual.append("uppercase_ratio")
        if residual:
            return ValidationResult(
                ok=False,
                reasons=tuple(residual),
                cleaned=cleaned,
            )
        return ValidationResult(
            ok=True,
            reasons=tuple(reasons),
            cleaned=cleaned,
        )
    return ValidationResult(ok=False, reasons=tuple(reasons), cleaned=cleaned)
