# DONNA · DESIGN SYSTEM

> **This file is gospel. If a request contradicts it, the request is wrong.**
> Read this file before writing a single line of UI code.
> Do not paraphrase. Do not "improve." Do not introduce new values.

---

## 0. Operating rules for Claude Code

When you build any page, component, or artifact for Donna:

1. **Read `tokens.css` and `tokens.json` first.** Those are the only colors, type, space, radius, shadow, and motion values that exist.
2. **Never introduce a raw hex, raw px font-size, or raw shadow** anywhere in code. If you reach for one, stop — the token you need already exists, or the design is wrong.
3. **Never add a color to the palette.** If success/warning/danger is the real need, use `--signal-*`. If an emphasis is needed, use rust — once per screen.
4. **The palette is closed.** There are 6 core colors + 3 signals + their scales. That is the entire visual vocabulary. Forever.
5. **Prefer existing components** in `components/` over building new ones. If a new component is needed, it must be added to `components.md` in the same PR.
6. **Italic is a scalpel, not a brush.** See §3. If you're reaching for italic, you're probably wrong.
7. **One rust moment per screen.** See §4. This is the hardest rule to hold and the most important.

When in doubt: **ink on paper, sans-serif, no shadow, no italic, no rust.** That is the correct baseline.

---

## 1. Colors · the six + three

### Core (6 roles)

| Token | Hex | Role | Use on | Never |
|---|---|---|---|---|
| `paper` | `#FBF7F5` | Page background | body, app shell | tint further |
| `surface` | `#F0EAE4` | Card/input at rest | paper | for page bg |
| `surface-pressed` | `#E7DFD7` | Hover/active | surface transitions | resting bg |
| `ink` | `#1E1A18` | Primary text | paper, surface | pure `#000` |
| `rust` | `#7B5544` | The one accent | one moment per screen | two things per screen |
| `muted` | `#6B615C` | Secondary text | paper, surface | as body color |

### Signal (3 semantic hues — not decorative)

| Token | Hex | Tint | Only for |
|---|---|---|---|
| `moss` (success) | `#5C6B4A` | `#EEF1E7` | "done", "kept", "noted" — never a celebration |
| `amber` (warning) | `#A8804A` | `#F5EBD9` | "heads up, something shifted" — paired with a sentence |
| `oxblood` (danger) | `#8B3A2E` | `#F3E0DC` | destructive confirm only |

### Scales

Only use scales for: disabled states, hairlines, tints. UI components reference the 6 core roles.

- `paper-50..500` — neutral surface ramp
- `ink-200..900` — text / border ramp
- `rust-50..900` — accent ramp (use `rust-100` for rust tints only)

---

## 2. Type · one serif, one sans, one italic rule

### Families

- **EB Garamond** — serif, upright by default. For hierarchy.
- **Red Hat Text** — sans. For product.
- Italic sans is **forbidden in UI**. Reads as apology. Donna is not apologetic.
- Serif 700 is **forbidden**. If you need more weight than 500, the layout is wrong.

### Roles · use the class, not raw values

```html
<!-- ✅ correct -->
<h1 class="type-h1">Good morning, <em class="italic-accent-heading text-rust">Arnav</em>.</h1>
<p class="type-body">Maya's sister lands at 4.</p>

<!-- ❌ wrong -->
<h1 style="font-size: 44px; font-family: serif">...</h1>
<p class="text-[17px] leading-[26px]">...</p>
```

| Role | Family | Size/Line | Weight | Use |
|---|---|---|---|---|
| `type-display` | serif | 64/65 | 400 | **Marketing hero only. NEVER in-product.** |
| `type-h1` | serif | 44/48 | 400 | Page title, one per page |
| `type-h2` | serif | 32/36 | 400 | Section |
| `type-h3` | serif | 22/28 | 500 | Subsection |
| `type-h4` | sans | 15/20 | 600 | Card title (most-used heading) |
| `type-lead` | sans | 18/29 | 400 | Page/section intro, 2 sentences max |
| `type-body` | sans | 16/25 | 400 | Default voice |
| `type-small` | sans | 14/22 | 400 | Timestamps, helpers |
| `type-caption` | sans | 12/18 | 400 | Annotations, form hints |
| `type-label` | sans | 11/16 · caps · +14% track | 500 | Categorical section labels · **always rust** |
| `type-button` | sans | 15/1 | 500 | Action |
| `type-input` | sans | 16/25 · upright | 400 | Placeholder & value |

