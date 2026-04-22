# SYSTEM.md
The canonical Donna design system. Every decision, locked.

One font duo. One color family. One spacing scale. Upright serif is the voice, italic is the emphasis, sans is the utility. Rust is brand, signals are states, never the other way around.

When the audit found two specs for the same thing, this document picks one.

---

## 0 · Principles

1. **Paper first.** The canvas is warm off-white. Black is a value, not the default.
2. **Editorial, not corporate.** Serif headings upright. Italic is emphasis, never decoration.
3. **One rust per screen.** Rust is for the one thing that matters most.
4. **Signals are states.** Moss/amber/oxblood appear only when something is true about the world.
5. **Hairlines, not boxes.** We contain with 1px rules and generous whitespace, not filled containers.
6. **Tight vertical rhythm.** A 4px spacing base, 10 named steps. Off-scale values are off-system.
7. **Numbers are tabular.** Any time a digit appears next to another digit, it's tabular.

---

## 1 · Color

### Families (primitives)

Five families. Nothing outside of them ships.

| Family   | Purpose                                   | Range              |
|----------|-------------------------------------------|--------------------|
| Paper    | Canvas, surfaces, pressed states          | `--paper-50` → `--paper-600` |
| Ink      | All type, hairlines                       | `--ink-300` → `--ink-900` |
| Rust     | Brand accent, one per screen              | `--rust-50` → `--rust-900` |
| Moss     | Success                                   | `--moss-100`, `--moss-700` |
| Amber    | Warning                                   | `--amber-100`, `--amber-700` |
| Oxblood  | Danger                                    | `--oxblood-100`, `--oxblood-700` |

### Semantic roles (what components use)

Components **never** reference primitives. They consume roles.

| Role                 | Token                  | Use                                    |
|----------------------|------------------------|----------------------------------------|
| Page background      | `--bg-canvas`          | body, full-bleed frames                |
| Card / input rest    | `--bg-surface`         | the resting state of any contained UI  |
| Pressed / hover      | `--bg-surface-alt`     | pressed buttons on surface, hover cell |
| Inverse canvas       | `--bg-inverse`         | dark splash, sign-in                   |
| Primary type         | `--fg-primary`         | body, headings                         |
| Secondary type       | `--fg-secondary`       | lead paragraphs                        |
| Tertiary type        | `--fg-tertiary`        | meta, labels                           |
| Muted type           | `--fg-muted`           | eyebrow, least-weight copy             |
| Placeholder          | `--fg-placeholder`     | input rest                             |
| Accent (brand)       | `--fg-accent`          | rust text, one per screen              |
| Accent pressed       | `--fg-accent-strong`   | hover on accent button                 |
| Hairline             | `--border-hairline`    | default 1px divider                    |
| Hairline strong      | `--border-strong`      | focused input, divider under header    |

### Rules

- **R-C1 · One rust per screen.** If the wordmark is rust, nothing else is. If a primary button is rust, the wordmark is ink.
- **R-C2 · Signals are earned.** Moss/amber/oxblood require a true state (saved, warning, destructive). Never decorative.
- **R-C3 · No info signal.** Donna has no blue. If you reach for "informational," use `--fg-muted`.
- **R-C4 · Hairlines on paper only.** Borders are `rgba(30,26,24,α)` on paper, or `--ink-300` on surface. Never border-on-border.
- **R-C5 · No invented hex.** The dashboard's `#2C3E63` avatar is off-system and removed.
- **R-C6 · Dark by class.** `.inverse` flips the semantic layer only. Primitives stay.

### Contrast commitments

All pairings verified ≥ 4.5:1 for body, ≥ 3:1 for ≥18px:

- `--fg-primary` on `--bg-canvas` — 14.3:1 ✅
- `--fg-secondary` on `--bg-canvas` — 10.2:1 ✅
- `--fg-tertiary` on `--bg-canvas` — 5.3:1 ✅
- `--fg-muted` on `--bg-canvas` — 3.5:1 ✅ (large text only)
- `--fg-accent` on `--bg-canvas` — 5.9:1 ✅
- `--fg-accent` on `--bg-accent-tint` — 5.6:1 ✅
- `--fg-inverse` on `--bg-inverse` — 13.8:1 ✅

---

## 2 · Typography

### Families

| Role    | Family           | Loaded weights              |
|---------|------------------|-----------------------------|
| Serif   | EB Garamond      | 400 (normal + italic), 500 italic only |
| Sans    | Red Hat Text     | 400, 500, 600               |
| Mono    | system           | regular only                |

### The upright-serif decision (resolves AUDIT 8.1)

**Page titles, section titles, and card headings in serif are set upright (regular 400), not italic.**

Italic is reserved for:
1. The wordmark (see §7).
2. In-prose emphasis (a word, a phrase).
3. Pull-quotes and marginalia.

When every heading is italic, italic means nothing. Upright serif carries the editorial tone; italic carries emphasis inside that voice.

### Roles

