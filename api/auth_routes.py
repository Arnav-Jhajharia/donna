"""Auth surface — magic-link redemption + OTP verification.

Both endpoints take credentials and return a fresh ``donna_session`` cookie
plus the resolved ``user_id``. Cookie TTL differs by audience:

- magic redemption  → 5 min (per product spec; user comes back to WhatsApp).
- OTP verification  → 24 hours (user typed a 6-digit code, longer trust).

The frontend ``/auth/magic`` route handler calls ``redeem-magic`` and the
``/auth/otp`` page calls ``verify-otp``. Neither endpoint reveals *why* a
credential was rejected — wrong code, expired, missing user all collapse
to a single 401 to avoid OTP-existence probes.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.auth.otp import verify_otp
from backend.auth.tokens import (
    SESSION_TTL_MAGIC_S,
    SESSION_TTL_OTP_S,
    SESSION_TTL_S,
    TokenError,
    make_session_token,
    verify_token,
)
from db.models import User
from db.session import async_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_COOKIE = "donna_session"


def _cookie_domain(request: Request) -> str | None:
    """Resolve the Domain attribute for the session cookie.

    Without an explicit Domain, browsers scope cookies to the EXACT host
    that responded. That breaks the canonical Safari path: magic link
    sets the cookie on ``itsmedonna.com``, then the user types
    ``itsmedonna.com`` in Google and Google sometimes rewrites that to
    ``www.itsmedonna.com`` — different host, no cookie, landing page
    shows up instead of the dashboard.

    Setting Domain to the registrable apex with a leading dot
    (``.itsmedonna.com``) makes the cookie available to all subdomains
    AND the apex, fixing the www-vs-apex split.

    Source of truth: ``SESSION_COOKIE_DOMAIN`` env var. Set to
    ``.itsmedonna.com`` in prod. Leave unset in local dev (browsers
    refuse Domain on ``localhost``).
    """
    domain = (os.environ.get("SESSION_COOKIE_DOMAIN") or "").strip()
    if not domain:
        return None
    # Refuse to set Domain on localhost — Safari/Chrome reject it.
    host = request.url.hostname or ""
    if host in ("localhost", "127.0.0.1") or host.endswith(".localhost"):
        return None
    return domain


def _set_session_cookie(
    response: Response, user_id: str, *, ttl_s: int, request: Request
) -> None:
    """Issue the session cookie.

    - ``Secure`` on HTTPS (dev server on http-localhost relaxes it,
      since Secure cookies don't ship over plain http).
    - ``SameSite=Lax`` — top-level navigation only; the cookie never
      needs to ride a cross-site POST.
    - ``Domain`` resolved from ``SESSION_COOKIE_DOMAIN`` env so a single
      cookie covers ``itsmedonna.com`` AND ``www.itsmedonna.com``
      AND any subdomains we add later. Without this, Safari users who
      land on the apex via magic link and then visit www get treated
      as logged out.
    """
    token = make_session_token(user_id, ttl_s=ttl_s)
    is_https = request.url.scheme == "https"
    domain = _cookie_domain(request)
    kwargs: dict[str, Any] = dict(
        key=SESSION_COOKIE,
        value=token,
        max_age=ttl_s,
        httponly=True,
        secure=is_https,
        samesite="lax",
        path="/",
    )
    if domain:
        kwargs["domain"] = domain
    response.set_cookie(**kwargs)


class RedeemMagicRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=512)


class VerifyOTPRequest(BaseModel):
    phone: str = Field(..., min_length=1, max_length=32)
    code: str = Field(..., min_length=6, max_length=6)


class AuthSuccess(BaseModel):
    user_id: str
    expires_in_s: int


@router.post("/redeem-magic", response_model=AuthSuccess)
async def redeem_magic(
    payload: RedeemMagicRequest,
    request: Request,
    response: Response,
) -> AuthSuccess:
    try:
        verified = verify_token(payload.token, aud="magic")
    except TokenError as exc:
        logger.info("redeem_magic rejected: %s", exc)
        raise HTTPException(status_code=401, detail="invalid or expired link")

    # Confirm the user still exists — a stale token for a deleted user
    # should fail closed even if the signature is valid.
    async with async_session() as session:
        exists = (
            await session.execute(
                select(User.id).where(User.id == verified.user_id)
            )
        ).scalar_one_or_none()
    if exists is None:
        logger.warning("redeem_magic: token user not found user_id=%s", verified.user_id)
        raise HTTPException(status_code=401, detail="invalid or expired link")

    _set_session_cookie(response, verified.user_id, ttl_s=SESSION_TTL_MAGIC_S, request=request)
    return AuthSuccess(user_id=verified.user_id, expires_in_s=SESSION_TTL_MAGIC_S)


@router.post("/verify-otp", response_model=AuthSuccess)
async def verify_otp_route(
    payload: VerifyOTPRequest,
    request: Request,
    response: Response,
) -> AuthSuccess:
    # Resolve phone → user_id. Treat missing as a generic 401 to avoid
    # leaking which phone numbers have accounts.
    async with async_session() as session:
        user_id = (
            await session.execute(
                select(User.id).where(User.phone == payload.phone.strip())
            )
        ).scalar_one_or_none()
    if not user_id:
        logger.info("verify_otp: phone not registered")
        raise HTTPException(status_code=401, detail="invalid code")

    ok = await verify_otp(user_id, payload.code)
    if not ok:
        raise HTTPException(status_code=401, detail="invalid code")

    _set_session_cookie(response, user_id, ttl_s=SESSION_TTL_OTP_S, request=request)
    return AuthSuccess(user_id=user_id, expires_in_s=SESSION_TTL_OTP_S)


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict[str, Any]:
    """Clear the session cookie. No-op if no cookie was set.

    Must use the same Domain attribute the cookie was set with — otherwise
    the browser keeps a stale copy of the cookie on the apex while the
    delete only clears the host-specific one.
    """
    domain = _cookie_domain(request)
    if domain:
        response.delete_cookie(key=SESSION_COOKIE, path="/", domain=domain)
    else:
        response.delete_cookie(key=SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/whoami")
async def whoami(request: Request, response: Response) -> dict[str, Any]:
    """Resolve the session cookie to a user_id, or 401.

    Rolling-window behavior: when the cookie verifies, we re-issue it
    with a fresh 30-day window. The frontend calls this endpoint on
    every page load (via ``resolveUserId``), so any active user keeps
    their session alive without re-authenticating. Inactivity for the
    full TTL is the only thing that drops them back to /auth/signin.
    """
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="no session")
    try:
        verified = verify_token(token, aud="session")
    except TokenError:
        raise HTTPException(status_code=401, detail="invalid session")
    # Refresh the cookie so the 30-day clock resets from now.
    _set_session_cookie(
        response, verified.user_id, ttl_s=SESSION_TTL_S, request=request
    )
    return {"user_id": verified.user_id, "expires_at": verified.exp}