---

## 3. Italic · the only three places it exists

Italic is allowed in exactly these three contexts. Anywhere else, it's a bug.

1. **One word inside H1 or H2** — the accent word. Usually rust.
   ```html
   <h1 class="type-h1">Good morning, <em class="italic-accent-heading text-rust">Arnav</em>.</h1>
   ```

2. **Proper nouns / titles in body copy** — a book title, a name of something.
   ```html
   <p class="type-body">We're re-reading <em class="italic-accent-inline">Middlemarch</em> together.</p>
   ```

3. **Her quoted memory** — verbatim recall, in a quote block.
   ```html
   <blockquote class="italic-accent-memory">You said: peonies, not roses.</blockquote>
   ```

**Forbidden italics** (if you see this in output, fix it):
- Italic placeholder (`<input placeholder="...">` stays upright)
- Italic captions / helper text
- Italic page titles (whole heading)
- Italic section labels
- Italic buttons / nav / chips
- Italic card titles
- Italic chat messages (whole message)

---

## 4. Rust · one moment per screen

A screen has **exactly one** rust element. Not zero (unless no moment is warranted). Not two.

**What counts as a rust moment:**
- One word in an H1 or H2, rendered in rust
- One filled accent button (rust bg, paper text)
- One active chip/tab
- One inline link (rust text, `border-bottom: 1px solid rgba(123,85,68,0.3)`)
- One status chip when Donna is actively present ("Listening", "Thinking") — rust label + pulsing dot

**Section labels (caps) are rust too**, but don't count as "the moment" — they're a consistent categorical signal, not an accent.

**If two things want to be rust**, the screen has two priorities and the design is wrong. Pick one. The other becomes ink or muted.

---

## 5. Cards · three treatments, two per page max

Cards have exactly three treatments:

1. **Surface-filled** — `bg-surface`, no border. Primary cards.
2. **Hairline** — `bg-paper` + `border border-ink-300`. Secondary cards.
3. **Paper** (no treatment) — for inline groupings that don't need card-ness.

**A page holds at most two of each before it reads as busy.** If you're making a third, consolidate.

```html
<!-- surface-filled card -->
<article class="bg-surface rounded-md p-5">
  <header class="type-label">TODAY · 8:14</header>
  <h3 class="type-h4 mt-2">This week with Maya</h3>
  <p class="type-body mt-2">You said you'd pick up the frame from Oscar's.</p>
</article>

<!-- hairline card -->
<article class="bg-paper border border-hairline border-ink-300 rounded-md p-5">
  ...
</article>
```

---

## 6. Elevation · hairlines, not shadows

**Default elevation is `none`.** Cards elevate by surface swap or hairline, never drop-shadow.

Shadows are allowed **only** on:
- `shadow-modal` — modal dialogs
- `shadow-toast` — toasts
- `shadow-popover` — popovers, tooltips

If you reach for a shadow on a card, stop. Use `bg-surface` or a hairline instead.

---

## 7. Spacing · 4px base, named steps only

Space comes from the scale: `space-1` (4) → `space-10` (128). No arbitrary values.

| Common pairing | Space |
|---|---|
| Icon to label (inline) | `space-2` (8) |
| Stacked text within a card | `space-2` (8) |
| Card inner padding | `space-5` (24) |
| Between cards | `space-4` (16) or `space-5` (24) |
| Section gap | `space-7` (48) |
| Page top padding | `space-8` (64) |

If you need space between two values, the value you want is probably one of them — not the halfway point.

---

## 8. Wordmark · locked

The wordmark is **set in live type, not a path**.

```html
<span class="font-serif italic font-medium lowercase tracking-[-0.01em]">donna</span>
```

