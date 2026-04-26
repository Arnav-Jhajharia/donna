/**
 * DONNA · Reference component implementations
 *
 * These are the canonical components. When building a new page,
 * compose with these. Do not re-implement, do not restyle.
 *
 * Uses Tailwind classes from tailwind.config.js.
 */

import React, { createContext, useContext, useEffect, useRef } from 'react';

/* ===================== Screen-level accent tracking ===================== */
/* One-rust-per-screen is enforced at runtime in dev via a context counter. */

const RustBudgetContext = createContext<{ spend: () => void; peek: () => number } | null>(null);

export const ScreenRoot: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const countRef = useRef(0);
  const api = {
    spend: () => {
      countRef.current += 1;
      if (process.env.NODE_ENV !== 'production' && countRef.current > 1) {
        // eslint-disable-next-line no-console
        console.warn(
          '[donna] Rust budget exceeded: more than one rust moment on this screen. The design is wrong.'
        );
      }
    },
    peek: () => countRef.current,
  };
  useEffect(() => { countRef.current = 0; });
  return <RustBudgetContext.Provider value={api}>{children}</RustBudgetContext.Provider>;
};

const useRustBudget = () => useContext(RustBudgetContext);

/* ===================== Heading ===================== */

type HeadingLevel = 1 | 2 | 3 | 4;

const HEADING_CLASS: Record<HeadingLevel, string> = {
  1: 'font-serif text-h1 text-ink',
  2: 'font-serif text-h2 text-ink',
  3: 'font-serif text-h3 text-ink',
  4: 'font-sans text-h4 text-ink',
};

export const Heading: React.FC<{
  level: HeadingLevel;
  children: React.ReactNode;
  className?: string;
}> = ({ level, children, className = '' }) => {
  const Tag = `h${level}` as keyof JSX.IntrinsicElements;
  return <Tag className={`${HEADING_CLASS[level]} ${className}`}>{children}</Tag>;
};

/* ===================== Accent (the one-word italic rust) ===================== */

export const Accent: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const budget = useRustBudget();
  useEffect(() => { budget?.spend(); }, [budget]);
  return <em className="italic-accent-heading font-medium text-rust">{children}</em>;
};

/* ===================== Label ===================== */

export const Label: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <span className="font-sans text-label uppercase tracking-[0.14em] text-rust">
    {children}
  </span>
);

/* ===================== Card ===================== */

type CardTreatment = 'surface' | 'hairline' | 'paper';

const CARD_TREATMENT: Record<CardTreatment, string> = {
  surface:  'bg-surface rounded-md',
  hairline: 'bg-paper rounded-md border border-hairline border-ink-300',
  paper:    'bg-paper',
};

export const Card: React.FC<{
  treatment?: CardTreatment;
  interactive?: boolean;
  children: React.ReactNode;
  className?: string;
}> = ({ treatment = 'surface', interactive = false, children, className = '' }) => (
  <article
    className={[
      CARD_TREATMENT[treatment],
      'p-5',
      interactive && treatment === 'surface' ? 'hover:bg-surface-pressed transition-colors duration-base ease-standard' : '',
      className,
    ].filter(Boolean).join(' ')}
  >
    {children}
  </article>
);

/* ===================== Button ===================== */

type ButtonVariant = 'primary' | 'secondary' | 'ghost';

const BUTTON_VARIANT: Record<ButtonVariant, string> = {
  primary:   'bg-rust text-paper hover:bg-rust-900',
  secondary: 'bg-paper text-ink border border-hairline border-ink-300 hover:bg-surface',
  ghost:     'bg-transparent text-ink hover:bg-surface',
};

export const Button: React.FC<
  React.ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: ButtonVariant;
    tone?: 'default' | 'danger';
  }
