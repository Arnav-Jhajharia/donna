/**
 * Gospel design-system components, ported for dashboard use.
 *
 * Source of truth: donna-design-system/components/index.tsx.
 * Ported here because the dashboard cannot directly import from that
 * folder (it's outside `next build`'s root). Keep these two files in sync
 * until we extract the design system as an installable package.
 *
 * Blocks should migrate from raw <div> + inline styles to these
 * components. See docs/design-system-audit.md (D7) for the rationale.
 */

'use client';

import React, { createContext, useContext, useEffect, useRef } from 'react';

/* ───────── Screen-level rust budget ─────────
 * One rust moment per screen is runtime-enforced in dev. Wrap
 * DashboardRenderer (or any top-level Donna surface) in <ScreenRoot> to
 * get a console.warn if a second rust element renders. */

interface RustBudgetApi {
  spend: () => void;
  peek: () => number;
}

const RustBudgetContext = createContext<RustBudgetApi | null>(null);

export function ScreenRoot({ children }: { children: React.ReactNode }) {
  const countRef = useRef(0);
  const api: RustBudgetApi = {
    spend: () => {
      countRef.current += 1;
      if (process.env.NODE_ENV !== 'production' && countRef.current > 1) {
        // eslint-disable-next-line no-console
        console.warn(
          '[donna] Rust budget exceeded: more than one rust moment on this screen. The design is wrong.',
        );
      }
    },
    peek: () => countRef.current,
  };
  useEffect(() => {
    countRef.current = 0;
  });
  return <RustBudgetContext.Provider value={api}>{children}</RustBudgetContext.Provider>;
}

function useRustBudget(): RustBudgetApi | null {
  return useContext(RustBudgetContext);
}

/* ───────── Heading ───────── */

type HeadingLevel = 1 | 2 | 3 | 4;

const HEADING_CLASS: Record<HeadingLevel, string> = {
  1: 'type-h1',
  2: 'type-h2',
  3: 'type-h3',
  4: 'type-h4',
};

interface HeadingProps {
  level: HeadingLevel;
  children: React.ReactNode;
  className?: string;
}

export function Heading({ level, children, className = '' }: HeadingProps) {
  const Tag = `h${level}` as keyof React.JSX.IntrinsicElements;
  const composed = `${HEADING_CLASS[level]}${className ? ` ${className}` : ''}`;
  return React.createElement(Tag, { className: composed, style: { color: 'var(--color-ink)', margin: 0 } }, children);
}

/* ───────── Accent (the one-word italic rust) ───────── */

export function Accent({ children }: { children: React.ReactNode }) {
  const budget = useRustBudget();
  useEffect(() => {
    budget?.spend();
  }, [budget]);
  return (
    <em
      className="italic-accent-heading"
      style={{ color: 'var(--color-rust)', fontWeight: 500 }}
    >
      {children}
    </em>
  );
}

/* ───────── Label (caps, always rust) ───────── */

export function Label({ children }: { children: React.ReactNode }) {
  return <span className="type-label">{children}</span>;
}

/* ───────── Card (three treatments) ───────── */

type CardTreatment = 'surface' | 'hairline' | 'paper';

interface CardProps {
  treatment?: CardTreatment;
  interactive?: boolean;
  children: React.ReactNode;
  className?: string;
}

const CARD_TREATMENT_STYLE: Record<CardTreatment, React.CSSProperties> = {
  surface: {
    background: 'var(--color-surface)',
    borderRadius: 'var(--radius-md)',
    padding: 'var(--space-5)',
  },
  hairline: {
    background: 'var(--color-paper)',
    border: '1px solid var(--ink-300)',
    borderRadius: 'var(--radius-md)',
    padding: 'var(--space-5)',
  },
  paper: {
    background: 'var(--color-paper)',
    padding: 'var(--space-5)',
  },
};

export function Card({ treatment = 'surface', interactive = false, children, className = '' }: CardProps) {
  const base = CARD_TREATMENT_STYLE[treatment];
  const extra = interactive && treatment === 'surface'
    ? { cursor: 'pointer', transition: 'background-color var(--duration-fast) var(--ease-out)' }
    : {};
  return (
    <article className={className} style={{ ...base, ...extra }}>
      {children}
    </article>
  );
}

