# AUDIT.md
Extracted from shipped artifacts in this project. No invention, no aspiration.

Sources scanned:
- `assets/tokens.css` · `assets/docs.css`
- `system/foundations.html` · `system/type.html` · `system/colors.html`
- `system/components.html` · `system/patterns.html` · `system/wordmark.html`
- `screens/dashboard.html` · `screens/mobile-dashboard.html`
- `index.html`

---

## 1 · COLOR (unique hex values)

| Hex       | Role observed                        | Files |
|-----------|--------------------------------------|-------|
| `#FBF7F5` | `--bg` · paper background            | 11 (every file) |
| `#F0EAE4` | `--surface` · card / input rest      | 9 |
| `#E7DFD7` | `--surface-2` · pressed / hover      | 5 |
| `#F5EFEA` | accent tint / `paper-200`            | 6 |
| `#FDFAF8` | `paper-50` · subtle tint             | 4 |
| `#D6CAC0` | `paper-500` · not used in UI         | 2 (foundations, colors) |
| `#B8A89B` | `paper-600` · not used in UI         | 1 (foundations) |
| `#1E1A18` | `--ink` · all primary type           | 11 |
| `#3A3331` | `--ink-700`                          | 6 |
| `#6B615C` | `--ink-500` / `--muted`              | 11 |
| `#8F837C` | `--ink-400`                          | 10 |
| `#B5A89F` | `--ink-300` placeholder/disabled     | 2 |
| `#D9CEC5` | `--ink-200` hairline on surface      | 1 |
| `#7B5544` | `--accent` · rust 700                | 11 |
| `#4A2F23` | rust 900 · hover for accent          | 3 |
| `#A07562` | rust 500                             | 2 |
| `#C9A796` | rust 300                             | 3 |
| `#EBDCD2` | rust 100                             | 2 |
| `#5C6B4A` | signal · success (moss)              | 6 |
| `#A8804A` | signal · warning (amber)             | 6 |
| `#8B3A2E` | signal · danger (oxblood)            | 6 |
| `rgba(30,26,24,0.08)` | `--border` hairline           | 11 |
| `rgba(30,26,24,0.14)` | `--border-strong`             | 9 |
| `rgba(30,26,24,0.03)` | chip inner stroke             | 1 |
| `rgba(30,26,24,0.04)` | shadow base                   | 4 |
| `rgba(30,26,24,0.05)` | shadow mid                    | 1 |
| `rgba(30,26,24,0.12)` | shadow heavy                  | 1 |
| `rgba(123,85,68,0.28)` | `--border-accent`            | 1 |
| `rgba(123,85,68,0.3)` | inline-link underline         | 1 (type.html prose) |
| `#2C3E63` | avatar filler (people chips)         | 1 (dashboard) |
| `#EEF1E7` | moss tint (spec only)                | 1 (colors.html) |
| `#F5EBD9` | amber tint (spec only)               | 1 (colors.html) |
| `#F3E0DC` | oxblood tint (spec only)             | 1 (colors.html) |

---

## 2 · SPACING (unique padding / margin / gap values, px)

| px      | Token candidate | Count | Principal uses |
|---------|-----------------|-------|----------------|
| 0       | –               | many  | reset |
| 1       | hairline        | many  | borders, dividers |
| 2       | –               | 8     | micro gaps in stacked labels |
| 4       | `space-1`       | ~20   | icon↔label, dot spacing |
| 6       | –               | 6     | chip dot↔label |
| 8       | `space-2`       | ~35   | inline gap, chip gap |
| 10      | (off-ramp)      | 9     | ad-hoc card padding, bubble padding |
| 12      | `space-3`       | ~40   | related stack, padding |
| 14      | (off-ramp)      | 8     | input padding, margin-notes |
| 16      | `space-4`       | ~55   | default gap |
| 18      | (off-ramp)      | 2     | bubble padding |
| 20      | (off-ramp)      | 18    | card padding (mobile), page gutter |
| 24      | `space-5`       | ~50   | card padding, form gap |
| 28      | (off-ramp)      | 10    | section lead padding |
| 32      | `space-6`       | ~30   | section internal gap |
| 40      | (off-ramp)      | 6     | intro margin-bottom |
| 48      | `space-7`       | ~18   | block separation / desktop gutter |
| 56      | (off-ramp)      | 4     | hero to content |
| 64      | `space-8`       | ~20   | major section break |
| 80      | (off-ramp)      | 3     | page-lead bottom margin |
| 88      | (off-ramp)      | 2     | v1 main padding |
| 96      | `space-9`       | ~15   | page top breathing |
| 128     | `space-10`      | ~6    | editorial pause |

---

## 3 · TYPOGRAPHY (size / line-height / weight / family combos)

Serif = EB Garamond. Sans = Red Hat Text.

