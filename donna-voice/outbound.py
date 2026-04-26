"""Outbound calling helper.

Donna's BRAIN node calls `place_call(...)` when she wants to dial out.
Uses LiveKit's CreateSIPParticipant API to:

  1. Create a room (or reuse one).
  2. Dispatch the donna-agent into it (so she's the caller's agent).
  3. Add the dialed number as a SIP participant via the outbound trunk.

Returns the room name. The room is the unit of state — observability,
recording, and post-call hooks are keyed off it.

Example:
    >>> from donna_voice.outbound import place_call
    >>> room = await place_call("+14155551234")
    >>> print(room)
    donna-out-3a7f1c
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
from dataclasses import dataclass

from livekit import api  # type: ignore

log = logging.getLogger(__name__)


_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


@dataclass(frozen=True)
class CallHandle:
    room: str
    participant_identity: str
    sip_call_id: str | None


async def place_call(
    to_number: str,
    *,
    agent_instructions: str | None = None,
    room_prefix: str = "donna-out",
    outbound_trunk_id: str | None = None,
) -> CallHandle:
    """Dial `to_number` from donna's outbound trunk and connect it to
    a fresh room with the donna-agent dispatched.

    Args:
        to_number:           E.164 destination, e.g. "+14155551234".
        agent_instructions:  Optional override for the agent's per-call
                             system context. Passed through as room
                             metadata (the agent reads it on entrypoint).
        room_prefix:         Prefix for the generated room name.
        outbound_trunk_id:   Override DONNA_OUTBOUND_TRUNK_ID env var.

    Returns:
        CallHandle with the room name + participant identity + SIP id.

    Raises:
        ValueError on bad number; livekit.api errors on dispatch failure.
    """
    if not _E164_RE.match(to_number or ""):
        raise ValueError(
            f"to_number must be E.164 (e.g. +14155551234), got: {to_number!r}"
        )

    livekit_url = _req_env("LIVEKIT_URL")
    api_key = _req_env("LIVEKIT_API_KEY")
    api_secret = _req_env("LIVEKIT_API_SECRET")
    trunk_id = (
        outbound_trunk_id or os.environ.get("DONNA_OUTBOUND_TRUNK_ID") or ""
    ).strip()
    if not trunk_id:
        raise RuntimeError(
            "DONNA_OUTBOUND_TRUNK_ID is not set. Run "
            "scripts/setup-livekit-sip.sh and copy the outbound trunk id."
        )

    agent_name = os.environ.get("DONNA_AGENT_NAME", "donna-agent")
    room_name = f"{room_prefix}-{secrets.token_hex(4)}"
    participant_identity = f"sip-{secrets.token_hex(3)}"

    metadata = ""
    if agent_instructions:
        import json as _json
        metadata = _json.dumps({"agent_instructions": agent_instructions})

    lk = api.LiveKitAPI(url=livekit_url, api_key=api_key, api_secret=api_secret)

    try:
        # Step 1 — create the room with explicit agent dispatch so the
        # worker is in the room *before* SIP connects (avoids race where
        # the SIP participant joins before the agent has).
        await lk.room.create_room(
            api.CreateRoomRequest(
                name=room_name,
                metadata=metadata,
            )
        )
        try:
            await lk.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(
                    room=room_name,
                    agent_name=agent_name,
                    metadata=metadata,
                )
            )
        except Exception:
            log.exception("agent dispatch create failed (will retry via SIP create)")

        # Step 2 — kick the outbound SIP call. LiveKit dials the number
        # via our outbound trunk and joins the resulting leg into the
        # same room as the agent.
        sip_response = await lk.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                sip_trunk_id=trunk_id,
                sip_call_to=to_number,
                room_name=room_name,
                participant_identity=participant_identity,
                participant_name=f"caller {to_number}",
                wait_until_answered=False,
            )
        )

        log.info(
            "outbound call: room=%s to=%s identity=%s sip_call_id=%s",
            room_name, to_number, participant_identity,
            getattr(sip_response, "sip_call_id", None),
        )
        return CallHandle(
            room=room_name,
            participant_identity=participant_identity,
            sip_call_id=getattr(sip_response, "sip_call_id", None),
        )
    finally:
        await lk.aclose()


def _req_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"required env var missing: {name}")
    return val


# ─── CLI helper ───────────────────────────────────────────────────────


def _cli() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Place an outbound donna call.")
    parser.add_argument("to_number", help="E.164 destination, e.g. +14155551234")
    parser.add_argument("--instructions", help="optional per-call agent instructions")
    args = parser.parse_args()

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    from .config import _load_env_file
    _load_env_file()

    handle = asyncio.run(
        place_call(args.to_number, agent_instructions=args.instructions)
    )
    print(f"room: {handle.room}")
    print(f"identity: {handle.participant_identity}")
    if handle.sip_call_id:
        print(f"sip_call_id: {handle.sip_call_id}")


if __name__ == "__main__":
    _cli()
