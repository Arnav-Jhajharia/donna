# DONNA · COMPONENTS

Component contracts. Every prop, every variant, every forbidden state.
If a component you need isn't here, you must add it here in the same PR as the code.

---

## Heading

Serif hierarchy for H1–H3. Sans for H4.

```tsx
<Heading level={1}>Good morning, <Accent>Arnav</Accent>.</Heading>
<Heading level={2}>Today</Heading>
<Heading level={3}>Things you said you'd do</Heading>
<Heading level={4}>This week with Maya</Heading>  {/* sans, not serif */}
```

**Props**
- `level`: `1 | 2 | 3 | 4` (required)

**Forbidden**
- Passing arbitrary className that changes font/size/weight
- Using `<h1>` directly without this component
- Nesting more than one `<Accent>` inside a heading

---

## Accent

The one-word italic rust inside a heading. **Max one per screen.**

```tsx
<Heading level={1}>Welcome back, <Accent>Maya</Accent>.</Heading>
```

The component must track screen-level occurrences (via context or a dev warning) and log a warning in dev when a second `<Accent>` appears on the same screen.

---

## Label

Caps section label. Always rust. Always at the top of a section.

```tsx
<Label>01 · The Scale</Label>
```

**Forbidden**
- Custom color
- Sentence case (the component uppercases)
- Inside a card title

---

## Card

Three treatments. Choose once per card type on a page.

```tsx
<Card treatment="surface">...</Card>   // default
<Card treatment="hairline">...</Card>
<Card treatment="paper">...</Card>     // inline grouping, no border
```

**Props**
- `treatment`: `'surface' | 'hairline' | 'paper'` (default `'surface'`)
- `interactive?`: `boolean` — if true, applies `surface-pressed` on hover (only for `surface` treatment)

**Forbidden**
- `box-shadow` for elevation (use treatment)
- Mixing `surface` and `hairline` treatments inside another `Card`
- Nested cards more than 1 level deep

---

## Button

```tsx
<Button variant="primary">Keep it for me</Button>
<Button variant="secondary">Not now</Button>
<Button variant="ghost">Skip</Button>
```

**Props**
- `variant`: `'primary' | 'secondary' | 'ghost'` (default `'secondary'`)
- `size`: `'md'` only (one size — if you need another, the design is wrong)
- `disabled?`: `boolean`

**Forbidden**
- Icon-only without `aria-label`
- `primary` variant appearing more than once per screen
- Rounded-full buttons (use `radius-sm` = 4px)
- Custom colors via className

---

## Input

Upright sans, always. Placeholder is upright sans, always.

```tsx
<Input placeholder="What should she remember?" />
```

**Props**
- `placeholder?`: `string` — written as a gentle question, not a label
- `state?`: `'default' | 'focus' | 'error' | 'disabled'`

**Forbidden**
- `font-style: italic` on placeholder
- Serif placeholder
- Error state color other than `oxblood`
- Float labels (they compete with placeholder tone)

---

## Chip / Status

```tsx
<Chip state="listening">Listening</Chip>    // rust label + pulsing dot, the rust moment
<Chip state="idle">Paused</Chip>            // ink-500 label
<Chip state="success">Kept</Chip>           // moss
<Chip state="warning">Re-check</Chip>       // amber
```

**Props**
- `state`: `'listening' | 'thinking' | 'idle' | 'success' | 'warning' | 'danger'`

**Forbidden**
- Custom colors
- `listening`/`thinking` chip appearing when another rust moment exists on screen

---

## Link (inline)

```tsx
<Link href="...">read the note</Link>
```

Renders as rust text with `border-bottom: 1px solid rgba(123,85,68,0.3)`. No underline.

**Forbidden**
- In navigation (use `NavLink` instead — no rust, no underline)
- More than one inline link per paragraph (if needed, rewrite the paragraph)

---

## Divider

A 1px line in `ink-300`. That is all.

```tsx
<Divider />
```

**Forbidden**
- Dashed, dotted, or colored dividers
- Vertical dividers thicker than 1px

---

## Toast / Banner

