# Showcase

A single static HTML page that demonstrates every token, every type role, and every Lego block in the Donna design system. No build step. Open `index.html` in a browser. That's it.

## Why this exists

The design system has three forms of documentation:

1. `DESIGN_SYSTEM.md` — the gospel (rules + decision trees)
2. `components.md` — component and block contracts (props + forbidden states)
3. `showcase/index.html` — **this file** — the visual reference

Reading the gospel tells you the rules. Opening this page tells you what the rules produce. When a debate starts about "what does the right amount of rust look like," someone opens this page and the debate ends.

## Running locally

```bash
# From the design-system root
open showcase/index.html
# or
python3 -m http.server 8000
# then visit http://localhost:8000/showcase/
```

Fonts load from Google Fonts at runtime. No npm, no bundler, no framework.

## What's on the page

1. **Palette** — the six core hues + three signals, shown as swatches with hex values
2. **Type scale** — every role from `type-h1` down to `type-caption`, each with a real-copy example
3. **Italic discipline** — the only three places italic exists, demonstrated
4. **Card treatments** — surface-filled and hairline side by side
5. **Buttons + chips** — all three button variants, all four chip states; the primary button is marked as "the rust moment" for the screen
6. **The Lego blocks** — one live example per attention `CardType`:
   - Tally → water (3 glasses, so far today)
   - EventStream → fundraising thread (three rows)
   - Brief → three investors pinged
   - PrepDoc → 1:1 with priya (numbered points + an open question)
   - OpenLoop → call dad (age pill right-aligned)
   - Ping → maya's sister lands (no heading, the quietest block)
7. **The forbidden list** — a hairline card summarizing the top rules

## Keeping this in sync

When you change a token, update this file in the same PR. When you add a block to `components.md`, add a live example here. If the gospel says "italic only in three places" but the showcase shows four, the showcase is wrong — fix it immediately.

## What this page does NOT try to be

- not a pattern library. it's a reference card, not a component kit.
- not responsive to perfection. it works on desktop and on a phone; it's not optimized for every breakpoint.
- not interactive. buttons don't do anything. this is deliberate — we're showing the rest state.
- not a website for donna. the wordmark in the topbar just exists to demonstrate the wordmark. visit somewhere else if you're looking for the product.
