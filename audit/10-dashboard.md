# Audit · 10 · Dashboard + proactive dashboard

## What's there

The dashboard is a Next.js app at `dashboard/web/`. Donna composes it with one Sonnet 4.6 call.

**Routes** (`dashboard/web/app/`):
- `page.tsx:20` — the main `/` surface. Resolves user via cookie, polls `/api/dashboard/{user_id}/manifest` every 20s, also opens an SSE channel to `/events`. 404 means "no manifest yet" empty state.
- `auth/signin/page.tsx:27` — paper-toned welcome page with a wa.me CTA "open the whatsapp thread."
- `auth/magic/route.ts:15` — server route that exchanges `?t=<token>` for a session cookie via `/api/auth/redeem-magic`.
- `auth/otp/page.tsx:18` — 6-digit code form fallback (24-hour session).
- `moments/page.tsx:7` — the gallery: 18 showcase plans rendered side by side, fed by `lib/plans/showcase/index.ts`.
- `observe/page.tsx`, `generator/page.tsx`, `expansion/page.tsx` — internal/dev tools.
- `admin/page.tsx` + `admin/[user_id]/{attentions, calendar, chat, email, integrations, memory, proactive, raw, tools, turns}` — staff inspector.

**Renderer** (`dashboard/web/components/DashboardRenderer.tsx:58`): plan-in, JSX-out. Two paths — `rows[]` (visual contract grid via `RowGrid` + `Cell`) and the legacy linear `blocks[]`. The `BlockSwitch` at line 157 dispatches 38 block types: 20 legacy + 18 catalogue archetypes (`c-tracker` through `c-read`).

**Block library** (`dashboard/web/components/blocks/`): every legacy block is its own file (Hero, Thesis, Witness, Confrontation, Celebration, Reflection, OpenLoops, WeatherOfYou, CalendarShape, TodoList, TrackerGrid, NudgeGrid, Permission, Reminders, TrackerStarter, Relationship, NewsBrief, Note, Footer). The 18 catalogue archetypes ported in this branch live in `blocks/catalogue/CatBlocks.tsx` + `CatTracker.tsx` with an icon set in `icons.tsx` and shared atoms in `atoms.tsx`.

**Plan schema** (`dashboard/web/lib/plan.ts:12`): every block type, every `ActionVerb` (16 verbs at line 21), `Row`/`Cell` for row-based layout, `IntroSpec`, validation rules (`validatePlan` line 516 enforces P-H1, P-TH1, P-R1, P-D1, R-C1).

**Composer** (`backend/dashboard/compose.py:477`): pulls user + 5 observations + 5 open loops + 4 offered attentions + 12 live attentions, packs them into a plaintext brief (line 355), hands brief + Pydantic schema to `call_structured` with Sonnet 4.6 and 6000 max tokens. Server overrides id/generatedAt/user post-parse so the LLM can never lie about identity.

**Persistence** (`backend/dashboard/store.py:22`): `INSERT … ON CONFLICT (user_id) DO UPDATE` on `dashboard_manifests`. One row per user, no version history. After upsert it calls `publish_manifest_change(user_id)`.

**SSE** (`backend/dashboard/manifest_events.py:24`): in-process pub/sub. The `/events` endpoint (line 56 in `api/dashboard_routes.py`) holds an open `text/event-stream` per user, sends `manifest_changed` on publish, keep-alives every 25s. Frontend re-fetches the manifest within ~1s.

**Actions** (`backend/dashboard/actions.py`): three verbs wired today — `accept_attention` (line 86, flips OFFERED→LIVE, materializes a `DonnaInstance(primitive=track)` for tally/event_stream cards, fire-and-forgets a recompose at line 130), `dismiss_attention` (line 190), `mark_reminder_done` (line 142, also recomposes). Unknown verbs return 501 (`api/dashboard_routes.py:194`).

## What works

- The whole loop is wired end-to-end: tool call → compose → upsert → SSE → re-fetch → re-render. SSE drops gracefully back to 20s polling.
- The composer prompt is genuinely good — long, opinionated, has worked examples, knows about emotional temperature, knows about offered vs live attentions, refuses to fabricate attention IDs.
- Server-overrides on id/generatedAt/user are the right call. LLM identity drift is impossible.
- `_recompose_after_accept` fires in a background task with a strong-ref set so it doesn't get GC'd. Good defensive code.
- The catalogue port is clean: 18 archetypes, every one has a real fixture in `lib/plans/showcase/index.ts`, the renderer has type-exhaustive switch coverage. `/moments` renders all 18 side by side.

## What's broken / missing

