"""Local end-to-end verification of the integration-notify path.

Spins up an in-memory DB with a fake user, stubs Composio's "list active
connections" + WhatsApp send, then drives ``watch_oauth_and_bootstrap``
to confirm:

  1. Watcher polls Composio.
  2. Notify path reaches WA send (captured) with the right body.
  3. Dedupe map is updated in users.living_profile.
  4. A second invocation in the dedupe window is skipped.

This is the local mirror of "user disconnects + reconnects in prod" —
gives confidence the path is wired before asking the user to live-test.

Usage:
    python -m scripts.verify_notify_path
"""
from __future__ import annotations

import asyncio
import sys

import pytest_asyncio  # noqa: F401  - imported so SQLAlchemy compile shim runs
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles


@compiles(JSONB, "sqlite")
def _sqlite_jsonb(type_, compiler, **kw):  # type: ignore[no-untyped-def]
    return "JSON"


WA_SENDS: list[tuple[str, str]] = []


class _FakeWhatsApp:
    async def send(self, phone, message):
        body = getattr(message, "body", str(message))
        WA_SENDS.append((phone, body))
        return "fake-wamid"

    async def send_many(self, phone, messages):
        for m in messages:
            await self.send(phone, m)
        return ["fake-wamid"]


async def _patch_modules(test_session) -> None:
    import backend.db.session as backend_session
    import db.session as root_session

    backend_session.async_session = test_session
    root_session.async_session = test_session

    # Patch Composio's "list active connections" to claim notion is ACTIVE.
    from backend.integrations import oauth_watcher

    async def _fake_list(user_id, toolkits):
        return {tk: f"ca_{tk}" for tk in toolkits if tk == "notion"}

    oauth_watcher._list_active_connections = _fake_list  # type: ignore[assignment]

    # Patch WA delivery — notify imports inline at call time, so we have to
    # have ``delivery.whatsapp.WhatsAppChannel`` resolved to our fake before
    # the call lands.
    import delivery.whatsapp as _wa_mod
    _wa_mod.WhatsAppChannel = _FakeWhatsApp  # type: ignore[attr-defined]


async def main() -> int:
    from db.models import Base, User

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    test_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with test_session() as s:
        s.add(User(id="u1", phone="+15551234567"))
        await s.commit()

    await _patch_modules(test_session)

    from backend.integrations.oauth_watcher import watch_oauth_and_bootstrap

    print("\nrunning notify-path verification...\n")
    print("[1] watcher invocation 1 (fresh notion connection)")
    await watch_oauth_and_bootstrap(
        user_id="u1", toolkits=["notion"], timeout_seconds=2
    )
    print(f"    WA sends so far: {len(WA_SENDS)}")
    if WA_SENDS:
        phone, body = WA_SENDS[-1]
        print(f"    last send: phone={phone} body={body!r}")
    else:
        print("    [FAIL] no WA send happened")

    # Second invocation should be deduped.
    print("\n[2] watcher invocation 2 (within dedupe window)")
    sends_before = len(WA_SENDS)
    await watch_oauth_and_bootstrap(
        user_id="u1", toolkits=["notion"], timeout_seconds=2
    )
    sends_after = len(WA_SENDS)
    if sends_after == sends_before:
        print("    OK — dedupe suppressed the second send")
    else:
        print("    [FAIL] dedupe failed; second send happened")

    # Read the dedupe map to confirm persistence.
    from sqlalchemy import select
    async with test_session() as s:
        user = (await s.execute(select(User).where(User.id == "u1"))).scalar_one()
        notified = (user.living_profile or {}).get("notified_integrations") or {}
    print(f"\n[3] notified_integrations map: {notified}")

    success = (
        len(WA_SENDS) == 1
        and "notion" in (WA_SENDS[0][1] or "").lower()
        and any("notion" in k for k in notified)
    )
    print()
    print("RESULT:", "PASS" if success else "FAIL")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
