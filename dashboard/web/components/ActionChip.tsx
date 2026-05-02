'use client';

import { motion } from 'framer-motion';
import { useCallback, useState, type CSSProperties, type ReactNode } from 'react';
import { useAction } from '@/lib/action-context';
import { useAttentionSheet } from '@/lib/attention-sheet-context';
import type { ActionVerb } from '@/lib/plan';

/**
 * Universal tap target for the user-facing dashboard. Lives between the
 * raw <button> and the per-block opinionated UI:
 *
 *   <ActionChip verb={...} tone="rust">log lunch</ActionChip>
 *
 * Behavior:
 *   - On tap: optimistic state (the chip flips to "doing…"), POST runs,
 *     toast surfaces, manifest re-fetches.
 *   - When the chip's tone is ``destructive`` (archive/dismiss) we ask
 *     for an inline confirm tap before sending. Two-tap to commit.
 *   - Disabled state is instant via ``disabled`` prop. No layout shift.
 *   - The component never throws on action failure — the toast tells
 *     the user. Caller can read ``onResult`` to do verb-specific UI.
 */

export type ActionTone =
  | 'rust'        // primary affirmative — log this, do that
  | 'paper'      // calm neutral — snooze, later
  | 'amber'     // attention — confirm, decide
  | 'moss'      // momentum / streak — kept, done
  | 'oxblood'   // confrontation — call it
  | 'destructive'; // dismiss / cancel — needs confirm tap

interface ActionChipProps {
  verb: ActionVerb;
  children: ReactNode;
  tone?: ActionTone;
  /** When set, the chip renders smaller — for inline-row dense layouts. */
  size?: 'sm' | 'md';
  disabled?: boolean;
  /** Optional icon node rendered before the label. */
  icon?: ReactNode;
  /** Optional callback fired AFTER the backend ack. */
  onResult?: (response: { ok: boolean; message?: string }) => void;
  /** Optional confirm-tap label override (default "tap again"). */
  confirmLabel?: string;
  /** Override default styling. Avoid unless prototyping. */
  style?: CSSProperties;
  /** ARIA label override; defaults to children when string. */
  ariaLabel?: string;
}

const TONE_STYLES: Record<ActionTone, { bg: string; bgHover: string; fg: string; border: string }> = {
  rust:        { bg: 'var(--rust-50, #f7e8d8)', bgHover: 'var(--rust-100, #f0d6b8)', fg: 'var(--rust-800, #6a3a08)', border: 'var(--rust-300, #d8a868)' },
  paper:       { bg: 'transparent',              bgHover: 'var(--paper-100, #f4f2ec)', fg: 'var(--ink-700, #2a2a2a)', border: 'var(--border-hairline, #e5e1d6)' },
  amber:       { bg: 'var(--amber-50, #fbf2d8)', bgHover: 'var(--amber-100, #f5e6b8)', fg: 'var(--amber-900, #5a4308)', border: 'var(--amber-300, #d8b868)' },
  moss:        { bg: 'var(--moss-50, #e6efde)',  bgHover: 'var(--moss-100, #d2e2c6)',  fg: 'var(--moss-800, #2a4a1a)', border: 'var(--moss-300, #98b878)' },
  oxblood:     { bg: 'var(--oxblood-50, #f0d8d8)', bgHover: 'var(--oxblood-100, #e6c0c0)', fg: 'var(--oxblood-900, #4a0808)', border: 'var(--oxblood-300, #c87878)' },
  destructive: { bg: 'transparent',              bgHover: 'var(--paper-100, #f4f2ec)', fg: 'var(--ink-500, #6b6b6b)', border: 'var(--border-hairline, #e5e1d6)' },
};

export default function ActionChip({
  verb,
  children,
  tone = 'paper',
  size = 'md',
  disabled,
  icon,
  onResult,
  confirmLabel = 'tap again',
  style,
  ariaLabel,
}: ActionChipProps) {
  const fire = useAction();
  const { openSheet } = useAttentionSheet();
  const [busy, setBusy] = useState(false);
  const [confirmArmed, setConfirmArmed] = useState(false);

  const handleTap = useCallback(async () => {
    if (busy || disabled) return;
    // Local intercept: open_attention pops the bottom sheet instead of
    // hitting the backend. Avoids a 200/no-op round-trip and keeps the
    // navigation feeling instant.
    if (verb.v === 'open_attention') {
      openSheet(verb.attentionId);
      onResult?.({ ok: true });
      return;
    }
    if (tone === 'destructive' && !confirmArmed) {
      setConfirmArmed(true);
      // Auto-disarm after 3s so the user doesn't double-trip later by accident.
      setTimeout(() => setConfirmArmed(false), 3000);
      return;
    }
    setBusy(true);
    try {
      const res = await fire(verb);
      onResult?.({ ok: !!res.ok, message: typeof res.message === 'string' ? res.message : undefined });
    } finally {
      setBusy(false);
      setConfirmArmed(false);
    }
  }, [busy, disabled, tone, confirmArmed, fire, verb, onResult, openSheet]);

  const palette = TONE_STYLES[tone];
  const armed = tone === 'destructive' && confirmArmed;

  return (
    <motion.button
      type="button"
      onClick={handleTap}
      disabled={disabled || busy}
      aria-label={ariaLabel || (typeof children === 'string' ? children : undefined)}
      aria-busy={busy}
      whileTap={{ scale: 0.96 }}
      whileHover={{ y: -1 }}
      transition={{ duration: 0.12, ease: [0.22, 1, 0.36, 1] }}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: size === 'sm' ? '4px 10px' : '7px 14px',
        fontSize: size === 'sm' ? 12 : 13,
        fontFamily: 'inherit',
        fontWeight: 500,
        letterSpacing: 0.1,
        border: `1px solid ${armed ? 'var(--oxblood-500, #a3343a)' : palette.border}`,
        borderRadius: 999,
        background: armed ? 'var(--oxblood-100, #e6c0c0)' : palette.bg,
        color: armed ? 'var(--oxblood-900, #4a0808)' : palette.fg,
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
        transition: 'background-color 140ms, border-color 140ms, color 140ms',
        ...style,
      }}
      onMouseEnter={(e) => {
        if (!disabled && !busy) {
          (e.currentTarget as HTMLButtonElement).style.background = palette.bgHover;
        }
      }}
      onMouseLeave={(e) => {
        if (!disabled && !busy) {
          (e.currentTarget as HTMLButtonElement).style.background = armed
            ? 'var(--oxblood-100, #e6c0c0)'
            : palette.bg;
        }
      }}
    >
      {busy ? (
        <Spinner />
      ) : (
        <>
          {icon ? <span style={{ display: 'inline-flex' }}>{icon}</span> : null}
          <span>{armed ? confirmLabel : children}</span>
        </>
      )}
    </motion.button>
  );
}

function Spinner() {
  return (
    <span
      style={{
        width: 12,
        height: 12,
        borderRadius: '50%',
        border: '2px solid currentColor',
        borderRightColor: 'transparent',
        animation: 'donna-spin 700ms linear infinite',
        display: 'inline-block',
      }}
    />
  );
}

// Inject the spin keyframes once. SSR-safe — only runs in the browser.
if (typeof document !== 'undefined') {
  const KEY = 'donna-action-chip-keyframes';
  if (!document.getElementById(KEY)) {
    const style = document.createElement('style');
    style.id = KEY;
    style.textContent =
      '@keyframes donna-spin { to { transform: rotate(360deg); } }';
    document.head.appendChild(style);
  }
}
