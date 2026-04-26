"""Disconnect a user's Composio connected accounts AND clear local
integration state. Safe-by-default: shows what WOULD be deleted unless
``--confirm`` is passed.

What it does (in --confirm mode):
  1. Lists Composio connected accounts for the user
  2. Deletes each (so the next authorize() call starts a fresh OAuth)
  3. Deletes rows from the local `integrations` table for the user

What it does NOT touch:
  - email_messages, calendar_entries (you can drop those manually if you
    want a truly cold bootstrap; otherwise re-bootstrap will upsert)
  - users.living_profile (biography stays until next bootstrap rewrites)

Usage:
  # See what would be deleted (default, safe):
  python scripts/disconnect_integrations.py --user-id <user_id>

  # Just print current state without ANY changes:
  python scripts/disconnect_integrations.py --user-id <user_id> --status-only

  # Actually delete (REQUIRED for any deletion):
  python scripts/disconnect_integrations.py --user-id <user_id> --confirm

  # Scope deletion to one provider:
  python scripts/disconnect_integrations.py --user-id <user_id> --confirm --provider google
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from donna_runtime.env import load_dotenv

load_dotenv()

from composio import Composio  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from backend.db.session import async_session  # noqa: E402
from db.models import Integration  # noqa: E402


async def _list_composio_accounts(user_id: str) -> list:
    composio = Composio()
    listing = composio.connected_accounts.list(user_ids=[user_id])
    items = listing.items if hasattr(listing, "items") else list(listing)
    return list(items)


async def _list_local_rows(user_id: str, provider: str | None) -> list[Integration]:
    async with async_session() as s:
        stmt = select(Integration).where(Integration.user_id == user_id)
        if provider:
            stmt = stmt.where(Integration.provider == provider)
        return list((await s.execute(stmt)).scalars().all())


def _print_state(
    composio_items: list, local_rows: list[Integration], header: str
) -> None:
    print(f"\n=== {header} ===")
    print(f"Composio connected_accounts ({len(composio_items)}):")
    if not composio_items:
        print("  (none)")
    for ca in composio_items:
        slug = getattr(getattr(ca, "toolkit", None), "slug", "?")
        status = getattr(ca, "status", "?")
        active_marker = " ← ACTIVE" if status == "ACTIVE" else ""
        print(f"  {slug:18} status={status:10} id={ca.id}{active_marker}")

    print(f"\nLocal DB integrations rows ({len(local_rows)}):")
    if not local_rows:
        print("  (none)")
    for r in local_rows:
        active_marker = " ← CONNECTED" if r.status == "connected" else ""
        print(
            f"  {r.provider}_{r.product:12} status={r.status:10} "
            f"conn_id={r.composio_connection_id}{active_marker}"
        )


async def disconnect(
    user_id: str, provider: str | None, confirm: bool, status_only: bool
) -> None:
    composio_items = await _list_composio_accounts(user_id)
    local_rows = await _list_local_rows(user_id, provider)

    if status_only:
        _print_state(composio_items, local_rows, "CURRENT STATE (status-only mode)")
        print(f"\nuser_id={user_id}: nothing changed.")
        return

    _print_state(composio_items, local_rows, "WOULD DELETE")

    active_composio = [
        ca for ca in composio_items
        if (getattr(ca, "status", None) or "").upper() == "ACTIVE"
    ]
    connected_local = [r for r in local_rows if r.status == "connected"]

    if not confirm:
        print(
            "\nDRY-RUN. Re-run with --confirm to actually delete the above."
        )
        if active_composio or connected_local:
            print(
                f"WARNING: {len(active_composio)} ACTIVE Composio account(s) "
                f"and {len(connected_local)} CONNECTED local row(s) would be "
                "wiped — make sure that's intended."
            )
        return

    if active_composio or connected_local:
        print(
            f"\n!! Deleting {len(active_composio)} ACTIVE Composio account(s) "
            f"and {len(connected_local)} CONNECTED local row(s) !!"
        )

    composio = Composio()
    composio_count = 0
    for ca in composio_items:
        try:
            composio.connected_accounts.delete(nanoid=ca.id)
            slug = getattr(getattr(ca, "toolkit", None), "slug", "?")
            print(f"  composio: deleted {ca.id} ({slug})")
            composio_count += 1
        except Exception as exc:
            print(f"  composio: failed to delete {ca.id}: {exc}")

    async with async_session() as s:
        stmt = delete(Integration).where(Integration.user_id == user_id)
        if provider:
            stmt = stmt.where(Integration.provider == provider)
        result = await s.execute(stmt)
        await s.commit()
        print(f"  db: deleted {result.rowcount} integration rows")

    print(
        f"\ndone. user_id={user_id}: deleted {composio_count} composio "
        f"accounts + {result.rowcount} local rows."
    )


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--user-id", required=True)
    p.add_argument(
        "--provider",
        default=None,
        help="Optional: scope local DB delete to one provider (e.g. google)",
    )
    p.add_argument(
        "--confirm",
        action="store_true",
        help="REQUIRED to actually delete. Without this flag the script "
             "runs in dry-run mode and only prints what would be removed.",
    )
    p.add_argument(
        "--status-only",
        action="store_true",
        help="Just print current state and exit. No deletes, no Composio "
             "writes. Safe to run any time.",
    )
    args = p.parse_args()
    if args.status_only and args.confirm:
        print("ERROR: --status-only and --confirm are mutually exclusive.")
        return 2
    asyncio.run(
        disconnect(args.user_id, args.provider, args.confirm, args.status_only)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
