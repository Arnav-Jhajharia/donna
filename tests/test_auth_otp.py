"""OTP issue + verify against the live test database.

Requires a usable ``DATABASE_URL`` and the migration chain through 0009 to
have been applied. Gated by ``DONNA_RUN_INTEGRATION_TESTS=1`` because:

  - probing the DB at collection time would bind asyncpg connections to a
    throwaway loop and poison subsequent tests, and
  - the suite should stay green offline.

``asyncio_mode = "auto"`` in pyproject means async tests run automatically;
``_reset_engine`` disposes the module-level engine between tests so each
test gets a connection pool bound to its own pytest-asyncio loop.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy import delete, select

from backend.auth import otp
from db.models import AuthOTP, User
from db.session import _engine, async_session


pytestmark = pytest.mark.skipif(
    os.environ.get("DONNA_RUN_INTEGRATION_TESTS") != "1",
    reason="set DONNA_RUN_INTEGRATION_TESTS=1 to run DB-bound tests",
)


@pytest.fixture(autouse=True)
async def _reset_engine():
    """Dispose the engine pool after each test so the next test's loop
    gets a fresh pool bound to it (pytest-asyncio creates a new loop per
    test). Without this, the second test fails with ``Future attached to
    a different loop``."""
    yield
    await _engine.dispose()


async def _make_user() -> str:
    user_id = f"otp-test-{uuid.uuid4()}"
    async with async_session() as s:
        s.add(User(id=user_id, phone=f"+otp-{user_id}", timezone="UTC"))
        await s.commit()
    return user_id


async def _cleanup(user_id: str) -> None:
    async with async_session() as s:
        await s.execute(delete(AuthOTP).where(AuthOTP.user_id == user_id))
        await s.execute(delete(User).where(User.id == user_id))
        await s.commit()


@pytest.mark.integration
async def test_issue_then_verify_succeeds() -> None:
    user_id = await _make_user()
    try:
        code = await otp.issue_otp(user_id)
        assert code.isdigit()
        assert len(code) == otp.OTP_LENGTH
        ok = await otp.verify_otp(user_id, code)
        assert ok is True
    finally:
        await _cleanup(user_id)


@pytest.mark.integration
async def test_verify_consumes_code() -> None:
    """Single-use: a successful verify deletes the row, second verify fails."""
    user_id = await _make_user()
    try:
        code = await otp.issue_otp(user_id)
        assert await otp.verify_otp(user_id, code) is True
        assert await otp.verify_otp(user_id, code) is False
    finally:
        await _cleanup(user_id)


@pytest.mark.integration
async def test_verify_wrong_code_fails() -> None:
    user_id = await _make_user()
    try:
        await otp.issue_otp(user_id)
        assert await otp.verify_otp(user_id, "000000") is False
        # Real code still valid afterwards (wrong-code attempts don't burn it).
        # We can't read the plaintext so just check that one issued code
        # remains in the table.
        async with async_session() as s:
            rows = (
                await s.execute(
                    select(AuthOTP).where(AuthOTP.user_id == user_id)
                )
            ).scalars().all()
        assert len(rows) == 1
    finally:
        await _cleanup(user_id)


@pytest.mark.integration
async def test_active_cap_prunes_oldest() -> None:
    """At the cap, issuing a new code drops the oldest one."""
    user_id = await _make_user()
    try:
        # Issue MAX_ACTIVE + 1 codes; the first should get pruned.
        codes = [await otp.issue_otp(user_id) for _ in range(otp.MAX_ACTIVE_OTPS_PER_USER + 1)]
        async with async_session() as s:
            rows = (
                await s.execute(
                    select(AuthOTP).where(AuthOTP.user_id == user_id)
                )
            ).scalars().all()
        assert len(rows) == otp.MAX_ACTIVE_OTPS_PER_USER
        # Oldest code should no longer verify.
        assert await otp.verify_otp(user_id, codes[0]) is False
        # Newest code should still verify.
        assert await otp.verify_otp(user_id, codes[-1]) is True
    finally:
        await _cleanup(user_id)


@pytest.mark.unit
def test_malformed_input_rejected_synchronously() -> None:
    """Non-numeric or wrong-length inputs short-circuit before the DB."""
    async def go() -> None:
        assert await otp.verify_otp("u_x", "abc") is False
        assert await otp.verify_otp("u_x", "12345") is False
        assert await otp.verify_otp("", "123456") is False
    asyncio.run(go())
