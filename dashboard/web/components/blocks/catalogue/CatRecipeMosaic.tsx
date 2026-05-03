'use client';

import { motion } from 'framer-motion';
import { buildWaUrl } from '@/lib/wa-deeplink';
import type { CatRecipeMosaicSpec, RecipeItem } from '@/lib/plan';

/**
 * Recipe invitation — two variants for two moments in the user's life.
 *
 *   variant=mosaic (default, Day 1 cover)
 *   ──────────────────────────────────────
 *   The InvitationPromptBlock pattern from
 *   donna-design-system/components.md:527 (the spec's day 1 /
 *   cold-start primitive): <Label> eyebrow + serif heading w/ rust
 *   italic accent + fake text input + hint chips.
 *
 *   variant=chips (Page 2 mind-rail footer, established users)
 *   ──────────────────────────────────────────────────────────
 *   Compact horizontal pill row. No fake-input chrome; just an eyebrow
 *   + a one-line heading + chips. Used when the user already has
 *   signal but might want more — "more I could run for you."
 *
 * Every spec field carries forward:
 *   eyebrow → <Label> caps rust
 *   title   → heading sentence (asterisks=*verb* become rust italic accent)
 *   items[].title  → chip label
 *   items[].primer → message sent on tap
 */

function HintChip({ item, idx }: { item: RecipeItem; idx: number }) {
  const href = buildWaUrl(item.primer);
  return (
    <motion.a
      href={href}
      target="_blank"
      rel="noreferrer"
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: 0.32,
        delay: 0.18 + idx * 0.05,
        ease: [0.22, 1, 0.36, 1],
      }}
      whileHover={{ backgroundColor: 'var(--paper-100, #f5f0e3)' }}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '7px 14px',
        background: 'transparent',
        border: '1px solid var(--ink-300, #c2bdb1)',
        borderRadius: 999,
        textDecoration: 'none',
        cursor: 'pointer',
        fontFamily: 'var(--font-sans, "Red Hat Text", system-ui)',
        fontSize: 12.5,
        lineHeight: 1.3,
        color: 'var(--ink-500, #6b6b6b)',
        letterSpacing: '-0.005em',
        whiteSpace: 'nowrap',
      }}
    >
      {item.title}
    </motion.a>
  );
}

export function CatRecipeMosaic({ spec }: { spec: CatRecipeMosaicSpec }) {
  if (spec.variant === 'chips') {
    return <RecipeChipsRow spec={spec} />;
  }
  return <RecipeMosaicCover spec={spec} />;
}

/** Day 1 cover variant — InvitationPromptBlock with fake input + chips. */
function RecipeMosaicCover({ spec }: { spec: CatRecipeMosaicSpec }) {
  // The heading splits into ``before`` + accent verb + ``after``. We
  // pull the verb from spec.title using a sentinel pattern: anything
  // wrapped in *asterisks* becomes the rust italic accent. Falls back
  // to a sensible default sentence if the title is plain.
  const { before, accent, after } = parseAccent(
    spec.title || 'do something *real* for you.',
  );

  return (
    <section style={{ margin: '20px 22px 0' }}>
      <header style={{ paddingBottom: 12 }}>
        <div
          style={{
            fontSize: 10,
            letterSpacing: '0.18em',
            textTransform: 'uppercase',
            color: 'var(--rust-700, #6a3a08)',
            fontWeight: 500,
            marginBottom: 6,
          }}
        >
          {spec.eyebrow || 'ask me to'}
        </div>
        <h3
          style={{
            fontFamily: 'var(--font-serif, "EB Garamond", Georgia, serif)',
            fontWeight: 400,
            fontSize: 22,
            lineHeight: 1.2,
            color: 'var(--ink-900, #1E1A18)',
            margin: 0,
            letterSpacing: '-0.015em',
          }}
        >
          {before}
          <em
            style={{
              fontStyle: 'italic',
              fontWeight: 500,
              color: 'var(--rust-700, #6a3a08)',
            }}
          >
            {accent}
          </em>
          {after}
        </h3>
      </header>

      {/* Fake text input — teaches "this is a chat surface" affordance.
          Not a real input; the chips below are the real CTAs. */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.4, delay: 0.05 }}
        aria-hidden
        style={{
          background: 'var(--paper-50, #fbf8f0)',
          border: '1px solid var(--ink-300, #c2bdb1)',
          borderRadius: 4,
          padding: '11px 14px',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          fontFamily: 'var(--font-sans, "Red Hat Text", system-ui)',
          fontSize: 13.5,
          color: 'var(--ink-400, #9a9a9a)',
          fontStyle: 'normal',
        }}
      >
        <span>tap one to send →</span>
        <motion.span
          animate={{ opacity: [1, 0, 1] }}
          transition={{ duration: 1.1, repeat: Infinity, ease: 'easeInOut' }}
          style={{
            display: 'inline-block',
            width: 1.5,
            height: 14,
            background: 'var(--ink-700, #4a4a4a)',
            marginLeft: 1,
          }}
        />
      </motion.div>

      <div
        style={{
          marginTop: 14,
          display: 'flex',
          flexWrap: 'wrap',
          gap: 8,
        }}
      >
        {spec.items.map((item, i) => (
          <HintChip key={`${item.title}-${i}`} item={item} idx={i} />
        ))}
      </div>
    </section>
  );
}

/** Compact chips variant — Page 2 footer for established users.
 *
 *  No fake-input chrome (the user already knows donna is a chat surface).
 *  Just a tiny eyebrow + a quiet one-line heading + a horizontal pill
 *  row that wraps on mobile. Designed to read as "by the way, more I
 *  could run for you" rather than the day-1 hero invitation. */
function RecipeChipsRow({ spec }: { spec: CatRecipeMosaicSpec }) {
  return (
    <section style={{ margin: '14px 22px 0' }}>
      <header style={{ paddingBottom: 8 }}>
        <div
          style={{
            fontSize: 10,
            letterSpacing: '0.18em',
            textTransform: 'uppercase',
            color: 'var(--ink-500, #6b6b6b)',
            fontWeight: 500,
          }}
        >
          {spec.eyebrow || 'more i could run'}
        </div>
        {spec.title && (
          <p
            style={{
              fontFamily: 'var(--font-serif, "EB Garamond", Georgia, serif)',
              fontStyle: 'italic',
              fontSize: 14,
              lineHeight: 1.4,
              color: 'var(--ink-500, #6b6b6b)',
              margin: '4px 0 0',
            }}
          >
            {spec.title}
          </p>
        )}
      </header>
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 6,
        }}
      >
        {spec.items.map((item, i) => (
          <HintChip key={`${item.title}-${i}`} item={item} idx={i} />
        ))}
      </div>
    </section>
  );
}

/** Parse `*verb*` sentinels out of a sentence into the three pieces
 *  the heading needs. If no asterisks present, italicises the first word. */
function parseAccent(s: string): { before: string; accent: string; after: string } {
  const m = s.match(/^(.*?)\*(.+?)\*(.*)$/);
  if (m) {
    return { before: m[1], accent: m[2], after: m[3] };
  }
  // No sentinel — italicise the first word as a fallback.
  const [first, ...rest] = s.split(' ');
  return { before: '', accent: first, after: rest.length ? ' ' + rest.join(' ') : '' };
}
