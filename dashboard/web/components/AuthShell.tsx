/**
 * Shared chrome for `/auth/*` pages — the editorial wrapper that gives
 * the magic-link expired state, the OTP form, and any future auth surface
 * the same paper-toned, lowercase, donna-voiced look.
 *
 * Visual contract: the page is a calm canvas (paper-50 → paper-100), the
 * card sits centered with a hairline border, the kicker is small caps
 * with letter-spacing, the headline is serif, body is sans, and a tiny
 * line-art moon glyph hovers above the headline as an ornament. No
 * shadow, no hard borders, no chrome you'd find on a generic SaaS form.
 */
import type { ReactNode } from 'react';

export interface AuthShellProps {
  kicker: string;
  title: string;
  body?: string;
  children: ReactNode;
  /** Optional subdued footer (e.g. "donna · whatsapp"). */
  meta?: string;
}

export function AuthShell({ kicker, title, body, children, meta }: AuthShellProps) {
  return (
    <main className="auth-page">
      <div className="auth-frame">
        <MoonGlyph />
        <div className="auth-kicker">{kicker}</div>
        <h1 className="auth-headline">{title}</h1>
        {body ? <p className="auth-lede">{body}</p> : null}
        <div className="auth-content">{children}</div>
      </div>
      {meta ? <div className="auth-meta">{meta}</div> : null}
    </main>
  );
}

/** Single-weight rust line drawing — a crescent over a horizon line. */
function MoonGlyph() {
  return (
    <svg
      className="auth-glyph"
      width="48"
      height="48"
      viewBox="0 0 48 48"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M30 10a14 14 0 1 0 8 22 12 12 0 0 1-8-22z" />
      <path d="M6 40h36" opacity="0.5" />
    </svg>
  );
}