```tsx
<Toast signal="success">Noted.</Toast>
<Toast signal="warning">Maya's flight shifted to 5pm.</Toast>
<Toast signal="danger">Forgot this. Can't undo.</Toast>
```

**Props**
- `signal`: `'success' | 'warning' | 'danger' | 'neutral'`

**Forbidden**
- Icons alone without text
- Toasts that auto-dismiss for danger (require user ack)
- Stacking more than 2 toasts (queue them)

---

## Modal

```tsx
<Modal title="Forget this memory?" destructive>
  ...
  <Button variant="ghost">Keep it</Button>
  <Button variant="primary" tone="danger">Forget it</Button>
</Modal>
```

**Props**
- `title`: `string` (required) — serif H3
- `destructive?`: `boolean` — changes primary button tone to `oxblood`

**Forbidden**
- Closing on background click when `destructive`
- More than 2 actions (confirm + cancel)
- Body copy longer than 2 sentences

---

## Wordmark

```tsx
<Wordmark color="ink" />            // default
<Wordmark color="paper" on="ink" /> // paper on ink splash
<Wordmark size="nav" />             // 22px
<Wordmark size="footer" />          // 16px
```

**Props**
- `color`: `'ink' | 'paper' | 'rust'`
- `on`: `'paper' | 'surface' | 'hairline' | 'ink' | 'rust'`
- `size`: `'splash' | 'hero' | 'cover' | 'masthead' | 'nav' | 'footer' | 'min'` (maps to 128 / 88 / 56 / 32 / 22 / 16 / 14)

**Enforcement**
- Below 14px, the component renders the "d" monogram instead. No exceptions.
- Rendered in live type (`font-style: italic; font-weight: 500`). Never an SVG path.

---

---

## Blocks · one per attention CardType

Blocks are the tier above components. Each maps 1:1 to a `CardType` from
`donna/attention/vocabulary.py:70`. Every attention Donna writes, regardless
of domain, renders as one of these six shapes. **New affordances add data,
never layout.** That is the Lego promise.

A block:
- always opens with a `<Label>` (domain or window, caps rust)
- has exactly one heading at the role fixed for that block
- has a fixed body region with fixed rhythm
- has an optional footer region for at most one terminator (button / chip / link)
- **treatment** (`surface` | `hairline` | `paper`) is chosen by policy, not the block

Treatment mapping (from attention `SurfaceLevel`):

| surface_level | treatment | notes |
|---|---|---|
| `silent` | not rendered | — |
| `digest` | `paper` | inline grouping |
| `notify` | `surface` | default |
| `urgent` | `hairline` + rust claim | stands apart, may be the rust moment |

### EventStreamBlock · card=`event_stream`

```tsx
<EventStreamBlock
  title="fundraising thread"
  events={[
    { id: 'e1', timestamp: '04:12', title: 'sequoia replied', summary: 'wants revenue slide' },
    ...
  ]}
/>
```

**Layout contract**
- `<Label>` — top, caps rust (e.g. the domain or subject name)
- `<Heading level={4}>` — card title
- body: vertical stack of rows, each row is `[time | title + summary]`
  - time column: `type-small` + `num-tabular`, `color-muted`
  - title: `type-body`, `ink`
  - summary: `type-small`, `muted`
- max 3 rows visible at rest; tap to expand
- no action region

**Forbidden**
- Italic on any row
- More than 3 rows at rest
- Mixing time formats in the same block (pick one: absolute, relative, or kickoff-style)

### TallyBlock · card=`tally`

```tsx
<TallyBlock
  title="water"
  count={3}
  unit="glasses"
  window="so far today"
/>
```

**Layout contract**
- `<Label>` — top, caps rust
- `<Heading level={4}>` — card title (e.g. "water", "spend")
- body: the big number, then unit+window
  - number: serif 44/48, `num-tabular` weight 500, letter-spacing `-0.02em`
  - unit line: `type-small`, `color-muted`, `space-2` below the number
- optional: a thin 3px progress bar at `alpha-ink-08` background, filled in the signal tone for this domain
- no action region

**Forbidden**
- Subtitle above the heading
- Icon larger than the heading
- Absolute count without a window ("3 glasses" alone — always pair with a window)