| Role         | Size | Line-ht | Weight | Style   | Family | Files |
|--------------|------|---------|--------|---------|--------|-------|
| Display      | 72   | 0.98    | 400    | italic  | serif  | foundations |
| Display · B  | 64   | 1.02    | 400    | upright | serif  | type.html |
| H1           | 56   | 1.05    | 400    | upright | serif  | type / colors / wordmark |
| H1 · B       | 48   | 1.08    | 400    | italic  | serif  | foundations, components |
| H1 · C       | 52   | 1.05    | 400    | upright | serif  | dashboard gate, v3 |
| H1 · D       | 44   | 1.08    | 400    | upright | serif  | type row, v1 letter |
| H2           | 36   | 1.10    | 400    | upright | serif  | type, colors, wordmark |
| H2 · B       | 36   | 1.10    | 400    | italic  | serif  | foundations/components |
| H2 · C       | 34   | 1.10    | 400    | upright | serif  | wordmark section |
| H2 · D       | 32   | 1.12    | 400    | upright | serif  | type row |
| H3           | 26   | 1.24    | 400    | italic  | serif  | foundations |
| H3 · B       | 24   | 1.10    | 400    | upright | serif  | v3 page |
| H3 · C       | 22   | 1.25    | 500    | upright | serif  | type row, strips |
| H3 · D       | 20   | 1.30    | 500    | upright | serif  | rules, wordmark |
| H4 · card    | 20   | 1.24    | 400    | italic  | serif  | components, foundations |
| H4 · card B  | 17   | 1.2     | 500    | upright | serif  | v1 card, v2 promises |
| H4 · card C  | 15   | 1.35    | 600    | upright | sans   | type.html row |
| Lead         | 18   | 1.65    | 400    | upright | sans   | foundations, components |
| Lead · B     | 17   | 1.60    | 400    | upright | sans   | type / colors / wordmark |
| Body         | 16   | 1.50    | 400    | upright | sans   | universal |
| Body · B     | 16   | 1.55    | 400    | upright | sans   | type / colors |
| Body · C     | 16   | 1.65    | 400    | upright | sans   | type / colors |
| Body · serif | 19   | 1.60    | 400    | upright | serif  | v1 letter body |
| Small        | 15   | 1.70    | 400    | upright | sans   | rule body |
| Small · B    | 14   | 1.50    | 400    | upright | sans   | meta |
| Small · C    | 14   | 1.55    | 400    | upright | sans   | meta |
| Caption      | 13   | 1.50    | 400    | upright | sans   | rule code |
| Caption · B  | 12   | 1.50    | 400    | upright | sans   | meta |
| Micro label  | 11   | 1.0     | 500    | caps    | sans   | universal (tracking 0.14em) |
| Micro · B    | 10   | 1.0     | 500    | caps    | sans   | dashboard dow, side-nav |
| Button       | 15   | 1.0     | 500    | upright | sans   | components, type |
| Button · sm  | 13   | 1.0     | 500    | upright | sans   | dashboard |
| Wordmark     | —    | —       | 400    | italic  | serif  | `wordmark` (docs.css, tokens.css) |
| Wordmark · B | —    | —       | 500    | italic  | serif  | `wordmark.html` locked spec |

Letter-spacing values observed: `-0.035em`, `-0.03em`, `-0.025em`, `-0.02em`, `-0.015em`, `-0.01em`, `-0.005em`, `0`, `0.002em`, `0.02em`, `0.12em`, `0.14em`.

---

## 4 · BORDER-RADIUS

| px   | Token       | Count | Uses |
|------|-------------|-------|------|
| 0    | —           | many  | hairlines |
| 3    | (off-ramp)  | 4     | inline code rounding |
| 4    | `radius-xs` | 10    | chip inner, small pressed |
| 5    | (off-ramp)  | 3     | dashboard nav item |
| 6    | `radius-sm` | 22    | buttons, inputs |
| 8    | (off-ramp)  | 4     | dashboard composer |
| 10   | `radius-md` | 15    | cards, viewport frame |
| 14   | (off-ramp)  | 2     | chat bubble asymmetric |
| 16   | `radius-lg` | 6     | large cards, modals |
| 24   | `radius-xl` | 2     | hero surfaces |
| 999  | `radius-full` | 18 | chips, dots, avatars |

---

## 5 · BOX-SHADOW

| Value                                                                                | Token      | Count |
|--------------------------------------------------------------------------------------|------------|-------|
| `none`                                                                               | `shadow-0` | default |
| `0 1px 2px rgba(30,26,24,0.04)`                                                      | `shadow-1` | 1 |
| `0 2px 8px rgba(30,26,24,0.05), 0 1px 2px rgba(30,26,24,0.04)`                       | `shadow-2` | 2 |
| `0 8px 24px rgba(30,26,24,0.08), 0 2px 4px rgba(30,26,24,0.04)`                      | `shadow-3` | 2 |
| `0 20px 48px rgba(30,26,24,0.12), 0 4px 8px rgba(30,26,24,0.04)`                     | `shadow-4` | 1 |

---

## 6 · TRANSITIONS & MOTION

| Duration | Token            | Count |
|----------|------------------|-------|
| 160ms    | `duration-fast`  | ~12 (hover, btn) |
| 280ms    | `duration-normal`| 8 |
| 480ms    | `duration-slow`  | 3 |
| 720ms    | `duration-page`  | 0 (declared, unused) |
| 1.6s     | (animation)      | 3 (pulse, breath) |

