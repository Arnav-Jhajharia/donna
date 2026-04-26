# Donna Design System

The machine-readable version of the three locked PDFs (Colors, Type, Wordmark).

## File hierarchy · what each file is for

```
donna-design-system/
├── CLAUDE.md            ← Read FIRST. Claude Code entry point.
├── DESIGN_SYSTEM.md     ← The gospel. All rules, with examples.
├── components.md        ← Component contracts (props, variants, forbidden states).
├── tokens.css           ← CSS custom properties + type utility classes.
├── tokens.json          ← Machine-readable token mirror (for tooling).
├── tailwind.config.js   ← Drop-in Tailwind config mapped to tokens.
├── components/index.tsx ← Reference React components. Import from here.
├── .stylelintrc.json    ← Enforces no raw hex, no forbidden shadows, no gradients.
└── eslint-plugin-donna.js ← Custom ESLint rules for JSX/TS.
```

## How it becomes gospel (the enforcement story)

Rules in prose get ignored. Rules in code don't. Here's how this system prevents drift:

1. **Claude Code reads `CLAUDE.md` on every task** → it gets the non-negotiables up front.
2. **Tailwind config replaces (not extends) colors/fonts/sizes** → arbitrary classes like `text-[17px]` or `bg-[#abc]` literally cannot be written.
3. **Stylelint blocks raw hex in CSS/JSX** → the palette cannot be extended accidentally.
4. **ESLint `donna/*` rules catch italic misuse, inline font-size, inline shadow, arbitrary Tailwind** → these get caught in CI, not in review.
5. **Runtime `ScreenRoot` counts rust moments** → dev console warns if a screen exceeds one rust moment.
6. **`Wordmark` component falls back to "d" monogram below 14px** → the size rule cannot be violated in code.

## Getting started (in a new repo)

```bash
# copy files into project root
cp CLAUDE.md DESIGN_SYSTEM.md components.md /path/to/project/
cp tokens.css tokens.json tailwind.config.js /path/to/project/
cp -r components /path/to/project/
cp .stylelintrc.json eslint-plugin-donna.js /path/to/project/

# install lint deps
npm i -D stylelint stylelint-config-standard stylelint-declaration-strict-value eslint

# import tokens at app root
# in src/index.tsx or app/globals.css:
@import './tokens.css';
```

In your `.eslintrc`:
```json
{
  "plugins": ["donna"],
  "rules": {
    "donna/no-raw-hex": "error",
    "donna/no-inline-font-size": "error",
    "donna/no-inline-box-shadow": "error",
    "donna/no-arbitrary-tailwind": "error",
    "donna/no-italic-class": "error"
  }
}
```

## What to do when the system feels wrong

The system is opinionated on purpose. If a design requirement forces you to violate a rule, **stop and flag it**. Do not extend the system unilaterally. Either:

1. The requirement is wrong → push back on product.
2. The requirement is right and the system needs to evolve → that's a system-wide design review, not a code change.

The palette is closed. The type scale is closed. The wordmark is locked. That is a feature.

---

*v1.0.0 · Locked · Paper, ink, and one moment of rust.*
