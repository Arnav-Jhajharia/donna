# Audit 11 — Ingestion (Documents, Voice, Text, Images)

Donna lives on WhatsApp. WhatsApp is voice-notes-and-photos territory. This audit covers everything that comes in that isn't plain text.

## What's there

### Voice in (WhatsApp voice note → text)

- `ingress/node.py:155-171` (`_maybe_transcribe`) — fires when the inbound payload carries `voice` bytes. Calls `ingress/stt.py:transcribe_voice`.
- `ingress/stt.py:25-91` — POSTs ogg/opus to Deepgram `/v1/listen` with `smart_format`, `punctuate`, `detect_language`. Default model from `settings.deepgram_model`. 12s timeout. Returns empty string on failure (the brain then asks the user to text).
- The transcript replaces `raw_input`. A separate flag `_inbound_modality="voice"` tells the brain the message arrived as voice — used for tone/voice-reply heuristics later.

### Voice out (text → ElevenLabs → WhatsApp audio)

- `donna_runtime/voice_synth.py` — ElevenLabs Flash v2.5 (`opus_48000_32`), 15s timeout. Reads the outbound buffer, looks for a `VoiceResponseMarker` sentinel. When present (or when the user explicitly asked for voice via `voice_intent.py`), concatenates the burst's text bodies, synthesizes one ogg/opus voice note, uploads to WhatsApp `/media`, replaces the buffer with one `AudioMessage(voice=True)`.
- `donna_runtime/voice_intent.py:14-32` — explicit substring detection for "voice me", "send a vm", "audio reply", etc. Belt-and-suspenders so an explicit ask still synthesizes even if the model forgot the marker.
- LiveKit live-call path: `donna_runtime/voice_synth.py:41-43` and `donna-voice/agent.py` — separate worker package, runs as its own Railway service. STT Deepgram nova-3, LLM Sonnet via LiteLLM proxy, TTS Cartesia Sonic-2. Logs to Supabase `voice_calls`. Notifies the brain via `brain_hook.notify_call_start` / `notify_call_end`.
- All failure modes degrade silently to text — the marker is stripped and the original burst delivers as text.

### Documents in (user attaches a PDF/file)

- `ingress/node.py:58-110` — `_maybe_dispatch_attachment_ingest` fires deep ingest as a **background task** (`asyncio.create_task`). The brain turn is not blocked.
- `backend/memory/ingest/documents.py` — orchestrator. Pipeline:
  1. SHA-256 the bytes; idempotency check via `Observation` rows of type `document_received` (`documents.py:275-295`).
  2. Pick extractor (PDF / image) at `documents.py:157-175`.
  3. Sliding-window chunk on character boundaries (`documents.py:181-209`) — 1800 chars target, 200 overlap, max 50 chunks.
  4. Persist chunks to **Supermemory** via `add_episode` with rich metadata (sha256, filename, title, mime_type, page_count, chunk_index, kind=`document_chunk`).
  5. Log one summary `Observation` of type `document_received` (so it surfaces in TODAY block + temporal context).
  6. Push summary to **Graphiti** via `ingest_episode` so entity extraction picks up names/dates.
- PDF extractor (`backend/memory/ingest/extractors/pdf.py`) — `pypdf`, max 50 pages. Scanned/image-only PDFs return empty (no OCR fallback).
- Recall: `backend/memory/tools/recall_document_chunks.py` searches Supermemory chunks with optional `doc_id` scope.

### Images in (user sends a photo)

- `backend/memory/ingest/extractors/image.py` — Claude **Haiku 4.5 vision**, one round-trip, 25s timeout. Prompt asks for two sections: `CAPTION` (lowercase, 2-4 sentences) and `VISIBLE TEXT` (line by line, OCR). Output is parsed by `_split_sections`.
- The caption + visible text become a single `ExtractedDocument` and run through the same chunking + Supermemory + Graphiti pipeline as documents.
- WhatsApp images sometimes arrive with weird mimes (`application/octet-stream`); extractor defaults to `image/jpeg`.

### Image generation out (the `image` tool)

- `donna_runtime/tools.py:1255-1314` (the tool) → `donna_runtime/image_client.py:generate_and_upload` → fal.ai **Flux 1.1 Pro** (`donna_runtime/config.py:IMAGE_MODEL`).
- Flow: fal generate → CDN URL → `httpx` download → WhatsApp `/media` upload → return `media_id` for `send_burst`.
- Caps enforced by `backend/memory/tools/image_caps.py`: 6h cooldown, 3/week cap, one-image-per-turn ever. Stored in `image_tool_events` Postgres table. Pre-tool hook checks; post-tool hook records.
- A separate `backend/illustration/generate.py` uses fal's **Recraft v3** for the dashboard's Day 1 illustration — different surface, returns the bare CDN URL (no WhatsApp upload).

### Text in

- The canonical path. WhatsApp body lands in `raw_input`, ingress enriches with reply context, URL excerpts (`_fetch_urls` — up to 3, `BeautifulSoup` strip, 2000-char excerpts), then off to the BRAIN loop.

### Email in (related but separate)

- `backend/memory/tools/list_gmail_recent.py` — pull-on-demand, not push. Donna asks Gmail when she needs to. Not part of the WhatsApp ingest pipeline.

## What works

