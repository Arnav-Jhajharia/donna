/**
 * Catalogue iconography — outlined hairline glyphs from the design system.
 * Ported verbatim from the catalogue's `I.*` set so visual treatment matches.
 */

interface IconProps {
  s?: number;
  c?: string;
}

const def = (s = 16, c = 'var(--ink-700)') => ({ s, c });

export const cIcons = {
  drop: ({ s, c }: IconProps = {}) => {
    const p = def(s, c);
    return (
      <svg width={p.s} height={p.s} viewBox="0 0 24 24" fill="none">
        <path d="M12 3c-4 5-6 8-6 11a6 6 0 0012 0c0-3-2-6-6-11z" stroke={p.c} strokeWidth="1.4" strokeLinejoin="round"/>
      </svg>
    );
  },
  flame: ({ s, c }: IconProps = {}) => {
    const p = def(s, c);
    return (
      <svg width={p.s} height={p.s} viewBox="0 0 24 24" fill="none">
        <path d="M12 3c1 3 4 4 4 8a4 4 0 01-8 0c0-2 1-3 2-4-1 0-2-1-2-2 0 0 3 0 4-2z" stroke={p.c} strokeWidth="1.4" strokeLinejoin="round"/>
      </svg>
    );
  },
  rupee: ({ s, c }: IconProps = {}) => {
    const p = def(s, c);
    return (
      <svg width={p.s} height={p.s} viewBox="0 0 24 24" fill="none">
        <path d="M7 5h10M7 9h10M9 5c3 0 5 2 5 4s-2 4-5 4H7l7 6" stroke={p.c} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
      </svg>
    );
  },
  envelope: ({ s, c }: IconProps = {}) => {
    const p = def(s, c);
    return (
      <svg width={p.s} height={p.s} viewBox="0 0 24 24" fill="none">
        <rect x="3" y="6" width="18" height="14" rx="1.5" stroke={p.c} strokeWidth="1.4"/>
        <path d="M3 8l9 7 9-7" stroke={p.c} strokeWidth="1.4"/>
      </svg>
    );
  },
  eye: ({ s, c }: IconProps = {}) => {
    const p = def(s, c);
    return (
      <svg width={p.s} height={p.s} viewBox="0 0 24 24" fill="none">
        <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" stroke={p.c} strokeWidth="1.4"/>
        <circle cx="12" cy="12" r="3" stroke={p.c} strokeWidth="1.4"/>
      </svg>
    );
  },
  book: ({ s, c }: IconProps = {}) => {
    const p = def(s, c);
    return (
      <svg width={p.s} height={p.s} viewBox="0 0 24 24" fill="none">
        <path d="M4 4h7v16H4zM13 4h7v16h-7zM4 4c2 1 5 1 7 0M13 4c2 1 5 1 7 0" stroke={p.c} strokeWidth="1.4" strokeLinejoin="round"/>
      </svg>
    );
  },
  link: ({ s, c }: IconProps = {}) => {
    const p = def(s, c);
    return (
      <svg width={p.s} height={p.s} viewBox="0 0 24 24" fill="none">
        <path d="M14 4h6v6M20 4l-9 9M10 6H5v13h13v-5" stroke={p.c} strokeWidth="1.4" strokeLinejoin="round"/>
      </svg>
    );
  },
  chev: ({ s, c }: IconProps = {}) => {
    const p = def(s, c);
    return (
      <svg width={p.s} height={p.s} viewBox="0 0 16 16" fill="none">
        <path d="M6 3l5 5-5 5" stroke={p.c} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
      </svg>
    );
  },
  check: ({ s, c }: IconProps = {}) => {
    const p = def(s, c);
    return (
      <svg width={p.s} height={p.s} viewBox="0 0 16 16" fill="none">
        <path d="M3 8l3 3 7-7" stroke={p.c} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
      </svg>
    );
  },
  plug: ({ s, c }: IconProps = {}) => {
    const p = def(s, c);
    return (
      <svg width={p.s} height={p.s} viewBox="0 0 24 24" fill="none">
        <path d="M9 3v6M15 3v6M6 9h12v3a6 6 0 11-12 0z M12 18v3" stroke={p.c} strokeWidth="1.4" strokeLinejoin="round"/>
      </svg>
    );
  },
  coffee: ({ s, c }: IconProps = {}) => {
    const p = def(s, c);
    return (
      <svg width={p.s} height={p.s} viewBox="0 0 24 24" fill="none">
        <path d="M4 9h13v6a4 4 0 01-4 4H8a4 4 0 01-4-4z" stroke={p.c} strokeWidth="1.4" strokeLinejoin="round"/>
        <path d="M17 11h2a2 2 0 110 4h-2M8 4v2M11 3v3M14 4v2" stroke={p.c} strokeWidth="1.4" strokeLinecap="round"/>
      </svg>
    );
  },
  bowl: ({ s, c }: IconProps = {}) => {
    const p = def(s, c);
    return (
      <svg width={p.s} height={p.s} viewBox="0 0 24 24" fill="none">
        <path d="M3 11h18a9 9 0 01-18 0z" stroke={p.c} strokeWidth="1.4" strokeLinejoin="round"/>
        <path d="M8 8c0-1 1-2 2-2m3 2c0-1 1-2 2-2" stroke={p.c} strokeWidth="1.4" strokeLinecap="round"/>
      </svg>
    );
  },
  moon: ({ s, c }: IconProps = {}) => {
    const p = def(s, c);
    return (
      <svg width={p.s} height={p.s} viewBox="0 0 24 24" fill="none">
        <path d="M20 14a8 8 0 01-10-10 8 8 0 1010 10z" stroke={p.c} strokeWidth="1.4" strokeLinejoin="round"/>
      </svg>
    );
  },
  heart: ({ s, c }: IconProps = {}) => {
    const p = def(s, c);
    return (
      <svg width={p.s} height={p.s} viewBox="0 0 24 24" fill="none">
        <path d="M12 20s-7-4.5-7-10a4 4 0 017-2.5A4 4 0 0119 10c0 5.5-7 10-7 10z" stroke={p.c} strokeWidth="1.4" strokeLinejoin="round"/>
      </svg>
    );
  },
};

export type CatIconName = keyof typeof cIcons;
