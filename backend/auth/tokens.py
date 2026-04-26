"""Stateless HMAC-signed tokens for magic links and session cookies.

A token is ``b64url(payload_json) + '.' + hex_hmac``. ``payload`` carries the
``user_id``, expiry (unix seconds), and an audience tag (``magic`` /
``session``) so a magic-link token cannot be replayed as a session cookie.

No DB writes on issue or verify. Revocation is handled by short TTLs
(magic link 5 min; session 5 min for magic-derived, 24h for OTP-derived).

Reads ``AUTH_SECRET`` from env. Falls back to ``MAGIC_LINK_SECRET`` for
backwards-compatibility with ops that prefer two distinct keys; the same
key works for both audiences in v1.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

Audience = Literal["magic", "session"]

# Magic links live 5 minutes from issue. The link itself is short-lived
# so a leaked URL has a tiny blast radius; the SESSION it issues is
# separate (and long-lived) — see below.
MAGIC_TTL_S = 300
# Sessions live 30 days. The cookie is **rolling**: every authenticated
# request re-issues the cookie with a fresh 30-day window via
# ``/api/auth/whoami``. So a user only needs another magic link after
# 30 days of total inactivity.
SESSION_TTL_S = 30 * 24 * 3600  # 30 days
# Back-compat aliases for any caller that imports the old names. Both
# auth paths now produce the same long-lived session — the differentiator
# was always trust signal, and a successful magic-link redemption is
# enough trust to issue a 30-day session.
SESSION_TTL_MAGIC_S = SESSION_TTL_S
SESSION_TTL_OTP_S = SESSION_TTL_S


class TokenError(Exception):
    """Raised when a token is malformed, expired, wrong audience, or
    fails signature verification. Callers should treat any TokenError as
    'reject this request' — never leak the specific reason to the user."""


@dataclass(frozen=True)
class TokenPayload:
    user_id: str
    aud: Audience
    exp: int  # unix seconds


def _secret() -> bytes:
    raw = os.environ.get("AUTH_SECRET") or os.environ.get("MAGIC_LINK_SECRET")
    if not raw:
        raise TokenError("AUTH_SECRET (or MAGIC_LINK_SECRET) not configured")
    return raw.encode("utf-8")


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    padding = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + padding)


def _sign(body: bytes) -> str:
    return hmac.new(_secret(), body, hashlib.sha256).hexdigest()


def make_token(user_id: str, *, aud: Audience, ttl_s: int) -> str:
    """Sign a token. ``user_id`` is the canonical ``users.id``; ``aud`` pins
    the use-case so a leaked magic link cannot be replayed as a session."""
    if not user_id:
        raise ValueError("user_id required")
    if ttl_s <= 0:
        raise ValueError("ttl_s must be positive")
    payload = json.dumps(
        {"u": user_id, "a": aud, "e": int(time.time()) + ttl_s},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    body_b64 = _b64url_encode(payload)
    sig = _sign(body_b64.encode("ascii"))
    return f"{body_b64}.{sig}"


def verify_token(token: str, *, aud: Audience) -> TokenPayload:
    """Verify a token's signature, expiry, and audience.

    Raises ``TokenError`` on any failure. Callers convert that into a
    401/403 — never echo the underlying reason to the client.
    """
    if not token or "." not in token:
        raise TokenError("malformed token")
    body_b64, _, sig = token.partition(".")
    expected = _sign(body_b64.encode("ascii"))
    if not hmac.compare_digest(sig, expected):
        raise TokenError("bad signature")
    try:
        payload = json.loads(_b64url_decode(body_b64))
    except Exception as exc:
        raise TokenError("undecodable payload") from exc
    user_id = payload.get("u")
    token_aud = payload.get("a")
    exp = payload.get("e")
    if not isinstance(user_id, str) or not user_id:
        raise TokenError("missing user_id")
    if token_aud != aud:
        raise TokenError(f"audience mismatch: {token_aud!r} ≠ {aud!r}")
    if not isinstance(exp, int):
        raise TokenError("missing expiry")
    if exp < int(time.time()):
        raise TokenError("expired")
    return TokenPayload(user_id=user_id, aud=token_aud, exp=exp)


def make_magic_token(user_id: str) -> str:
    """5-minute magic-link token. Embedded in ``?t=…`` on the dashboard."""
    return make_token(user_id, aud="magic", ttl_s=MAGIC_TTL_S)


def make_session_token(user_id: str, *, ttl_s: int = SESSION_TTL_MAGIC_S) -> str:
    """Session cookie token. ``ttl_s`` defaults to the magic-link redemption
    window (5 min); OTP verification path uses ``SESSION_TTL_OTP_S``."""
    return make_token(user_id, aud="session", ttl_s=ttl_s)
