# Vapi + Telnyx wiring — first real call

Goal: dial a `+65` number, hear donna, in under a week. Vapi runs the
voice pipeline; Telnyx provides the SG number; our FastAPI exposes the
brain via `/vapi/chat/completions`.

## Architecture

```
caller phone → Telnyx +65 number → Telnyx SIP trunk
                                       ↓
                              Vapi inbound SIP gateway
                                       ↓
                Vapi (STT + TTS + VAD + turn-taking + barge-in)
                                       ↓
              POST https://<your-host>/vapi/chat/completions
                                       ↓
                   donna_runtime.brain.donna_turn
                                       ↓
                    streamed reply (SSE) → Vapi TTS → user
```

Nothing in `donna_runtime/` changes. The voice surface is a single new
router (`api/vapi_routes.py`) wrapping the existing brain.

## What's already in place

- `api/vapi_routes.py` — custom-LLM webhook + server-events handler.
- `api/main.py` — router mounted at `/vapi/*`.
- `voice/vapi_assistant.json` — assistant config, paste into Vapi dashboard or POST via API.

## Step-by-step

### 1. Public host for the webhook

Vapi must reach your FastAPI over HTTPS. Two options:

- **Already-deployed donna API** — use the existing public URL (Railway/Fly).
- **Local dev** — `ngrok http 8000` and use the ngrok URL.

Note the host. You'll paste it into the assistant JSON twice (`model.url`
and `serverUrl`).

### 2. Generate the shared secret

```
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Set in two places:
- Your server env: `VAPI_WEBHOOK_SECRET=<value>`
- The assistant JSON: replace `serverUrlSecret` with the same value.

Vapi sends this in the `x-vapi-secret` header on every call. Mismatch → 401.

### 3. Vapi account + assistant

1. Sign up at https://dashboard.vapi.ai.
2. Edit `voice/vapi_assistant.json` — replace `YOUR_PUBLIC_HOST` (twice)
   and `REPLACE_WITH_VAPI_WEBHOOK_SECRET`.
3. Create the assistant — either:
   - Dashboard → *Assistants → Create → JSON tab → paste*, OR
   - `curl -X POST https://api.vapi.ai/assistant -H "Authorization: Bearer $VAPI_API_KEY" -H "Content-Type: application/json" -d @voice/vapi_assistant.json`
4. Copy the returned `assistantId`.

### 4. Telnyx `+65` number

1. Sign up at https://portal.telnyx.com.
2. **Mission Control → Numbers → Buy → Country: Singapore → Local**.
   Filter for `+65 3xxx` (virtual local prefix). ~$1/mo.
3. KYC: **Mission Control → Compliance**. Upload company docs +
   director ID. SG approval is 2–5 business days for foreign entities.
4. While KYC processes, test on a **Vapi-issued US number**
   (Dashboard → *Phone Numbers → Buy*) — costs ~$2/mo, no KYC,
   call it from anywhere to validate the brain on Vapi end-to-end.

### 5. SIP trunk: Telnyx → Vapi

Once the SG number is approved:

1. **Telnyx → Voice → SIP Connections → Create**:
   - Type: *FQDN*.
   - FQDN: `sip.vapi.ai` (port 5060, transport UDP).
   - Authentication: Vapi gives you credentials in *Phone Numbers → Import → SIP Trunk*.
2. **Telnyx → Numbers → your `+65` number → Voice Settings**:
   - Connection: the SIP connection from step 1.
3. **Vapi Dashboard → Phone Numbers → Import existing → Telnyx SIP**:
   - Number: `+65...`
   - Assistant: select the donna assistant.
   - Save.

Test: call the number from your mobile. Vapi logs the inbound call,
fires the assistant, hits your webhook within ~500ms.

### 6. Verify the wiring locally first

Without Telnyx, you can validate the webhook surface directly:

```bash
# 1. start the server
uvicorn api.main:app --reload --port 8000

# 2. in another terminal, simulate a Vapi turn
curl -N -X POST http://localhost:8000/vapi/chat/completions \
  -H "Content-Type: application/json" \
  -H "x-vapi-secret: $VAPI_WEBHOOK_SECRET" \
  -d '{
    "model": "donna-voice",
    "messages": [{"role": "user", "content": "remind me to call mum"}],
    "call": {"id": "test-call", "customer": {"number": "+6591234567"}},
    "stream": true
  }'
```

You should see SSE chunks streaming back with donna's reply. If yes,
the brain↔Vapi seam works. Everything past this is account+SIP setup.

### 7. Real call

With KYC done and the trunk live, dial the SG number. You should hear
the `firstMessage` ("hey. you got me. what's up") then a real response
from the brain. End the call → check server logs for the
`end-of-call-report` event.

## Tuning knobs (in `vapi_assistant.json`)

- `transcriber.endpointing` (ms) — silence required before STT
  finalizes. Lower = snappier, more false-finalizes. Try 200–350.
- `responseDelaySeconds` — pause before donna starts speaking after
  STT finalizes. Higher = more "thoughtful" feel. 0.2–0.5 is human.
- `numWordsToInterruptAssistant` — barge-in trigger. 1 = ultra-eager
  (cuts donna mid-syllable on "yeah"), 3 = waits for a phrase.
- `voice.optimizeStreamingLatency` — ElevenLabs latency mode 0–4.
  4 = lowest latency, lowest quality. 3 is the sweet spot.
- `model.maxTokens` — keep low (≤600). Voice replies should be short.

## Cost shape (per inbound minute)

| line item | cost |
|---|---|
| Vapi platform | $0.05 |
| Deepgram nova-3 | ~$0.005 |
| ElevenLabs flash | ~$0.10 |
| Telnyx +65 inbound | ~$0.012 |
| **Total** | **~$0.17/min** |

Plus fixed: Telnyx number $1/mo, Vapi $0/mo (pay-per-use).

## What's deferred

- The 10 voice tricks from `voice_callbot/`. Vapi handles backchannel,
  VAD, interruption, turn-taking with its own (less tunable) versions.
  Keep `voice_callbot/` as the migration target if/when Vapi limits us.
- End-of-call memory writes. The `end-of-call-report` handler logs
  duration only. Wire into post-turn hooks (commitment summarization,
  observation logging) once we hear donna speak first.
- Outbound calls (trick #10). Vapi has an outbound API — implement
  after inbound works.

## Migration off Vapi (when/if)

The brain webhook is reusable. Migration to LiveKit means:
1. Deploy the `voice_callbot/` package (already exists on branch
   `voice-callbot`).
2. Point its `BrainClient` at the same `/vapi/chat/completions`
   endpoint (or a sister endpoint with the same shape).
3. Swap Telnyx SIP trunk from Vapi → LiveKit SIP gateway.
4. Tear down Vapi assistant.

Total: one weekend, no brain changes.
