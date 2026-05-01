/**
 * FooterBlock — catalogue archetype #03.
 *
 * Sign-off. Last visible block on every plan. Not interactive. Three flavors:
 *
 *   caps   — uppercase tracked status line. the default.
 *            good when the plan ends on a quiet beat.
 *   italic — serif italic line. warmest. for "that's the day. sleep well."
 *   mark   — the donna mark with hairline rules. for the morning hero plan
 *            and any "this is the start" moment.
 */

import type { FooterBlock as FooterSpec } from '@/lib/plan';

export default function FooterBlock({ spec }: { spec: FooterSpec }) {
  const kind = spec.kind ?? 'caps';

  if (kind === 'italic') {
    return (
      <div style={{ textAlign: 'center', padding: '20px 0 12px' }}>
        <span
          style={{
            fontFamily: 'var(--font-serif, "EB Garamond", Georgia, serif)',
            fontStyle: 'italic',
            fontSize: 15,
            color: 'var(--ink-600)',
          }}
        >
          {spec.text}
        </span>
      </div>
    );
  }

  if (kind === 'mark') {
    return (
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          gap: 10,
          padding: '20px 0 12px',
        }}
      >
        <div style={{ width: 18, height: 1, background: 'rgba(30,26,24,0.08)' }} />
        <span
          style={{
            fontFamily: 'var(--font-serif, "EB Garamond", Georgia, serif)',
            fontStyle: 'italic',
            fontWeight: 500,
            fontSize: 16,
            color: 'var(--ink-900)',
            letterSpacing: '-0.01em',
            display: 'inline-flex',
            alignItems: 'baseline',
            gap: 2,
          }}
        >
          donna
          <span
            style={{
              width: 4,
              height: 4,
              borderRadius: 999,
              background: 'var(--rust-700)',
              transform: 'translateY(-1px)',
            }}
          />
        </span>
        <div style={{ width: 18, height: 1, background: 'rgba(30,26,24,0.08)' }} />
      </div>
    );
  }

  // caps — the default
  return (
    <div
      style={{
        textAlign: 'center',
        fontSize: 11,
        letterSpacing: '0.14em',
        textTransform: 'uppercase',
        color: 'var(--fg-placeholder)',
        fontWeight: 500,
        padding: '16px 0 8px',
      }}
    >
      {spec.text}
    </div>
  );
}