/* ───────── Button (three variants) ───────── */

type ButtonVariant = 'primary' | 'secondary' | 'ghost';

const BUTTON_VARIANT_STYLE: Record<ButtonVariant, React.CSSProperties> = {
  primary: {
    background: 'var(--color-rust)',
    color: 'var(--color-paper)',
    borderColor: 'transparent',
  },
  secondary: {
    background: 'var(--color-paper)',
    color: 'var(--color-ink)',
    borderColor: 'var(--ink-300)',
  },
  ghost: {
    background: 'transparent',
    color: 'var(--color-ink)',
    borderColor: 'transparent',
  },
};

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  tone?: 'default' | 'danger';
}

export function Button({
  variant = 'secondary',
  tone = 'default',
  className = '',
  style,
  children,
  ...rest
}: ButtonProps) {
  const budget = useRustBudget();
  useEffect(() => {
    if (variant === 'primary') budget?.spend();
  }, [variant, budget]);

  const variantStyle = BUTTON_VARIANT_STYLE[variant];
  const danger = tone === 'danger' && variant === 'primary'
    ? { background: 'var(--signal-danger)', color: 'var(--color-paper)' }
    : {};

  return (
    <button
      className={`type-button ${className}`}
      style={{
        padding: '12px 24px',
        borderRadius: 'var(--radius-sm)',
        borderWidth: 1,
        borderStyle: 'solid',
        cursor: 'pointer',
        transition: 'background-color var(--duration-fast) var(--ease-out)',
        ...variantStyle,
        ...danger,
        ...style,
      }}
      {...rest}
    >
      {children}
    </button>
  );
}

/* ───────── Chip ───────── */

type ChipState = 'listening' | 'thinking' | 'idle' | 'success' | 'warning' | 'danger';

const CHIP_STYLE: Record<ChipState, React.CSSProperties> = {
  listening: { color: 'var(--color-rust)', background: 'transparent' },
  thinking:  { color: 'var(--color-rust)', background: 'transparent' },
  idle:      { color: 'var(--color-muted)', background: 'transparent' },
  success:   { color: 'var(--signal-success)', background: 'var(--signal-success-tint)' },
  warning:   { color: 'var(--signal-warning)', background: 'var(--signal-warning-tint)' },
  danger:    { color: 'var(--signal-danger)',  background: 'var(--signal-danger-tint)' },
};

export function Chip({ state, children }: { state: ChipState; children: React.ReactNode }) {
  const budget = useRustBudget();
  useEffect(() => {
    if (state === 'listening' || state === 'thinking') budget?.spend();
  }, [state, budget]);

  const showDot = state === 'listening' || state === 'thinking';

  return (
    <span
      className="type-small"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 'var(--space-2)',
        padding: 'var(--space-1) var(--space-3)',
        borderRadius: 9999,
        ...CHIP_STYLE[state],
      }}
    >
      {showDot && (
        <span
          aria-hidden
          style={{
            display: 'inline-block',
            width: 6,
            height: 6,
            borderRadius: 9999,
            background: 'var(--color-rust)',
            animation: 'donna-pulse 1.8s ease-in-out infinite',
          }}
        />
      )}
      {children}
    </span>
  );
}

/* ───────── Link (inline) ───────── */

export function Link({
  className = '',
  style,
  children,
  ...rest
}: React.AnchorHTMLAttributes<HTMLAnchorElement>) {
  return (
    <a
      className={className}
      style={{
        color: 'var(--color-rust)',
        textDecoration: 'none',
        borderBottom: '1px solid rgba(123,85,68,0.3)',
        transition: 'border-color var(--duration-fast) var(--ease-out)',
        ...style,
      }}
      {...rest}
    >
      {children}
    </a>
  );
}

/* ───────── Divider ───────── */

export function Divider() {
  return <hr style={{ border: 0, borderTop: '1px solid var(--ink-300)', height: 1, margin: 0 }} />;
}
