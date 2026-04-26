"""HMAC token round-trip + tamper / expiry / audience-mismatch coverage."""
from __future__ import annotations

import os
import time

import pytest

from backend.auth import tokens


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_SECRET", "test-secret-do-not-use-in-prod")


@pytest.mark.unit
def test_round_trip_magic() -> None:
    t = tokens.make_magic_token("u_kai")
    payload = tokens.verify_token(t, aud="magic")
    assert payload.user_id == "u_kai"
    assert payload.aud == "magic"
    assert payload.exp > int(time.time())


@pytest.mark.unit
def test_round_trip_session() -> None:
    t = tokens.make_session_token("u_kai", ttl_s=86_400)
    payload = tokens.verify_token(t, aud="session")
    assert payload.user_id == "u_kai"
    assert payload.aud == "session"


@pytest.mark.unit
def test_audience_mismatch_rejected() -> None:
    t = tokens.make_magic_token("u_kai")
    with pytest.raises(tokens.TokenError, match="audience"):
        tokens.verify_token(t, aud="session")


@pytest.mark.unit
def test_tampered_payload_rejected() -> None:
    t = tokens.make_magic_token("u_kai")
    body, _, sig = t.partition(".")
    # Flip a single character in the encoded payload — sig should fail.
    flipped = body[:-1] + ("A" if body[-1] != "A" else "B")
    with pytest.raises(tokens.TokenError, match="signature"):
        tokens.verify_token(f"{flipped}.{sig}", aud="magic")


@pytest.mark.unit
def test_tampered_signature_rejected() -> None:
    t = tokens.make_magic_token("u_kai")
    body, _, _sig = t.partition(".")
    bogus = "0" * 64
    with pytest.raises(tokens.TokenError, match="signature"):
        tokens.verify_token(f"{body}.{bogus}", aud="magic")


@pytest.mark.unit
def test_expired_token_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A token past its expiry must fail closed even with a valid sig."""
    # Mint a token, then fast-forward time by patching ``time.time`` inside
    # ``backend.auth.tokens`` so verify sees us in the future.
    t = tokens.make_token("u_kai", aud="magic", ttl_s=10)
    real_time = time.time
    monkeypatch.setattr(tokens.time, "time", lambda: real_time() + 3600)
    with pytest.raises(tokens.TokenError, match="expired"):
        tokens.verify_token(t, aud="magic")


@pytest.mark.unit
def test_malformed_token_rejected() -> None:
    with pytest.raises(tokens.TokenError):
        tokens.verify_token("not-a-token", aud="magic")
    with pytest.raises(tokens.TokenError):
        tokens.verify_token("", aud="magic")


@pytest.mark.unit
def test_missing_secret_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    monkeypatch.delenv("MAGIC_LINK_SECRET", raising=False)
    with pytest.raises(tokens.TokenError, match="not configured"):
        tokens.make_magic_token("u_kai")
