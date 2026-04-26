# donna-voice

LiveKit voice agent for Donna. Inbound + outbound PSTN via Twilio
Elastic SIP. Sonnet 4 over LiteLLM, Deepgram STT, Cartesia TTS,
Supabase call logs.

## Topology

```
caller phone
   ↓ PSTN
Twilio elastic sip trunk
   ↓ origination URI (sip:<project>.sip.livekit.cloud;transport=tls)
LiveKit Cloud SIP gateway
   ↓ dispatch rule (donna-call-* room, agent_name=donna-agent)
donna-voice worker (this package)
   ├── deepgram nova-3 STT
   ├── litellm proxy → claude sonnet 4
   ├── cartesia sonic-2 TTS
   ├── supabase voice_calls (start row → patch on end)
   └── BRAIN_HOOK_URL → /voice/post-call (phase 2: memory + WA recap)
```

## Setup order — first deploy

1. **Provision Twilio Elastic SIP**
   - Already done. Number `+14154232657`. Termination URI
     `donna-pstn.pstn.twilio.com`. Auth user `donna_livekit`.
2. **Fill env**
   ```
   cp donna-voice/.env.example donna-voice/.env
   # paste LIVEKIT_*, DEEPGRAM_API_KEY, CARTESIA_API_KEY,
   #       LITELLM_*, SUPABASE_*, TWILIO_SIP_PASSWORD
   ```
3. **Run the LiveKit SIP setup script**
   ```
   set -a; source donna-voice/.env; set +a
   ./donna-voice/scripts/setup-livekit-sip.sh
   ```
   Script is idempotent. Prints inbound trunk id, outbound trunk id,
   dispatch rule id, and the SIP URI to paste into Twilio.
4. **Paste SIP URI into Twilio**
   - console.twilio.com → Elastic SIP Trunking → Trunks → `donna`
   - Origination tab → Origination URI:
     `sip:<project>.sip.livekit.cloud;transport=tls`
5. **Deploy the agent worker to Railway**
   ```
   railway up
   ```
   The Dockerfile builds the worker. Healthcheck is `/health` on `$HEALTH_PORT`.

## Local dev

```
cd donna-voice
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

set -a; source .env; set +a
python -m donna_voice.agent dev
```

Agent registers with LiveKit Cloud and waits for dispatches. Test by
calling the Twilio number — the agent picks up, says
"Donna. What do you need?", and you can talk to her.

> Run from the **donna repo root** so `donna_voice` is importable as a
> package. The `dev` mode auto-reloads on file edits.

## Test inbound

Call `+14154232657` from a phone. Agent picks up. Watch logs:

- LiveKit Cloud dashboard → Rooms → live room `donna-call-…` shows
  the agent + caller participants.
- Local agent log shows `call start: id=donna-call-… direction=inbound`.
- Supabase `voice_calls` table gets a row.

## Test outbound

```python
import asyncio
from donna_voice.outbound import place_call

async def main():
    handle = await place_call("+14155551234")
    print(handle.room, handle.sip_call_id)

asyncio.run(main())
```

Or from the shell:

```
python -m donna_voice.outbound +14155551234
```

The brain calls `place_call` from its tool surface (phase 2 wiring).

## Phase 2 — brain integration

Today the agent runs LiteLLM as the LLM with a fixed Donna persona
prompt. Phase 2 routes per-turn LLM calls through donna's BRAIN node
so memory + tool calls flow:

1. Set `BRAIN_HOOK_URL` and `VOICE_BRAIN_SECRET` in `.env`.
2. The agent already fires:
   - `notify_call_start` → `POST {BRAIN_HOOK_URL}/voice/events`
   - `notify_call_end`   → `POST {BRAIN_HOOK_URL}/voice/post-call`
3. The donna API (this repo's `api/voice_routes.py`) handles those
   today. Post-call extracts commitments, schedules anything promised,
   sends WhatsApp recap.

Per-turn brain integration (replacing the LiteLLM passthrough) lands
in phase 2.5 — the agent will swap `openai.LLM` for a custom adapter
that hits the donna API's `/voice/chat/completions` endpoint.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Twilio call → silence | Agent not registered. | Agent worker logs should show `registered worker {"agent_name":"donna-agent"}`. Restart the worker. |
| Twilio call → SIP 503 | LiveKit didn't dispatch. | Confirm dispatch rule references the inbound trunk id. Re-run setup script. |
| Hears "Donna. What do you need?" then dead air | Cartesia/Deepgram key invalid. | Check `donna-voice/.env`. |
| `503 model not found` | LiteLLM model alias mismatch. | Set `LITELLM_MODEL` to whatever your proxy maps to Sonnet 4. |
| `outbound trunk id is not set` | `setup-livekit-sip.sh` wasn't run, or env not exported. | Run script, copy printed `outbound trunk: ST_…` into `DONNA_OUTBOUND_TRUNK_ID`. |
| Twilio outbound → 401 | SIP password mismatch. | Re-check `TWILIO_SIP_PASSWORD`, re-run setup script. |

## Files

```
donna-voice/
├── agent.py            ← LiveKit worker entrypoint
├── outbound.py         ← place_call helper for the brain
├── brain_hook.py       ← phase-2 hooks (call_start, post_call)
├── supabase_log.py     ← voice_calls table writer
├── config.py           ← env loader
├── trunks/
│   ├── inbound-trunk.json
│   ├── outbound-trunk.json
│   └── dispatch-rule.json
├── scripts/
│   └── setup-livekit-sip.sh
├── Dockerfile
├── railway.toml
├── requirements.txt
└── .env.example
```

## What's deferred

- **Per-turn brain integration** (use donna's BRAIN node as the LLM
  instead of LiteLLM passthrough). Phase 2.5.
- **Recording / call audio archive.** Cheap to enable later via
  LiveKit egress.
- **Speaker identity verification.** Useful when multiple humans share
  one number.
- **Streaming transcript export to Supabase.** Today we summarize on
  close; live streaming is a 10-line addition once needed.
