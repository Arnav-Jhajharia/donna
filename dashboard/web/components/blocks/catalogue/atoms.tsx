/** Shared atoms used by every catalogue block. */

import type { CSSProperties, ReactNode } from 'react';

export const SERIF = 'var(--font-serif, "EB Garamond", Georgia, serif)';
export const SANS = 'var(--font-sans, "Red Hat Text", -apple-system, sans-serif)';
export const BORDER = 'rgba(30,26,24,0.08)';
export const BORDER_STRONG = 'rgba(30,26,24,0.14)';
export const BORDER_ACCENT = 'rgba(123,85,68,0.28)';

export function Eyebrow({
  children,
  tone = 'var(--ink-500)',
  style,
}: {
  children: ReactNode;
  tone?: string;
  style?: CSSProperties;
}) {
  return (
    <div
      style={{
        fontSize: 9.5,
        letterSpacing: '0.14em',
        textTransform: 'uppercase',
        color: tone,
        fontWeight: 500,
        fontFamily: SANS,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

export function SectionHead({
  title,
  right,
  italic = false,
  tone = 'var(--ink-900)',
}: {
  title: string;
  right?: string;
  italic?: boolean;
  tone?: string;
}) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
        paddingBottom: 8,
        borderBottom: `1px solid ${BORDER}`,
      }}
    >
      <h3
        style={{
          margin: 0,
          fontFamily: SERIF,
          fontWeight: 500,
          fontSize: 18,
          letterSpacing: '-0.01em',
          color: tone,
          fontStyle: italic ? 'italic' : 'normal',
        }}
      >
        {title}
      </h3>
      {right && (
        <span style={{ fontFamily: SANS, fontSize: 12, color: 'var(--ink-500)' }}>{right}</span>
      )}
    </div>
  );
}
