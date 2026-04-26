# CLAUDE.md

Read this file first on every task. Always.

## Project

This is **Donna** — a quiet, warm AI companion product. Every pixel is opinionated.

## Before you write any UI code

1. Read `DESIGN_SYSTEM.md` in full. It is the gospel.
2. Read `components.md` for the component contracts.
3. Use only tokens from `tokens.css` / `tokens.json` / `tailwind.config.js`.
4. Compose with components from `components/index.tsx`. Do not restyle them.

## Non-negotiables (if any of these show up in your output, fix it before claiming done)

- **No raw hex colors** anywhere. Use tokens.
- **No arbitrary Tailwind values** like `text-[17px]` or `bg-[#abc]`. The scale is closed.
- **One rust moment per screen.** Exactly one. Runtime warning in dev if exceeded.
- **Italic only in the three approved contexts** (see `DESIGN_SYSTEM.md` §3).
- **No drop-shadows on cards at rest.** Only modals/toasts/popovers have shadow.
- **No serif weight 700.** Not in code, not in CSS, not anywhere.
- **Upright sans for placeholders.** Never italic, never serif.
- **Section labels are always rust and uppercase.** Use `<Label>`.
- **No gradients.** Ever.
- **Below 14px, the wordmark is the "d" monogram, not the word.** The `Wordmark` component enforces this.

## When you're asked to build a new page

Default structure:

```tsx
import { ScreenRoot, Heading, Accent, Label, Card, Button, Input, Chip } from '@/components';

export default function SomePage() {
  return (
    <ScreenRoot>
      <main className="bg-paper min-h-screen p-8 max-w-3xl mx-auto">
        <Label>TODAY · 8:14</Label>
        <Heading level={1} className="mt-2">
          Good morning, <Accent>Arnav</Accent>.
        </Heading>

        <Card className="mt-7">
          <Heading level={4}>This week with Maya</Heading>
          <p className="font-sans text-body text-ink mt-2">
            You said you'd pick up the frame from Oscar's before Thursday.
          </p>
        </Card>

        {/* ONE primary button per screen — it IS the rust moment */}
        <Button variant="primary" className="mt-5">Keep it for me</Button>
      </main>
    </ScreenRoot>
  );
}
```

## When you're asked to add a new color / font / size

**The answer is almost certainly no.** The palette, type scale, and space scale are closed.

- Want a new color? → use a scale step (e.g. `rust-300`) or a signal token.
- Want a new font-size? → use the nearest role (`type-h4`, `type-body`, etc.). If nothing fits, the design is wrong.
- Want a new shadow? → you don't. Use `bg-surface` or a hairline.

If you truly, genuinely believe the system needs a new value, stop and flag it to the human. Do not add it unilaterally.

## Pre-commit checks (run before declaring done)

```bash
npx stylelint "src/**/*.{css,tsx,jsx}"     # catches raw hex, forbidden shadows, gradients
npx eslint "src/**/*.{ts,tsx}"             # catches arbitrary tailwind, italic misuse
```

Both should pass with zero warnings.

## Tone in copy

Donna does not apologize, does not perform warmth, does not exclaim.

- ✅ "Noted."
- ❌ "Got it! I've saved that for you! 🎉"

Copy is one step quieter than you think it should be. Short sentences. Lowercase where possible without being precious.

## Forbidden phrases in UI copy

- "Oops!" / "Uh oh!" / "Whoops!"
- "Great!" / "Awesome!" / "Perfect!"
- "Let me..." / "I'll go ahead and..."
- Emoji in UI chrome (allowed in user content only)
- Exclamation marks in system messages (user messages can use them)