| Easing                                | Token             |
|---------------------------------------|-------------------|
| `cubic-bezier(0.22, 1, 0.36, 1)`      | `ease-out` · default |
| `cubic-bezier(0.65, 0, 0.35, 1)`      | `ease-in-out` |
| `cubic-bezier(0.2, 0.8, 0.2, 1)`      | `ease-editorial` |

---

## 7 · Z-INDEX
None declared in any source file. System has no stacking contexts defined — **GAP**: flag if modals / popovers / toasts ship.

---

## 8 · INCONSISTENCIES (flagged, not resolved)

These are values that serve the same semantic purpose but differ across files. Each one needs a rule.

### 8.1 · Serif page titles: upright vs italic
Three files set H1/H2/Display in **italic serif** (foundations, components, patterns, old wordmark lockup).
Four files set them in **upright serif** (type, colors, wordmark-locked, dashboard gate, v3 page).
`type.html · section 04 · Before/After` explicitly says upright wins.
Rule needed.

### 8.2 · Card title styling
Three conflicting specs exist:
- `.card-title` (components.html): serif italic 400 at 20/1.24
- `.v1 .card h3` (dashboard): serif upright 500 at 17
- `.s-h4` (type.html row): **sans 600 at 15** — flagged in Before/After as the correction.
Rule needed.

### 8.3 · Placeholder text
- `components.html .composer textarea::placeholder` sets it **serif italic 17px**.
- `type.html section 04` says placeholder must be **sans upright 16px**.
Same token, opposite rules.

### 8.4 · Her messages / chat bubbles
- `components.html .bubble.from-donna`: serif italic 18px, hairline rule
- `type.html section 04`: sans 15px, hairline rule
Same component, two specs.

### 8.5 · Wordmark weight + dot
- `assets/tokens.css .wordmark` + `docs.css .ds-nav-brand`: weight **400**, **dot appended as `::after`**
- `system/wordmark.html` (Locked · final): weight **500**, **no dot, no decoration**
Three places in the project still render the dot (`docs.css`, `tokens.css`, `index.html` cover title uses a rust span).
Wordmark spec locks no-dot; the docs chrome contradicts it.

### 8.6 · Card padding
- foundations rules: 24 mobile / 32 desktop
- `components.html .card`: 24 (space-5) on all
- `wordmark.html .pair`: 56 / 28
- `dashboard v1-main`: 88 / 64
- `v2 .col-main`: 40 / 56
The rule "24 mobile, 32 desktop" is violated inside the dashboard variants themselves. Rule needed for "canvas" vs "card" padding.

### 8.7 · Letter-spacing on headings
Four different tightness settings for serif headings: `-0.035`, `-0.025`, `-0.02`, `-0.015`. No consistent mapping to size. Rule needed.

### 8.8 · Spacing off-ramp values
Eight values appear that are not on the 4px/semantic scale: **10, 14, 18, 20, 28, 40, 56, 80, 88**. Most are in dashboard variants. Canonical scale has 4/8/12/16/24/32/48/64/96/128 — these need to be pulled onto the scale.

### 8.9 · Border radius `3px` and `5px`
Two values outside the system: `border-radius:3px` for inline code, `border-radius:5px` for dashboard nav li. Both ad-hoc, both removable.

### 8.10 · Body line-heights
Same "body" role ships at `1.5`, `1.55`, and `1.65` across files. Tokens declare `--lh-normal:1.5` and `--lh-relaxed:1.65`. `1.55` is not a token. Rule needed: which line-height is the default for body at 16px.

### 8.11 · Avatar `#2C3E63`
One blue avatar background appears inside `screens/dashboard.html`. It is the only cool color anywhere in the system and has no declared role. **Remove, or name it.**

### 8.12 · `--signal-info`
Declared in `tokens.css` as `--ink-500` (a bare custom-property reference, not wrapped in `var(...)`). This is a broken declaration — ships as a literal string. Must fix.

### 8.13 · `700` sans weight
`type.html` says "700 only for tabular numerals", but tokens/components load `700` via Google Fonts and never use it. `components.html` explicitly forbids it ("never 700 in product UI"). Conflict; resolve to: load 700 only if tabular numerals need it.

### 8.14 · Dashboard `v2 .col-nav .people`: `gap:-6px` then `gap:4px`
Invalid CSS (`gap:-6px`). Silently ignored. Bug.

### 8.15 · Duplicate pages for the same concept
- `foundations.html` (old, italic-heavy) and `type.html` + `colors.html` (new, upright, locked) both exist.
- `wordmark.html` (no-dot locked), `wordmark-d.html`, `wordmark-colors.html` — three wordmark explorations.
- `mobile-dashboard.html` + `mobile-dashboard.jsx` + `ios-frame.jsx` — one shipped, two scaffolds.
Resolution: `type.html`, `colors.html`, `wordmark.html` are the locked sources; older files must be demoted to `/archive/`.
