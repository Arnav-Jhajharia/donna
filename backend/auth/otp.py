"""OTP issue + verify for the WhatsApp login fallback.

Codes are 6-digit numeric. We store ``sha256(code).hexdigest()`` so the
DB never holds the plaintext. ``issue_otp`` returns the plaintext exactly
once for the caller (the brain tool) to weave into a WhatsApp message;
nothing else logs or persists it.

Single-use: ``verify_otp`` deletes the row on a hit. Expired rows are
deleted on read. A cap of 3 active rows per user limits the number of
parallel codes; older codes get pruned when the cap is hit.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Final

from sqlalchemy import delete, select

from db.models import AuthOTP
from db.session import async_session

logger = logging.getLogger(__name__)

OTP_LENGTH: Final = 6
OTP_TTL_S: Final = 600  # 10 minutes
MAX_ACTIVE_OTPS_PER_USER: Final = 3


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _generate_code() -> str:
    """Cryptographically random 6-digit code, zero-padded.

    ``secrets.randbelow(10**6)`` is uniform over 0..999999; padding keeps
    leading zeros so the user always sees a 6-digit string."""
    return f"{secrets.randbelow(10**OTP_LENGTH):0{OTP_LENGTH}d}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def issue_otp(user_id: str) -> str:
    """Generate a fresh code, store its hash, return the plaintext.

    Caller is responsible for delivering the plaintext (e.g. via WhatsApp)
    and never persisting or logging it. Older codes for this user beyond
    the cap get pruned in the same transaction.
    """
    if not user_id:
        raise ValueError("user_id required")
    code = _generate_code()
    code_hash = _hash(code)
    expires_at = _utcnow() + timedelta(seconds=OTP_TTL_S)

    async with async_session() as session:
        # Drop expired rows for this user before counting active.
        await session.execute(
            delete(AuthOTP).where(
                AuthOTP.user_id == user_id,
                AuthOTP.expires_at < _utcnow(),
            )
        )
        active = (
            await session.execute(
                select(AuthOTP)
                .where(AuthOTP.user_id == user_id)
                .order_by(AuthOTP.created_at.asc())
            )
        ).scalars().all()
        # Prune oldest until we have room for one more.
        excess = len(active) - (MAX_ACTIVE_OTPS_PER_USER - 1)
        if excess > 0:
            for row in active[:excess]:
                await session.delete(row)
        session.add(
            AuthOTP(
                user_id=user_id,
                code_hash=code_hash,
                expires_at=expires_at,
            )
        )
        await session.commit()
    return code


async def verify_otp(user_id: str, code: str) -> bool:
    """Return True iff a non-expired row matches; row is deleted on hit.

    The caller treats the boolean as the entire decision — never echo why
    a verify failed (wrong code vs expired vs missing) to the client."""
    if not user_id or not code or not code.isdigit() or len(code) != OTP_LENGTH:
        return False
    code_hash = _hash(code)
    async with async_session() as session:
        # Drop expired rows up front so a stale match cannot pass.
        await session.execute(
            delete(AuthOTP).where(
                AuthOTP.user_id == user_id,
                AuthOTP.expires_at < _utcnow(),
            )
        )
        row = (
            await session.execute(
                select(AuthOTP)
                .where(
                    AuthOTP.user_id == user_id,
                    AuthOTP.code_hash == code_hash,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        await session.delete(row)
        await session.commit()
    return True