| Role       | Size | Line-height | Tracking         | Family/weight/style      |
|------------|------|-------------|------------------|--------------------------|
| Display    | 72   | 1.02        | -0.025em         | serif 400 upright        |
| H1         | 56   | 1.10        | -0.02em          | serif 400 upright        |
| H2         | 36   | 1.10        | -0.015em         | serif 400 upright        |
| H3         | 22   | 1.24        | -0.01em          | serif 500 upright        |
| H4 / card  | 15   | 1.24        | 0                | **sans 600**             |
| Lead       | 17   | 1.60        | 0                | sans 400                 |
| Body       | 16   | 1.65        | 0                | sans 400                 |
| Small      | 14   | 1.50        | 0                | sans 400                 |
| Caption    | 13   | 1.50        | 0                | sans 400                 |
| Eyebrow    | 11   | 1.00        | 0.14em uppercase | sans 500                 |
| Button     | 15   | 1.00        | 0                | sans 500                 |

### The card-title decision (resolves AUDIT 8.2)

**Card titles are sans 600 at 15/1.24.** Serif italic at 20px was tried and rejected: it competed with page H2s and made card grids feel noisy. Sans 600 reads as "this is a label for a thing," which is what a card title is.

Serif italic card titles are allowed only on editorial surfaces (onboarding, about page). In product UI: sans.

### The placeholder decision (resolves AUDIT 8.3)

**Placeholder text is sans 400 at the input's own size, in `--fg-placeholder`.** Never italic serif. Italic placeholders look like draft copy and cost a beat of recognition on every input.

### The chat-bubble decision (resolves AUDIT 8.4)

**Donna's outgoing messages are sans 400 at 16/1.65.** The messenger is a utility, not a letterpress; her voice comes from what she says, not the metal it's set in.

Exception: the onboarding "letter from Donna" artifact is serif 19px — it's a letter, not a message.

### Weight policy (resolves AUDIT 8.13)

- **400** — body, all paragraph text, H1–H2 serif.
- **500** — button labels, eyebrow labels, H3, wordmark.
- **600** — sans-only, for `--size-h4` card titles and tabular numerals where emphasis is load-bearing.
- **700** — **not loaded**, never used. Previous guidance to "load 700 for nums" was a note-to-self; 600 + tabular is enough.

### Tracking ladder (resolves AUDIT 8.7)

Serif tightens predictably by size: `-0.025` at display, `-0.02` at H1, `-0.015` at H2, `-0.01` at H3, 0 below. Sans is always `0` except the uppercase eyebrow (`+0.14em`). No other tracking values.

### Rules

- **R-T1 · Upright before italic.** Italic is emphasis, not decoration.
- **R-T2 · Two families, three weights.** Serif 400/500, sans 400/500/600. No bold serif, no 700.
- **R-T3 · Measure.** Prose caps at `--measure-prose` (62ch). Narrow copy at 48ch.
- **R-T4 · Balance on headings, pretty on prose.** `text-wrap: balance` on h1–h3, `pretty` on p.
- **R-T5 · Tabular numerals for any digit stack.** Counts, dates, timestamps.

---

## 3 · Spacing

### Scale

4px base, ten named steps. Only these may appear.

```
0 · 1px · 4 · 8 · 12 · 16 · 24 · 32 · 48 · 64 · 96 · 128
```

Tokens: `--space-0`, `--space-px`, `--space-1`…`--space-10`.

### Off-ramp values (resolves AUDIT 8.8)

The following appeared in old files and are **removed from the system**:

| Was | Becomes |
|-----|---------|
| 10  | 12 (`--space-3`) |
| 14  | 16 (`--space-4`) — or 12 if tight |
| 18  | 16 or 24 |
| 20  | 24 (`--space-5`) |
| 28  | 32 (`--space-6`) |
| 40  | 48 (`--space-7`) |
| 56  | 48 or 64 |
| 80  | 64 or 96 |
| 88  | 96 (`--space-9`) |

### Rules

- **R-S1 · Card padding.** 24 on mobile, 32 on desktop. `--space-5` / `--space-6`.
- **R-S2 · Page gutter.** 24 on mobile, 48 on desktop. `--space-5` / `--space-7`.
- **R-S3 · Stack rhythm.** Default stack gap is 16 (`--space-4`). `.stack-lg` is 32, `.stack-xl` is 64.
- **R-S4 · Section break.** 96 (`--space-9`) between top-level sections on an editorial page; 64 in product UI.
- **R-S5 · Hairline, not gap.** A hairline rule replaces a 48+ gap where content is related.

---

## 4 · Radius

| Token           | px    | Use                                 |
|-----------------|-------|-------------------------------------|
| `--radius-0`    | 0     | hairlines, table cells              |
| `--radius-xs`   | 4     | chip inner, small pressed affordance|
| `--radius-sm`   | 6     | buttons, inputs                     |
| `--radius-md`   | 10    | cards, dialogs                      |
| `--radius-lg`   | 16    | large modal, hero cards             |
| `--radius-xl`   | 24    | hero surface, rare                  |
| `--radius-full` | 999   | chips, dots, avatars                |

