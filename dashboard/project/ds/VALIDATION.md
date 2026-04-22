# VALIDATION.md
How to check the system holds. Run these before merging anything that touches tokens, primitives, or a shipped page.

---

## 1 · Token hygiene

### 1.1 · No raw hex outside `ds/tokens.css`

```bash
grep -rnE '#[0-9A-Fa-f]{3,6}' ds/ system/ screens/ \
  --exclude='tokens.css' \
  --include='*.css' --include='*.html' --include='*.jsx'
```

Expected: **0 matches.** Any hit means a component is bypassing the token layer.

### 1.2 · No off-scale spacing

```bash
grep -rnE '(padding|margin|gap)[^;]*\b(10|14|18|20|28|40|56|80|88)px' system/ screens/ ds/
```

Expected: **0 matches.**

### 1.3 · No stray radii

```bash
grep -rnE 'border-radius:\s*(3|5|7|9|11|12|14|20)px' system/ screens/ ds/
```

Expected: **0 matches.**

### 1.4 · No deprecated tokens

```bash
grep -rn -E '(--signal-info|\.wordmark::after|font-weight:\s*700)' .
```

Expected: **0 matches** in `ds/`, `system/`, or `screens/`. Matches in `assets/` (legacy) are acceptable only while `/archive/` exists.

---

## 2 · Type rules

### 2.1 · Upright serif headings (R-T1)

```bash
grep -rnE 'font-family:[^;]*(Garamond|--font-serif)[^}]*font-style:\s*italic' system/ screens/ ds/
```

Expected: italic + serif only on wordmark, `.is-italic`, `blockquote`, `em`, or explicit marginalia.

### 2.2 · No italic serif placeholders (R-T2, §2.4)

```bash
grep -rnE '::placeholder[^}]*font-style:\s*italic' .
```

Expected: **0 matches.**

### 2.3 · Card titles are sans 600 (R-T2, §2.3)

Card-title selectors (`.card h3`, `.card-title`, `h4`) must resolve to `font-family: var(--font-sans)` + `font-weight: var(--weight-semi)`. Spot-check by rendering `ds/index.html` and inspecting a card.

---

## 3 · Color rules

### 3.1 · One rust per screen (R-C1)

For each shipped page:

1. Load in a browser at 1440×900.
2. Count distinct elements painted in `--fg-accent` / `--bg-accent`.
3. Expected: **≤ 1** primary brand element per viewport above the fold.

Wordmark + CTA in rust simultaneously = fail.

### 3.2 · No info blue (R-C3)

```bash
grep -rnE '#(2C3E63|1E4[0-9A-F]{3}|[0-9A-F]{0,2}7[0-9A-F]{2}[A-F]{1,3})' system/ screens/ ds/
```

Any cool hex is a fail. Replace with `--fg-muted`.

### 3.3 · Contrast (WCAG AA)

Test every semantic pairing declared in `SYSTEM.md §1 · Contrast commitments`. Use the Chrome DevTools color-picker or any AA checker. All must meet ≥ 4.5:1 for body, ≥ 3:1 for ≥18px.

---

## 4 · Wordmark

For every surface that renders "donna":

- [ ] Set in `--font-serif`
- [ ] `font-style: italic`
- [ ] `font-weight: 500`
- [ ] `letter-spacing: -0.01em`
- [ ] **No** `::after` dot, no underline, no box
- [ ] Size ≥ 14px (else use "d" monogram)
- [ ] Color: `--fg-primary`, `--fg-accent`, or `--fg-inverse`

Regression probe:

```bash
grep -rnE 'wordmark[^}]*::after' .
```

Expected: **0 matches** outside `/archive/`.

---

## 5 · Accessibility

### 5.1 · Focus visibility

Tab through every interactive element in `ds/index.html`, `system/components.html`, `screens/dashboard.html`. Each must show the `--fg-accent` outline at 2px with 2px offset.

### 5.2 · Reduced motion

Set `prefers-reduced-motion: reduce`. Every animation and transition must collapse to 0ms. Verify in DevTools → Rendering → Emulate CSS media feature.

Each component CSS file must end with:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

### 5.3 · Keyboard traps

No focus trap outside a modal. Tab must complete a loop through the page and return to the address bar.

---

## 6 · Visual regression

Screenshot these pages at 1440×900 before and after any token change:

- `ds/index.html`
- `system/type.html`
- `system/colors.html`
- `system/wordmark.html`
- `system/components.html`
- `system/patterns.html`
- `screens/dashboard.html`
- `screens/mobile-dashboard.html`

Diff. Any unintended shift is a regression.

---

## 7 · Off-system file scan

The audit flagged these for archival. Confirm they do not load in any page that's shipped:

- `system/foundations.html`
- `system/wordmark-d.html`
- `system/wordmark-colors.html`
- `screens/mobile-dashboard.jsx`
- `screens/ios-frame.jsx`

```bash
grep -rn -E 'foundations\.html|wordmark-d\.html|wordmark-colors\.html|mobile-dashboard\.jsx|ios-frame\.jsx' ds/ system/ screens/ index.html
```

Expected: only the `/archive/` redirect, nothing live.

---

## 8 · System-change checklist

Before landing any PR that touches `ds/tokens.css`:

- [ ] The change fits one of the six color families, ten spacing steps, five radii, four shadows, three durations.
- [ ] The change is documented in `SYSTEM.md` under the correct section.
- [ ] No primitive is referenced directly by a component — only semantic roles.
- [ ] The validation in §1 still passes.
- [ ] At least one page in §6 demonstrates the change intentionally.

---

## 9 · What "done" means

The system is in good standing when:

1. `§1` token-hygiene greps return 0.
2. Every page in `§6` renders cleanly with the tokens from `ds/tokens.css`.
3. The wordmark checklist in `§4` passes on every surface.
4. Contrast checks in `§3.3` all meet AA.
5. Reduced-motion behavior in `§5.2` is present.
6. No deprecated file in `§7` is referenced from a shipped path.

If any of these fail, the regression is the bug — not the system.
