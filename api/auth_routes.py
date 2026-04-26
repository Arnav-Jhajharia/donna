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


def _set_session_cookie(
    response: Response, user_id: str, *, ttl_s: int, request: Request
) -> None:
    """Issue the session cookie. Marked Secure when the request came over
    HTTPS; the dev server on localhost-http would reject Secure cookies,
    so we relax it there. ``SameSite=Lax`` is enough — the cookie never
    needs to ride a cross-site POST."""
    token = make_session_token(user_id, ttl_s=ttl_s)
    is_https = request.url.scheme == "https"
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=ttl_s,
        httponly=True,
        secure=is_https,
        samesite="lax",
        path="/",
    )


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
async def logout(response: Response) -> dict[str, Any]:
    """Clear the session cookie. No-op if no cookie was set."""
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