Removed: `3px` and `5px` (AUDIT 8.9). Off-system.

---

## 5 · Shadow

Four steps. Warm — shadows are ink-tinted, not black.

| Token        | Use                              |
|--------------|----------------------------------|
| `--shadow-0` | resting flat                     |
| `--shadow-1` | subtle raise, chip-in-hover      |
| `--shadow-2` | card hover, menu                 |
| `--shadow-3` | floating element, popover        |
| `--shadow-4` | modal, drawer                    |

- **R-Sh1 · Shadows are rare.** Most surfaces sit flat on hairlines. Reserve shadows for elements that leave the page (menus, modals).

---

## 6 · Motion

| Token                | Duration | Use                              |
|----------------------|----------|----------------------------------|
| `--duration-fast`    | 160ms    | hover, press, focus              |
| `--duration-normal`  | 280ms    | drawer, menu, toast              |
| `--duration-slow`    | 480ms    | route change, modal              |

| Easing               | Shape                          |
|----------------------|--------------------------------|
| `--ease-out`         | default — arrives gently       |
| `--ease-in-out`      | reciprocal — for reversible UI |
| `--ease-editorial`   | long, slow fades on serif      |

- **R-M1 · Animate meaning, not decoration.** If the motion doesn't communicate state, remove it.
- **R-M2 · Respect reduced motion.** Every transition must collapse to `0ms` when `prefers-reduced-motion: reduce`.

---

## 7 · Wordmark

Set in **EB Garamond, italic 500, lowercase, tracking −0.01em**. No dot. No underline. No swash.

Resolves AUDIT 8.5: the `.wordmark::after` dot in the old `docs.css` and `tokens.css` is deprecated. The locked spec lives in `system/wordmark.html` and ships at weight 500.

- **R-W1 · Ink, rust, or paper only.** No signal colors on the mark.
- **R-W2 · One rust per screen.** If the mark is rust, nothing else on that screen is.
- **R-W3 · Minimum 14px.** Below 14px, use the "d" monogram.
- **R-W4 · Never redraw.** Live type, not a path. `font-style: italic; font-weight: 500; letter-spacing: -0.01em;`
- **R-W5 · Clearspace.** Minimum margin is the width of the lowercase "d".

---

## 8 · Z-index

Named layers, declared once (resolves AUDIT §7 gap).

| Token            | Value | Use                     |
|------------------|-------|-------------------------|
| `--z-base`       | 0     | default                 |
| `--z-raised`     | 10    | hover lift, sticky card |
| `--z-sticky`     | 100   | sticky header/nav       |
| `--z-dropdown`   | 200   | menus, autocomplete     |
| `--z-modal`      | 300   | dialogs, drawers        |
| `--z-toast`      | 400   | toasts, notifications   |
| `--z-tooltip`    | 500   | tooltips, top-most      |

Arbitrary z-index values are forbidden. Use a named layer or create one here first.

---

## 9 · Voice & copy

The system has a voice. It shows up in microcopy, empty states, and labels.

- **Quiet and specific.** "Saved 2 minutes ago" not "Autosaved successfully!"
- **First-name.** Donna refers to herself in the first person. "I kept this." not "This was kept."
- **No exclamation marks.** Not one.
- **Lowercase product noun.** "donna" — the brand is always lowercase except at sentence start.
- **No emoji in product UI.** Drafts, onboarding prose, and marketing may use one.

---

## 10 · What this system doesn't do

- **No tabs.** The product uses a single-column drawer pattern. Tabs appeared in one dashboard variant and are retired.
- **No dropdowns for navigation.** Drawers for secondary, links for primary.
- **No gradients.** Flat warm colors. A gradient is a tell that the system is failing.
- **No skeumorphic texture.** Paper is a metaphor, not a JPEG.
- **No icons in place of labels.** Icons beside labels, never replacing them.

---

## 11 · Deprecations (from this audit)

Moved to `/archive/` and not to be referenced going forward:

- `system/foundations.html` → replaced by `system/type.html` + `system/colors.html` (and this document)
- `system/wordmark-d.html`, `system/wordmark-colors.html` → replaced by `system/wordmark.html`
- `screens/mobile-dashboard.jsx`, `screens/ios-frame.jsx` → scaffold-only, superseded
- `.wordmark::after` dot CSS in `assets/tokens.css` and `assets/docs.css`
- `--signal-info` token — never worked (broken declaration), no info state in the system
- `font-weight: 700` — unloaded
- `border-radius: 3px` and `5px` — replaced by `--radius-xs`/`--radius-sm`
- Spacing values 10, 14, 18, 20, 28, 40, 56, 80, 88 — replaced per §3
- Avatar `#2C3E63` — removed
- Italic-everywhere headings — replaced per §2
- Serif italic placeholders — replaced per §2
- Serif italic chat bubbles — replaced per §2
