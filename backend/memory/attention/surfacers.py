"""Surfacer implementations.

A Surfacer interprets ``surface_policy`` against ``current_state`` and
decides what to do — silent (just refresh state), nudge (WhatsApp burst),
or escalation (conditional WhatsApp burst when a condition matches).

Surfacers return a SurfaceResult; the caller actually performs the
side-effect (sends WhatsApp, updates last_surfaced_at, records a tick).
This separation keeps Surfacers pure and easy to test.

Today's condition language is tiny: comparisons against current_state
fields like ``daily_total > 2300`` or ``count == 0``. A future iteration
could extend this; for now it covers the common cases without dragging
in a full DSL.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from backend.memory.attention.runtime import DeriveContext, SurfaceResult

logger = logging.getLogger(__name__)


# Tiny safe-eval for surface_policy.escalations[].condition.
# Whitelist: operand identifiers from current_state, numeric literals,
# comparison + boolean operators. No function calls, no attribute access.
_ALLOWED_OPS = {">", "<", ">=", "<=", "==", "!=", "AND", "OR", "and", "or"}
_TOKEN_RE = re.compile(
    r"\s*(>=|<=|==|!=|>|<|\(|\)|AND|OR|and|or|"
    r"[A-Za-z_][A-Za-z_0-9]*|\d+(?:\.\d+)?)\s*"
)


def _tokenize(expr: str) -> list[str]:
    pos = 0
    tokens: list[str] = []
    while pos < len(expr):
        m = _TOKEN_RE.match(expr, pos)
        if not m:
            raise ValueError(f"unexpected char at {pos}: {expr[pos:pos+10]!r}")
        tok = m.group(1)
        tokens.append(tok)
        pos = m.end()
    return tokens


def _eval_condition(expr: str, state: dict[str, Any]) -> bool:
    """Evaluate a simple condition like ``daily_total > 2300``.

    Substitutes identifiers from ``current_state`` (also accepts a few
    aliases like ``daily_total`` → ``value_numeric``). Returns False on
    any error — surfacers should fail closed.
    """
    aliases = {
        "daily_total": state.get("value_numeric"),
        "today_total": state.get("value_numeric"),
        "value": state.get("value_numeric"),
        "count": state.get("count"),
        "target": state.get("target"),
        "progress": state.get("progress"),
        "overdue_count": state.get("overdue_count"),
    }

    try:
        tokens = _tokenize(expr)
    except ValueError:
        logger.warning("condition tokenize failed: %r", expr)
        return False

    rendered: list[str] = []
    for t in tokens:
        if t in {"AND", "OR"}:
            rendered.append(t.lower())
            continue
        if t in {"and", "or", ">=", "<=", "==", "!=", ">", "<", "(", ")"}:
            rendered.append(t)
            continue
        # Numeric literal
        try:
            float(t)
            rendered.append(t)
            continue
        except ValueError:
            pass
        # Identifier: must resolve to a number in aliases or state.
        val = aliases.get(t)
        if val is None:
            val = state.get(t)
        if isinstance(val, bool):
            rendered.append("True" if val else "False")
        elif isinstance(val, (int, float)):
            rendered.append(str(val))
        else:
            # Identifier doesn't resolve; condition can't be evaluated.
            logger.debug("condition unresolved: %s in %r", t, expr)
            return False

    expr_safe = " ".join(rendered)
    # Only digits, dots, comparison/boolean ops, parens, True/False, spaces.
    if not re.fullmatch(r"[0-9.()<>=!\s a-zT]+(?:and|or|True|False| |[<>=!()0-9.])*", expr_safe):
        # Looser fullmatch above — defensive, just in case identifiers slipped through.
        logger.debug("condition rejected by safety regex: %r", expr_safe)
        return False
    try:
        return bool(eval(expr_safe, {"__builtins__": {}}, {}))  # noqa: S307 - whitelisted tokens only
    except Exception:
        logger.debug("condition eval raised: %r", expr_safe)
        return False


class PolicySurfacer:
    """Surfacer driven by ``surface_policy``.

    For tally / event_stream / brief — anything with a default + escalations.
    Walks each escalation; if any condition matches, returns a burst with
    the escalation's level/text. Otherwise default behavior:
        silent → no-op
        notify → always burst on fire
    """

    async def surface(
        self,
        *,
        attention: Any,
        current_state: dict[str, Any],
        ctx: DeriveContext,
        trigger: str,
    ) -> SurfaceResult:
        spec = getattr(attention, "spec", None)
        policy = getattr(spec, "surface_policy", None) if spec else None
        if policy is None:
            return SurfaceResult(kind="silent")

        # Walk escalations first — the more specific signal wins.
        escalations = getattr(policy, "escalations", []) or []
        for esc in escalations:
            cond = getattr(esc, "condition", None)
            if not cond:
                continue
            if _eval_condition(str(cond), current_state):
                level = getattr(getattr(esc, "level", None), "value", None) or "notify"
                text = getattr(esc, "text", None) or self._compose_escalation_text(
                    attention, current_state, str(cond)
                )
                return SurfaceResult(
                    kind="escalation",
                    message=text,
                    metadata={"condition": str(cond), "level": level},
                )

        # No escalation matched — defer to default.
        default = getattr(getattr(policy, "default", None), "value", None) or "silent"
        if default == "silent":
            return SurfaceResult(kind="silent")
        if default in ("notify", "burst"):
            title = getattr(spec, "title", "") if spec else ""
            return SurfaceResult(
                kind="burst",
                message=f"{title}: {current_state.get('value', '?')}",
            )
        return SurfaceResult(kind="silent")

    def _compose_escalation_text(
        self,
        attention: Any,
        state: dict[str, Any],
        condition: str,
    ) -> str:
        spec = getattr(attention, "spec", None)
        title = getattr(spec, "title", "tracker") if spec else "tracker"
        value = state.get("value", "?")
        return f"{title} alert — current: {value}. ({condition})"


class StaleNudgeSurfacer:
    """For attentions whose surface_policy carries a nudge_policy.

    Fires a nudge when no events have landed in `if_silent_for_seconds`.
    Caller must pass the elapsed silence in ``current_state['silent_for_seconds']``
    or set it on the attention; surfacer just reads + decides.
    """

    async def surface(
        self,
        *,
        attention: Any,
        current_state: dict[str, Any],
        ctx: DeriveContext,
        trigger: str,
    ) -> SurfaceResult:
        spec = getattr(attention, "spec", None)
        policy = getattr(spec, "surface_policy", None) if spec else None
        if policy is None:
            return SurfaceResult(kind="silent")
        nudge = getattr(policy, "nudge_policy", None)
        if nudge is None:
            return SurfaceResult(kind="silent")

        threshold = getattr(nudge, "if_silent_for_seconds", None)
        silent_for = current_state.get("silent_for_seconds")
        if not threshold or silent_for is None:
            return SurfaceResult(kind="silent")
        try:
            if float(silent_for) < float(threshold):
                return SurfaceResult(kind="silent")
        except (TypeError, ValueError):
            return SurfaceResult(kind="silent")

        text = getattr(nudge, "nudge_text", None) or "log your meals for today?"
        return SurfaceResult(
            kind="nudge",
            message=text,
            metadata={"silent_for_seconds": silent_for, "threshold": threshold},
        )


class SilentSurfacer:
    """No-op surfacer. State updates only — never a burst."""

    async def surface(
        self,
        *,
        attention: Any,
        current_state: dict[str, Any],
        ctx: DeriveContext,
        trigger: str,
    ) -> SurfaceResult:
        return SurfaceResult(kind="silent")
