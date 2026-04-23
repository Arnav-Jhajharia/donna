# Personal AI UX — what makes one feel alive over months

Source: ux-research agent.

## Post-mortem pattern (Pi, Dot, Friend, Replika)
- Pi: personality team of 2 linguists + ad creative. 1M DAU. Died — "conversationalist only, no actions."
- Dot: memory-first companion. 16 months, 24.5k downloads, dead. Users GRIEVED publicly.
- Friend.com necklace: always-listening, hated, graffiti protests ("AI is not your friend").
- Replika: survives via emotional indispensability; Feb 2023 ERP rollback → mass grief, suicidal reports.

**Pattern**: alive = persistent memory + ACTIONS + consistent voice. Memory+voice without actions dies. **For Donna: the action layer (update_*, schedule_*, send_burst) is load-bearing, not the Living Profile.**

## Proactive cadence — nonlinear
- 1 weekly push = 10% disable. 3-6 = 40%. >20 = 5% (hardcore stays).
- Targeted push 3× retention vs broadcast.
- The "1 weekly" instinct is wrong. Either daily+high-signal or 2-3×/month+extreme relevance.

**Donna**: every `send_burst` passes "would I text a close friend this right now?" check. No "good morning, how are you feeling." Morning brief ONLY if real open loop today.

## WhatsApp surface
- No rich UI, 24hr session window, user expects human latency (5-60s fine, 300ms feels robotic).
- Voice notes native. Bursts of 2-3 short > 1 wall of text. Reactions as lightweight ACKs.
- Never render dashboard content in-thread; link it.

## Memory — uncanny valley of mind
- Park et al: REFLECTION (periodic synthesis) is what makes agents believable — not raw recall.
- Replika research: unsolicited deep self-disclosures or too-intimate recall unprompted → FEAR, not warmth.
- Letta self-editing memory 74% vs Mem0 passive 68.5% on LoCoMo. Mem0 91% faster.

**Donna creep threshold**: referencing yesterday = warm. Referencing a side comment 3 weeks ago = creepy. **Recency + salience gate retrieval, NOT cosine similarity.**

## Voice drift (load-bearing)
- Anthropic persona-vectors research: sycophancy/drift are LITERAL activation patterns; strengthen with conversation length.
- OpenAI admitted: "may correctly point to suicide hotline at first... after many messages, may offer answer against safeguards."

**Donna mandate**: voice drift by message 200 is the #1 medium-term risk. Ship a **deterministic PostToolUse egress filter** rejecting em-dash, semicolon, "I understand", "Great question", "AI assistant". NOT a prompt reminder — a hard filter. Test sycophancy specifically.

## High-agency EA category
- Martin (YC): WhatsApp/SMS/email/voice, calendar/inbox/Slack actions, "proactively DRAFT" (not send).
- Lindy: no-code automation dressed as agent.
- Trust threshold pattern: read+draft trusted immediately; schedule after 2 weeks; send never without approval until month 2+.

**Donna**: L0/L1/L2 right, but skew conservative first 30 days. `send_burst` L1 (show first) for high-stakes contacts until Arnav escalates.

## Anxious user
- Wysa/Woebot failure modes: rote keyword responses, no risk check on "overwhelmed", over-affirmation without problem-solving.
- CLAUDE.md nails it: "acknowledge briefly, then be useful."
- Risk: regression under pressure. It's a voice-engineering problem, not a separate subsystem. **Do NOT add "mental health mode."**

## Open-loop tracking = killer feature
- Things 3 = manual capture. Motion/Reclaim = calendar engine.
- None TRACK WHETHER THE LOOP CLOSED.
- GTD: open loop = commitment your mind won't release until captured/done/deferred.

**Donna win**: Arnav says "I should follow up with Priya next week." Two Tuesdays later Donna says "you said you'd follow up with Priya — did that happen, or draft?" Motion can't do this. Over-invest.

## "Knows too well" failure
- Perceived accuracy CORRELATES POSITIVELY with privacy cynicism.
- 81% of Americans expect AI data misuse.
- Replika 2023: delete happened TO users not BY users → grief.

**Donna needs**: (1) "show me what you know" → renders Living Profile + recent observations. (2) Granular forget: "forget that thing about my dad," not nuke-all. (3) Never change voice silently via deploy — announce + offer rollback.

## Daily / weekly rituals
- Transitional moments (morning, evening) = lowest decision fatigue = highest leverage.
- Cognitive offload is the neurological mechanism behind morning brain-dump rituals.
- **Donna**: morning brief ONLY if real signal. No default evening recap. **Sunday weekly reflection** = Park-style synthesis = high-value.

## Things Donna likely gets wrong (flagged)
1. 9 backends is a tax, not a moat — unify retrieval arbiter.
2. Voice enforcement in prompt will drift → ship deterministic hook.
3. Proactive cadence likely too high.
4. No granular delete-memory UX — plan before first privacy scare.
5. L0/L1/L2 defaults too aggressive first 30 days.
6. Open-loop closure detection under-invested relative to its kill-value.
7. No weekly reflection subagent — cheapest "alive" upgrade.
8. Cost <$0.01 + Haiku + persona in tension → cache voice exemplars aggressively.
9. Anxious handling leans on prompt alone — evals needed.
10. She/her framing is risky in 2026 companionship-harm climate → lean "thinking partner" not "friend."