- **Voice in is fast and clean.** Deepgram STT → text → normal turn. The `_inbound_modality="voice"` flag is the right way to thread tone hints without polluting the prompt.
- **Voice out has the right shape.** Marker-driven, fail-safe to text, 6 second-or-so latency budget. The `voice_intent.py` belt is the kind of pragmatism this codebase needs more of.
- **Document ingest is genuinely well-designed.** Idempotent on SHA-256. Background task so brain isn't blocked. Three writes: Supermemory chunks (for content recall), Postgres Observation (for "I sent you a doc on Monday" recall), Graphiti episode (for entity edges). Best-effort everywhere — one failure doesn't drop the file silently.
- **Image extraction is the same shape.** Haiku vision = caption + OCR in one round-trip. Cheap. The two-section parser is tolerant of small format drift.
- **Image generation has hard caps wired in.** 6h cooldown + 3/week cap is the kind of cost discipline the rest of the codebase preaches.

## What's broken or missing

- **No OCR fallback for scanned PDFs.** `pdf.py:1-7` admits it: scanned/image-only PDFs return empty text. Many user-shipped PDFs (receipts, contracts, lecture notes) are scanned. The orchestrator falls back to logging a `document_received` row with no chunks — recall by filename works, full-text doesn't. For an iPhone-native partner this is table-stakes-missing.
- **Image extractor uses Haiku, not Sonnet, and is silent about it.** Haiku 4.5 vision is fine for captions but weaker on screenshot text density (long screenshots of code, dense receipts). No tier-up path. Single attempt, no retry on partial output.
- **Document chunking is character-window, not semantic.** Comment at `documents.py:181-187` is honest — "within 10% of optimal." Fine for prose, weaker for slide decks (heavy headers, tables, code blocks). No layout awareness.
- **No file-size cap visible in `documents.py`.** A 200MB scanned PDF would still try to extract. `pdf.py` caps at 50 pages but doesn't reject by byte size before reading. R2 storage env vars are set in prod (per the prompt) but I see no R2 client code in the repo — files live in WhatsApp media + Supermemory + Postgres summaries only.
- **Voice notes do not feed the document pipeline.** `documents.py:11` says voice is intentionally skipped because STT already routed it to text. So a 12-minute voice note becomes one `raw_input` blob with no chunking, no `document_received` observation, no Supermemory persistence beyond the chat row. A user who voice-notes a brain-dump cannot later say "find the part about the founder I mentioned in my voice note last Tuesday."
- **No multimodal-native recall path.** The image extractor stores caption+OCR as text. If a user asks "find the photo of the whiteboard from the meeting" Donna searches text, not image embeddings. No CLIP, no Gemini multimodal embed, no image vector index.
- **R2 not actually used in code.** `R2_*` env vars are set in prod but `grep -rn "R2\|cloudflare" --include="*.py"` finds zero matches in the relevant directories. So either it's a planned future or another service handles it. Currently media lives in WhatsApp's CDN (24h-ish expiry per Meta) and chunks in Supermemory.
- **Voice synth has no per-user toggle visible at the user level.** Global `DONNA_VOICE_ENABLED` flag, that's it. Some users want voice-always, some never. No persistence of preference.
- **`donna-voice/` is a separate package shipped as a separate Railway service.** That's the right architecture, but the boundary is thin — `brain_hook.py` calls back into the main brain. Failure modes between the two services are not well documented.

## Opinion vs Donna's vision

Donna is sold as WhatsApp-native and iPhone-natural. iPhone-natural means: I voice-note you a chaotic 8-minute thought-dump while walking, you remember the three things that mattered, and tomorrow you bring one of them back without me re-explaining. I send you a photo of a whiteboard, you can answer questions about it next week.

Voice-in is solid. Photo-in is solid for one round-trip ("what does this say"). Document-in is solid for text PDFs. Voice-out is solid as a sometimes-thing.

But the stitch is loose. A voice note is treated as text-that-arrived-via-voice — once the transcript exists, the original audio and its richer signals (tone, pauses, "ums") are gone. A photo is treated as caption-text-plus-OCR — visual recall is reduced to whatever Haiku said in two sentences. A scanned PDF is treated as a filename. So the persistent-memory promise has a hole shaped like "anything the user actually wanted preserved beyond text."

What's missing for table-stakes:
1. **OCR fallback for scanned PDFs** (Tesseract or Vision API on page images).
2. **Voice-note chunking + persistence** so long voice brain-dumps become recallable documents, not just one chat row.
3. **Image embeddings** so "the whiteboard photo" works.
4. **Tier-up to Sonnet vision for dense screenshots** (or at least retry-with-better-model on low-confidence captions).
5. **Per-user voice preference** — at minimum a "always voice" / "never voice" toggle stored on the user.

What's nice-to-have but feels later:
- Audio fingerprinting (Donna recognizing the same speaker across voice notes).
- Live photo / video ingest.
- Native PDF layout understanding for tables and figures.

## Verdict

Multimodal ingestion is **bolted on, but the bolts are the right ones**. The design instincts are correct (background tasks, idempotency, three-write fanout, cap-based safety). The implementation is honest about its limits (the comments in `pdf.py` and `documents.py` admit the gaps cleanly).

But "first-class" it isn't. A user sending a scanned receipt or a 10-minute voice memo gets degraded behavior they'll notice. For a thinking partner who promises persistent memory on WhatsApp, the missing pieces are not exotic — OCR, voice-note-as-document, image embeddings — they're three weeks of work each and they would close the gap to "actually iPhone-native." Ship the current state as v1; the next sprint should pick one of those three before any new features.