- **No proactive dashboard push.** Recompose-after-accept and update_dashboard tool exist, but Donna has no way to say "look at your dashboard right now" to a user who isn't already on the page. SSE only works if the tab is open. There's no WhatsApp-out hook that says "i refreshed your home — open it." Closest thing is `send_dashboard_link`, which mints a magic link the user has to tap to open in the first place.
- **Morning trigger doesn't recompose the dashboard.** `backend/web/proactive/triggers/morning.py:269` runs `donna_turn` in proactive mode and sends the WhatsApp burst, but never calls `compose_manifest` or `update_dashboard`. The 5am morning ping doesn't refresh the dashboard unless the brain happens to call `update_dashboard` itself.
- **Action verb coverage is thin.** 16 verbs declared in the schema, only 3 implemented (accept, dismiss, mark_reminder_done). `start_tracker`, `complete_pick`, `snooze_reminder`, `connect_integration`, `accept_draft`, `decide_option`, `quick_log`, `open_relationship`, `open_news`, `open_tracker`, `reply_chip`, `log_value` — all 501s today. Catalogue blocks render `c-offer`, `c-pick`, `c-decision`, `c-permission`, `c-quicklog` as if they're tappable, but most taps go nowhere.
- **18 catalogue archetypes, no LLM use.** The composer's system prompt (`backend/dashboard/compose.py:144`) tells the model to use the *legacy* block kinds: `thesis | witness | todo-list | reminders | permission | tracker-grid | footer`. The 18 `c-*` archetypes are not mentioned. So in production, the LLM can't pick `c-watch`, `c-brief`, `c-streak`, `c-confront` etc. They exist in the renderer and on `/moments` but are dead code from the brain's POV.
- **Editorial vs inventory** — the prompt explicitly addresses this and tells the model to edit (compose.py:204 — "you do not have to render all of them"). Good intent. But density budget is 12, and a fully-loaded plan with hero+todo+tracker+reminders+permission already costs ~10. Empirically (judging by scripts/_out/*.json and the fixture density numbers on /moments), the model does pick 3-5 things. So editorial works.
- **Manifest change pubsub is in-process.** `manifest_events.py:11` is honest about it — works for single-pod, dies in multi-pod. Schedule_worker now runs as its own Railway service (per memory note), so a recompose triggered from the worker pod will not notify SSE clients on the API pod. SSE silently no-ops, and the client falls back to 20s poll. Functional but fragile.
- **No "preview" or pre-publish step.** Composer writes straight to the live row. If the LLM emits a bad plan (rare, but Pydantic doesn't catch every wrong-shape), the user sees it on next poll. No staging table, no canary.
- **Image-tool / dashboard preview surface** — couldn't find a wired surface where Donna sends a *preview* image of the dashboard inside WhatsApp. There's an `image` tool but it does ad-hoc image gen, not "snapshot of your home screen." If the goal is "user gets a glimpse in chat then opens the link," that's not built.
- **Empty-state copy** at `app/page.tsx:182` instructs the user to text "redo my dashboard" — fine, but only works if the user has *already authenticated*. A new user with no manifest, no chat history, no integrations sees: "your dashboard is being composed." That's a lie. Nothing is composing until they text Donna.

## Opinion vs vision

Donna's vision: WhatsApp-native AI, dashboard as the legible counterpart. The dashboard is supposed to be where chat goes to rest — a paper-toned point of view on the day, not a feed.

The plumbing is there. The aesthetic intent is there in the showcase plans (the rust accents, the editorial italic, the moss for streaks, the oxblood for confrontation, the density budget that forces selection). When the renderer fires the canonical morning pair (sc02, hero + tracker pair + footer-mark), it actually feels like donna's voice on a page rather than a status dashboard.

What's missing is the **proactive push that makes the dashboard live**. Right now the dashboard is a thing the user *opens*. There's no moment where Donna texts "i refreshed your home — sleep is the only real job tonight" with a link, and the user opens the link to find a hero-only plan that says exactly that. That moment — chat and dashboard pointing at the same thesis at the same instant — is the one feature nobody else has. We have the pieces, but they're not stitched.

The other gap: 18 archetypes the LLM can't reach. We did the design work, ported the components, wrote the fixtures, built `/moments` to show them. Then we shipped a system prompt that limits the LLM to 7 block types. That's a self-inflicted ceiling. Until compose.py knows about `c-watch`, `c-brief`, `c-streak`, `c-confront`, `c-pick`, `c-draft`, `c-offer` etc., the catalogue is a design artifact, not a product surface.

What dashboard moment makes a user say "this is the part Donna does that nobody else does"? Not the daily morning page. Not the trackers. It's the moment Donna recomposes mid-day in response to a chat ("i'm crashing"), texts "i moved everything off your screen — go sleep, watches are still running," and the screen literally turns into a hero + footer with two lines. That is editorial AI in a way no other product has. We have the bones. We don't have the choreography.

## Verdict

**Solid scaffolding, half-finished product.** Composer + renderer + SSE + actions are built well, with care. The 18-archetype catalogue is real design work, faithfully ported, and currently unreachable by the production prompt. Three of sixteen action verbs are wired. The proactive push — the thing that would make the dashboard feel alive instead of pulled — does not exist. Day one for dashboard polish: (1) teach compose.py about the catalogue archetypes, (2) wire the missing action verbs (or at least cut the schema down to what's real), (3) make the morning trigger recompose, (4) build one explicit "look at your dashboard" WhatsApp burst tied to a fresh manifest. Without (4) the dashboard remains a museum of donna's voice instead of a tool she actively uses.