### BriefBlock · card=`brief`

```tsx
<BriefBlock
  title="fundraising"
  headline="three investors pinged while you were out"
  bullets={['sequoia · revenue slide by friday', 'accel · re-engaged']}
  sources={['gmail · series-a thread']}
/>
```

**Layout contract**
- `<Label>` — caps rust
- `<Heading level={4}>` — the headline (sans 600; H3 only if it's the screen's primary block)
- body: `<ul>` bullets using `type-body`, `ink-300` marker color
- footer: sources as `type-caption`, muted, prefixed by "source · "
- no action region by default; policy may attach one `<Button variant="secondary">` ("read thread")

**Forbidden**
- More than 3 bullets (if you need more, it's a prep_doc, not a brief)
- Italic on bullets
- Sources shown inline with bullets

### PrepDocBlock · card=`prep_doc`

```tsx
<PrepDocBlock
  forEvent="1:1 with priya"
  talkingPoints={["where she's stuck", "who she's met"]}
  openQuestions={["what does good look like by week two?"]}
/>
```

**Layout contract**
- `<Label>` — e.g. "FOR · 1:1 WITH PRIYA"
- `<Heading level={4}>` — the context line (or talking-points header if no context)
- body: numbered list (serif 500 counters in rust), each point in `type-body`
- if `openQuestions`: `<Divider />` then a single open question block with lead-in "still open: "
- optional: one `<Button variant="ghost">` ("reopen this")

**Forbidden**
- More than 5 numbered points (if you need more, it's two preps)
- Mixing talking points and open questions in the same list
- Bullets instead of numbers (numbers imply sequence)

### OpenLoopBlock · card=`open_loop`

```tsx
<OpenLoopBlock
  title="still open"
  summary="call dad — committed this week on tuesday"
  lastActivity="6 days"
  waitingOn="you, to pick up the phone"
  isResolved={false}
/>
```

**Layout contract**
- `<Label>` — caps rust ("STILL OPEN" or domain name)
- `<Heading level={4}>` — loop summary (line 1)
- age pill right-aligned with the heading: `type-small`, rust, caps, tracking `0.06em`
- body: waiting-on line as `type-small`, `color-muted`
- if this is *the* loop for the moment (policy decision), this block gets treatment `hairline` + claims the rust moment; otherwise `surface`

**Forbidden**
- Italic on the waiting-on line
- Multiple loops in one block (use many blocks or an EventStreamBlock)
- Showing resolved loops — policy must filter these out

### PingBlock · card=`ping`

```tsx
<PingBlock
  message="maya's sister lands at 4:10. the peonies should leave by three."
  fireAt="02:40 pm"
  surfaceLevel="notify"
/>
```

**Layout contract**
- no `<Label>` (this is the quietest block — it has no category)
- body: `type-body`, `ink`
- footer: `type-small`, `muted` — "fire at HH:MM · relative-day"
- treatment: `paper` for digest, `hairline` for urgent

**Forbidden**
- Heading (pings have no title, on purpose)
- More than 2 sentences of body (if you need more, it's a brief)
- Stacking two pings — render one at a time

### SparklineStatusBlock · temporal rhythm

```tsx
<SparklineStatusBlock
  title="lunch · last 7 days"
  days={[
    { state: 'miss' }, { state: 'hit' }, { state: 'miss' }, { state: 'miss' },
    { state: 'half' }, { state: 'hit' }, { state: 'miss' },
  ]}
  window="mon → sun"
  hitCount={2}
  total={7}
/>
```

**When to use**
- any tally or event_stream attention where the *rhythm* over days matters more than a single count
- streak visibility ("5 of the last 7")
- habit aging ("this was daily in march, twice in april")

**When NOT to use**
- a single moment in time (use TallyBlock)
- more than 14 days (use a chart, not a sparkline)

**Layout contract**
- `<Label>` — top, caps rust
- `<Heading level={4}>` — card title
- 7–14 vertical bars, 6px wide, 3px gap, right-edge = today
- three states: `hit` (color-ink, full-height), `half` (color-muted, half-height), `miss` (paper-500, 4px stub)
- footer row: left = window label (type-small, muted), right = count `num-tabular`

**Forbidden**
- More than 14 bars (too dense for the primitive)
- Color bars in signal hues (only ink/muted/paper-500 scale)
- Animating bar heights on render

### ProvenanceFactRowBlock · auditable living profile

```tsx
<ProvenanceFactRowBlock
  title="aarav, partial"
  rows={[
    { key: 'place',   value: 'mumbai · bandra',      source: 'told me · tuesday 9:14' },
    { key: 'season',  value: <em>antler quarter</em>, source: 'inferred · confidence 0.68' },
    { key: 'pattern', value: 'sleeps poorly when priya slips', source: 'observed · 3 weeks of chat' },
  ]}
/>
```

**When to use**
- living profile surfaces
- any place the user needs to see *where donna learned something*
- trust-building screens (onboarding, settings, "what do you know about me")

**When NOT to use**
- transient data (use EventStreamBlock)
- anonymous facts donna didn't author (use a plain key/value list)

**Layout contract**
- `<Label>` — top, caps rust
- `<Heading level={4}>` — optional section title
- table with `grid-template-columns: 96px 1fr`
- each row: left = `type-label` rust key, right stack = serif `type-body` value + `type-caption` muted source
- source line uses " · " separator with half-opacity dots
- rows separated by `ink-300` hairlines, last row no border

**Forbidden**
- Source line without a provenance tag (every row must have `told me` / `observed` / `inferred` / `from calendar` etc.)
- Colored rows (the state is in the source, not the color)
- More than 8 rows (paginate or group with multiple instances)

### DryRunOfferBlock · the promotion ritual

```tsx
<DryRunOfferBlock
  kind="event_stream"          // the attention type being promoted
  status="dry-run · awaiting you"
  headline={{ prefix: 'keep an eye on ', accent: 'luca' }}
  body="the antler deck thread, not email. daily 07:30 check-in."
  sources={['email', 'calendar', 'chat']}
  actions={{ live: 'live', tweak: 'tweak', dismiss: 'not yet' }}
/>
```

**When to use**
- promoting a shadow attention to live (the three-button ritual)
- the morning "three things I've been watching quietly"
- any offer where the user needs to see *what shape the attention will take* before approving

**When NOT to use**
- a plain yes/no confirmation (use OfferBlock)
- an already-live attention (use the block for its own CardType)

**Layout contract**
- treatment: `hairline` (stands apart from live content)
- header row: left = dry-run status with muted dot + rust caps text; right = `.dryrun-kind` pill (mono caption, ink-300 border) showing the attention type
- `<Heading level={4}>` — the action phrased as a sentence ("keep an eye on luca"), with one rust italic accent on the subject
- body: `type-body` explanation
- caption: `type-caption` muted sources, " · " separated
- actions row: three buttons — **primary "live"** (the rust moment), plus two ghost buttons "tweak" and "not yet"

**Forbidden**
- More than 3 actions
- The kind pill using any color outside ink-300 border / muted text
- Two primary buttons (only "live" can be primary)
- Missing the kind pill — the user must see which CardType they're approving

### LifecycleBandBlock · unified state view

```tsx
<LifecycleBandBlock state="live"     label="live · running"           count={8} />
<LifecycleBandBlock state="shadow"   label="shadow · watching quietly" count={3} />
<LifecycleBandBlock state="paused"   label="paused · you said not yet" count={2} />
<LifecycleBandBlock state="resolved" label="resolved · harvested"      count={12} />
```

**When to use**
- the unified-lifecycle "power user" surface (plan E)
- any list that groups by attention state
- `/observe` or garden-like views where the user scans state at once

**When NOT to use**
- the moment dashboard (policy picks blocks, not states)
- a single-state view (use a plain SectionHead)

**Layout contract**
- full-width band, not a card
- top/bottom `ink-300` hairline; left 2px colored border encoding state
- state color map: `living`=rust, `today`=ink, `live`=moss, `shadow`=muted, `paused`=amber, `resolved`=ink-300
- row: state label (`type-label`, state-colored) + count (`num-tabular`, muted)
- attentions belonging to the state stack *below* the band, not inside it

**Forbidden**
- Using signal colors (moss/amber/oxblood) for anything other than their mapped state
- Borders on all four sides (only top + bottom + left accent)
- Empty bands — if count is 0, hide the band

### InvitationPromptBlock · bootstrap / cold-start

```tsx
<InvitationPromptBlock
  eyebrow="ask me to"
  verb="watch"
  placeholder="keep an eye on "
  hints={['priya', 'luca — antler', 'my cofounder', 'the shipment from oscar\'s']}
/>
```

**When to use**
- day 1 / cold-start — donna has no shadows to offer yet
- any surface that teaches the user how to author intent
- plan A's "invitation" posture (she waits to be asked)

**When NOT to use**
- a running product (after day 7, the ritual retires to offers)
- mid-conversation (this is a page-level bootstrap, not a chat affordance)

**Layout contract**
- `<Label>` — eyebrow ("ASK ME TO")
- `<Heading level={3}>` (serif) with one italic accent verb (`<em class="italic-accent-heading">watch</em>`)
- a fake text input: paper bg, ink-300 border, `type-input`, placeholder text + blinking cursor
- hint chips below: pill buttons, ink-300 border, transparent bg, `type-small` muted — clicking one pre-fills the input

**Forbidden**
- More than 4 hint chips
- A real submit button (cold-start lands LIVE without dry-run — no approval step)
- Icons inside the input (keep the input monospace-free and upright)

### MiniStatGridBlock · three tallies, one glance

```tsx
<MiniStatGridBlock
  cells={[
    { key: 'calories', value: '820', total: '/2,200', sub: 'chicken bowl at 1:30' },
    { key: 'water',    value: '3',   total: '/8',     sub: 'so far today' },
    { key: 'loops',    value: '2',                    sub: 'open · dad, priya' },
  ]}
/>
```

**When to use**
- midday check-ins where 2–3 tallies live together
- the "live today" slice of plan D
- any screen that needs extreme compression (mobile, peripheral glance)

**When NOT to use**
- a single tally (use TallyBlock)
- 4+ tallies (the grid breaks readability; use a TrackerGridBlock instead)

**Layout contract**
- treatment: `surface`, padding `space-4 0` (vertical only; horizontal handled by cells)
- grid with 3 columns, cells divided by `ink-300` vertical hairlines, last cell no border
- each cell: `type-label` key, then big serif tabular value (26px), then `type-caption` sub
- optional `total` shown muted and smaller inline beside the value ("820/2,200")

**Forbidden**
- More than 3 cells (always exactly 3)
- Icons in cells (the key line is the category)
- Progress bars per cell (use TrackerGridBlock for that)
- Colored cells (state lives in the sub-line, not the background)

---

### OfferBlock · from Donna's `offer` terminator

```tsx
<OfferBlock
  ask="want me to draft the reply?"
  body="sequoia wants a revenue slide by friday."
  confirm={{ label: 'Draft it', action: 'draft_reply' }}
  decline={{ label: 'Not now', action: 'dismiss' }}
/>
```

**Layout contract**
- treatment: `hairline`
- `<Label>` — "OFFER"
- `<Heading level={4}>` — the ask
- body: `type-body`
- action row: exactly one `<Button variant="primary">` (the rust moment) + one `<Button variant="ghost">`

**Forbidden**
- More than 2 actions
- Primary button without a concrete verb ("OK" is wrong; "Draft it" is right)

---

## Components NOT allowed

If you feel you need one of these, the design is wrong. Stop and rethink.

- ❌ Accordion with chevron icons (use collapsed `<details>` or a separate page)
- ❌ Tooltip with arrow tail (use `Popover` + `type-caption`)
- ❌ Progress bar with gradient fill
- ❌ Avatar with colored ring
- ❌ Notification badge with red fill (use `type-caption` + `rust` text)
- ❌ Tab with underline indicator in any color other than rust
- ❌ Dropdown with custom-styled scrollbar
- ❌ Any component that introduces a 10th color

---

*Locked · v1.0.0*
