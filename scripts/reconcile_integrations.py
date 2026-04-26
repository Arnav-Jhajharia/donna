"""On-demand reconcile of users.integrations against Composio's truth.

Used while the live webhook handler doesn't recognize Composio V3 events.
Queries Composio for a user's connected accounts and updates the local
integrations table to match. Idempotent.

Usage:
  python scripts/reconcile_integrations.py --user-id <user_id>
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

from backend.integrations import state  # noqa: E402

_TOOLKIT_TO_PRODUCT = {
    "gmail": "gmail",
    "googlecalendar": "calendar",
}


async def reconcile_user(user_id: str) -> None:
    composio = Composio()
    result = composio.connected_accounts.list(user_ids=[user_id])
    items = result.items if hasattr(result, "items") else list(result)
    if not items:
        print(f"composio: no connected accounts for user_id={user_id}")
        return

    for ca in items:
        toolkit_slug = getattr(getattr(ca, "toolkit", None), "slug", None)
        product = _TOOLKIT_TO_PRODUCT.get((toolkit_slug or "").lower())
        ca_status = (getattr(ca, "status", None) or "").upper()
        ca_id = getattr(ca, "id", None)
        if not product or not ca_id:
            print(f"  skip: id={ca_id} toolkit={toolkit_slug} (unmapped)")
            continue

        local = await state.get_integration_status(user_id, "google", product)
        local_status = local.status if local else "absent"

        if ca_status == "ACTIVE":
            if local_status == "connected":
                print(
                    f"  noop: google/{product} already connected "
                    f"(ca={ca_id})"
                )
                continue
            if local_status == "absent":
                await state.upsert_pending(user_id, "google", product)
            await state.mark_connected(
                user_id, "google", product, connection_id=ca_id
            )
            print(
                f"  flip: google/{product} {local_status} → connected "
                f"(ca={ca_id})"
            )
        elif ca_status in ("EXPIRED", "FAILED"):
            await state.mark_revoked(user_id, "google", product)
            print(
                f"  flip: google/{product} {local_status} → revoked "
                f"(ca={ca_id} status={ca_status})"
            )
        else:
            print(
                f"  noop: google/{product} composio={ca_status} "
                f"local={local_status}"
            )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--user-id", required=True)
    args = p.parse_args()
    asyncio.run(reconcile_user(args.user_id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