> = ({ variant = 'secondary', tone = 'default', className = '', children, ...rest }) => {
  const budget = useRustBudget();
  useEffect(() => {
    if (variant === 'primary') budget?.spend();
  }, [variant, budget]);

  const dangerOverride = tone === 'danger' && variant === 'primary'
    ? 'bg-oxblood text-paper hover:bg-oxblood'
    : '';

  return (
    <button
      className={[
        'font-sans text-button px-5 py-3 rounded-sm',
        'transition-colors duration-fast ease-standard',
        'focus:outline-none focus:ring-focus focus:ring-rust focus:ring-offset-2 focus:ring-offset-paper',
        'disabled:bg-paper-200 disabled:text-ink-200 disabled:cursor-not-allowed',
        BUTTON_VARIANT[variant],
        dangerOverride,
        className,
      ].join(' ')}
      {...rest}
    >
      {children}
    </button>
  );
};

/* ===================== Input ===================== */

export const Input: React.FC<React.InputHTMLAttributes<HTMLInputElement>> = ({
  className = '',
  ...rest
}) => (
  <input
    {...rest}
    className={[
      'font-sans text-input not-italic',  // upright always
      'bg-surface text-ink placeholder:text-ink-400',
      'rounded-sm px-4 py-3',
      'border border-transparent',
      'focus:outline-none focus:border-rust focus:bg-paper',
      'transition-colors duration-fast ease-standard',
      className,
    ].join(' ')}
  />
);

/* ===================== Link (inline) ===================== */

export const Link: React.FC<React.AnchorHTMLAttributes<HTMLAnchorElement>> = ({
  className = '',
  children,
  ...rest
}) => (
  <a
    {...rest}
    className={[
      'text-rust no-underline',
      'border-b',
      'border-[rgba(123,85,68,0.3)]', // the one approved rgba — pulled from spec
      'transition-colors duration-fast ease-standard',
      'hover:border-rust',
      className,
    ].join(' ')}
  >
    {children}
  </a>
);

/* ===================== Chip ===================== */

type ChipState = 'listening' | 'thinking' | 'idle' | 'success' | 'warning' | 'danger';

const CHIP_STYLE: Record<ChipState, string> = {
  listening: 'text-rust',
  thinking:  'text-rust',
  idle:      'text-ink-500',
  success:   'text-moss bg-moss-tint',
  warning:   'text-amber bg-amber-tint',
  danger:    'text-oxblood bg-oxblood-tint',
};

export const Chip: React.FC<{ state: ChipState; children: React.ReactNode }> = ({
  state, children,
}) => {
  const budget = useRustBudget();
  useEffect(() => {
    if (state === 'listening' || state === 'thinking') budget?.spend();
  }, [state, budget]);

  const showDot = state === 'listening' || state === 'thinking';

  return (
    <span className={`inline-flex items-center gap-2 px-3 py-1 rounded-full font-sans text-small ${CHIP_STYLE[state]}`}>
      {showDot && (
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-rust animate-pulse" aria-hidden />
      )}
      {children}
    </span>
  );
};

/* ===================== Divider ===================== */

export const Divider: React.FC = () => <hr className="border-0 border-t border-ink-300 h-px" />;

/* ===================== Wordmark ===================== */

type WordmarkSize = 'splash' | 'hero' | 'cover' | 'masthead' | 'nav' | 'footer' | 'min';
const WORDMARK_SIZE_PX: Record<WordmarkSize, number> = {
  splash: 128, hero: 88, cover: 56, masthead: 32, nav: 22, footer: 16, min: 14,
};

export const Wordmark: React.FC<{
  color?: 'ink' | 'paper' | 'rust';
  size?: WordmarkSize;
}> = ({ color = 'ink', size = 'masthead' }) => {
  const px = WORDMARK_SIZE_PX[size];

  // Below 14px, render the "d" monogram instead. No exceptions.
  if (px < 14) {
    return (
      <span
        className={`font-serif italic font-medium lowercase text-${color}`}
        style={{ fontSize: `${px}px`, letterSpacing: '-0.01em' }}
      >
        d
      </span>
    );
  }

  const budget = useRustBudget();
  useEffect(() => {
    if (color === 'rust') budget?.spend();
  }, [color, budget]);

  return (
    <span
      className={`font-serif italic font-medium lowercase text-${color}`}
      style={{ fontSize: `${px}px`, letterSpacing: '-0.01em' }}
    >
      donna
    </span>
  );
};
