# Audit · 17 · Day 1

## What's there

Day 1 is the first 60 seconds a user has with Donna. Two surfaces: WhatsApp (the actual product) and the dashboard website (the legible counterpart).

**Discovery → first contact.** There is no marketing site. `dashboard/web/app/auth/signin/page.tsx:39` is the public-facing front door. It renders a paper-toned editorial card titled "hi. i'm donna." with one CTA: `wa.me/<number>?text=send%20my%20dashboard` (built at line 17). A secondary line offers an OTP path (`/auth/otp`). This is also the page the middleware redirects unauthenticated users to.

**Inbound WhatsApp message.** Hits `api/composio_webhook.py` (HMAC-verified Composio webhook). Ingress preprocessing happens in `ingress/node.py` and `ingress/payload.py`. Then `api/graph.py:state_from_payload` (line 42) builds the brain state and `user_lookup` (line 74) resolves phone → user_id. If the phone is new, it CREATEs a `User` row with a guessed timezone (line 84-105) — `+91` → `Asia/Kolkata`, `+1` → LA, fallback `Asia/Singapore`. `is_first_message` is set True (line 105) and stamped onto state at line 124.

**The first turn.** The brain's per-turn context starts with `first_message: True/False` (`donna_runtime/context_builder.py:558`). The system prompt at `donna_runtime/prompt.py:220-222` tells the model: *"On a first message, in the same turn, before send_burst, you MUST call send_dashboard_link(reason='first_message'). Then weave the returned URL into your send_burst reply naturally."* The `send_dashboard_link` tool (`donna_runtime/tools.py:2356`) mints a 5-minute magic-link token via `backend/auth/tokens.make_magic_token` and returns the URL.

**Auth on the website.** Two paths.
1. **Magic link** — `dashboard/web/app/auth/magic/route.ts:15` GET handler exchanges `?t=<token>` against `POST /api/auth/redeem-magic` (`api/auth_routes.py:76`). On success, the backend issues a 5-minute session cookie. The route then 302s to `/`.
2. **OTP** — `dashboard/web/app/auth/otp/page.tsx:18` posts phone+code to `/api/auth/verify-otp` (`api/auth_routes.py:104`). 24-hour session on success. The OTP itself comes from a separate flow where the user texts Donna asking for a code; `donna_runtime/tools.py` has a `send_login_otp` tool that puts the 6-digit code in the WhatsApp burst.

**Session refresh.** `/api/auth/whoami` (`api/auth_routes.py:138`) refreshes the cookie on every page load with a rolling 30-day window. Once you're in, you stay in.

**First dashboard.** The `/` page (`dashboard/web/app/page.tsx:38`) calls `resolveUserId()`, then fetches `/api/dashboard/{user_id}/manifest`. If 404 (which a brand-new user *will* get — there is no auto-bootstrap manifest), the empty state at line 178 reads: "your dashboard is being composed. text donna with 'redo my dashboard' and she'll assemble one for the moment you're in."

**Profile editor on the website.** None. The admin dashboard at `/admin/[user_id]/*` is a staff inspector (read-mostly), not a user-facing profile editor. There is no `/settings`, no `/profile`, no UI to set name / TZ / preferences. Everything is chat-driven.

**DAY1_ENABLED.** The flag is in production env (referenced in the prompt brief). I could not find it referenced in the Python or TypeScript source. Either it gates something at the platform level (Composio routing? Vercel preview?) or it's vestigial. If it's gating the codebase, the gate isn't in the repo.

## What works

- The path **WhatsApp signin → magic link → dashboard** is wired and tested. Cookies forward correctly via the Next route handler. Sessions roll. Logout clears.
- The first-message branch is encoded in the brain prompt, not in a deterministic pipeline — that's correct per CLAUDE.md ("every capability is a tool"). Donna emits the link inline, in her voice.
- New-user creation is automatic, idempotent, and stamps a sensible timezone guess. `onboarding_goals` JSON tracks what's been done (`tz_done`, `watch_done`).
- The signin page is genuinely well-written. The voice is right — "your personal assistant on whatsapp. i remember what you share, hold threads, notice what's becoming important, and reach out before things slip." Lowercase, blunt, no em dashes.
- The OTP fallback is a real escape hatch when magic links fail (corporate proxies, link previews chewing tokens, expired-before-tap).

## What's broken / missing