- Lowercase. Always.
- EB Garamond italic, weight 500.
- Tracking `-1%` (`-0.01em`).
- **No dot, no underline, no box, no swash.** The italic is the mark.
- Minimum display size: **14px**. Below that, use the "d" monogram.
- **Clearspace:** minimum margin around the mark = width of the lowercase "d".
- One rust per screen still applies: if wordmark is rust, nothing else on that screen may be.

Approved pairings only (see `wordmark.md` — not included here for brevity, but the six pairings are: ink/paper, ink/surface, rust/paper, paper/ink, paper/rust, ink/hairline).

---

## 9. What NOT to do — the forbidden list

In priority order. These are not style preferences. These are system violations.

1. ❌ A new hex color anywhere in code
2. ❌ Two rust elements on one screen
3. ❌ Italic outside the three approved roles
4. ❌ Serif at weight 700
5. ❌ Drop shadow on a card at rest
6. ❌ Pure `#000` as text color (use `ink` = `#1E1A18`)
7. ❌ Underlines on links (use rust + bottom border)
8. ❌ Gradients anywhere, ever
9. ❌ Icon-only warnings (amber always pairs with a sentence)
10. ❌ Section label in any color other than rust
11. ❌ Inventing a new type size between the scale
12. ❌ Using `type-display` inside the product (marketing surfaces only)
13. ❌ Auto-elevating cards on hover with shadow (use `surface-pressed`)
14. ❌ Placeholder text in italic or serif

---

## 10. Decision tree · "What color/type do I use?"

```
Is it text?
├── Is it a page title (H1)?            → serif, ink. Optional one-word italic rust.
├── Is it a section title (H2/H3)?      → serif, ink.
├── Is it a card title?                 → type-h4 (sans 600), ink.
├── Is it a caps section label?         → type-label, rust, always.
├── Is it an inline link?                → rust + rust link underline.
├── Is it her recalled memory?         → italic-accent-memory, ink.
├── Is it secondary/helper?             → muted.
└── Everything else                     → type-body, ink.

Is it a surface?
├── Page?                               → paper.
├── Primary card?                       → surface OR paper+hairline. Pick once per type.
├── Pressed/hovered card?               → surface-pressed.
└── Button?                             → see §11.

Is it a signal?
├── "Kept / noted / done"?              → moss + moss-tint.
├── "Heads up"?                         → amber + amber-tint + a full sentence.
├── "Forget this / remove"?             → oxblood + oxblood-tint. Destructive only.
└── Anything else                       → NOT a signal. Use ink or rust.
```

---

## 11. Buttons · three variants, no more

| Variant | BG | Text | Border | Use |
|---|---|---|---|---|
| `primary` | `rust` | `paper` | none | The one action on a screen |
| `secondary` | `paper` | `ink` | `hairline ink-300` | Supporting action |
| `ghost` | transparent | `ink` | none | Tertiary / toolbar |

- `type-button` class on the label.
- `primary` counts as the rust moment for that screen.
- Disabled: `ink-300` text, `paper-200` bg, no border change.
- Focus: `focus-ring` token, never browser default.
- **No icon-only buttons** without `aria-label`.

---

## 12. For Claude Code · file layout expected

```
donna-design-system/
├── DESIGN_SYSTEM.md       ← this file, read first
├── tokens.css             ← CSS custom properties + type utility classes
├── tokens.json            ← machine-readable mirror
├── tailwind.config.js     ← Tailwind mapped to tokens
├── components.md          ← component contracts (Button, Card, Input, etc.)
├── wordmark.md            ← wordmark-specific rules
├── .stylelintrc.json      ← enforces no raw hex / no forbidden shadows
└── eslint-plugin-donna/   ← (optional) custom rules for React
```

When generating any new page:
1. Import `tokens.css` at the app root.
2. Use Tailwind classes from `tailwind.config.js` OR the utility classes in `tokens.css`.
3. Compose with components from `components/`. Do not style elements directly.
4. Before marking a task complete, re-read §9 (forbidden list). If your output violates any row, fix it.

---

*Locked · v1.0.0 · Do not modify without a system-wide review.*
