"""donna-voice — LiveKit voice agent for Donna.

Phase 1 surface: Twilio Elastic SIP → LiveKit Cloud → donna-agent worker
→ Deepgram STT, LiteLLM-proxied Sonnet 4, Cartesia TTS.

Phase 2 surface: brain_hook.notify_call_end fires the post-call brain
which writes memory and posts WhatsApp follow-ups.
"""