- **The first dashboard a new user sees is an empty state telling them to text Donna again.** They just texted her. They got a link. They tapped the link. They land on `/`. Manifest is 404 because Donna's first turn doesn't call `update_dashboard`. The empty-state copy says "text donna with 'redo my dashboard'." That's a dead loop.
- **No bootstrap fixture for new users.** A welcome plan — even a static one with intro + thesis + footer that says "we just met. tell me one thing you're holding right now." — would close the loop. Today: cold 404.
- **First-message instruction relies on the model.** `prompt.py:222` says "you MUST call send_dashboard_link." If the model doesn't, nothing falls back. There's no deterministic post-turn hook that mints the link if the brain forgot. Should be a hook, not a vibe.
- **No landing page.** The signin page IS the landing page. Anyone visiting `dashboard.donna.app` with no cookie sees "hi. i'm donna." That's brave but also fragile — there's no story, no screenshots, no proof, no "what is this." Press a journalist hits this: there's nothing to look at. Compare: the `/moments` page (which is gorgeous) is undocumented and behind no link from `/`.
- **No profile editor.** A user who wants to fix their name from the WhatsApp `profile_name` Composio sent (often wrong, often "Mom" or the carrier name) has to text Donna and hope she stores it correctly. They can't go to `/profile` and type their name. Same for timezone — guessed from `+<cc>` prefix and never user-confirmed in UI.
- **No welcome flow on WhatsApp.** There is no scripted first-turn (no "hi, i'm donna, here are three things i can do"). The brain just freestyles based on the prompt. That's faithful to the architecture, but in practice the first reply is whatever the model does with `first_message=True`, which is highly variable. Sometimes brilliant, sometimes terse, sometimes performs the long onboarding speech the prompt explicitly forbids.
- **No phone verification.** A user creates an account just by texting Donna. The phone number is the user_id. There's no SMS confirm, no "is this really you" step. For a personal-memory product this is actually fine — WhatsApp itself verified the number — but it means anyone with access to your WhatsApp account has Donna.
- **OTP flow has a chicken-and-egg.** To use OTP you need to text Donna for a code. To text Donna you need WhatsApp. If WhatsApp is broken, the OTP doesn't help. The "magic link broken / give me a code" recovery path is only useful when magic links specifically fail.
- **`DAY1_ENABLED=true` in prod env, no code reference.** Either dead config or platform-level routing. Either way it should be documented or removed.
- **No data-handoff in the website.** A user who arrives via magic link with zero history sees an empty dashboard. There's no "tell me about yourself" form, no integrations connect grid, no "set your morning time" picker. Everything has to happen via chat. The website is read-only for the user.

## Day 1 as the user feels it

Best case: user finds Donna's number somehow (we don't know how — there's no marketing site). They text "send my dashboard." Within a few seconds they get back a warm one-liner from Donna with a link. They tap it on their phone, browser opens, the cookie is set, they land on `/`. Empty state. They read "your dashboard is being composed." They wait. They scroll. Nothing happens. They go back to WhatsApp. They text "redo my dashboard." Donna calls `update_dashboard`. ~10-30 seconds later (Sonnet 4.6 + 6000 tokens) the dashboard polls and a real plan appears. *Now* they see it.

So Day 1 is: text → link → wait → empty page → text again → wait → real page. **Three steps too many.** The first link should land on a real dashboard.

Worst case: link expires before they tap (5 minutes is tight on iMessage previews and corporate inboxes). They land on `/auth/expired`, told to "text donna for a fresh link." Back to WhatsApp. They text. They get a new link. Same problem can recur.

## Opinion vs vision

CLAUDE.md says Donna is a thinking partner with persistent memory and a legible dashboard, blunt, high-agency, lowercase. The voice on `/auth/signin` matches this exactly. The first-turn prompt is faithful. So Day 1 *speaks* like the product.

But Day 1 *behaves* like a developer demo. The first dashboard a real user sees is an empty state that tells them to go re-do something they just did. The website has zero ability to set anything. The landing page assumes you already know what Donna is. There is no proof on the page that Donna can do anything — just a CTA to WhatsApp.

The smallest change that would make Day 1 feel intentional: **a real first-dashboard fixture.** When `is_first_message=True` and a manifest is requested for the first time, compose synthesizes (or even hard-codes) a welcome plan: a hero greeting with the user's name, one thesis ("tell me one thing you're holding"), and a footer ("i'll be here when you reply"). Donna's chat reply should reference what's on the dashboard. The user opens the link and sees Donna already paying attention. Three lines, on a page, in her voice, with their name. That's the moment that decides whether Day 2 happens.

Second: a deterministic post-turn hook on first_message that mints the magic link if the brain forgot. The prompt says "MUST" — make it true. Belt and braces.

Third: kill the empty-state instruction to "text donna with 'redo my dashboard'." Replace with the welcome fixture. Or, if 404, render the static welcome plan client-side.

## Verdict

**Day 1 plumbing is real, Day 1 product is missing.** Auth works, first-message detection works, magic links work, the brain is told to issue them, the website knows how to redeem them. But the experience the user actually gets is: text-link-wait-empty-text-wait-page. The dashboard says "your dashboard is being composed" while nothing composes it. There is no welcome fixture, no profile editor, no landing story, no deterministic fallback if the brain skips the link. Worth a focused week: one welcome plan, one post-turn hook, one /onboarding sub-route for name+TZ+integrations, one paragraph on `/auth/signin` that says what Donna is to people who don't already know. Until then, Day 1 dies on a 404.
