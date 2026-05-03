'use client';

import { motion } from 'framer-motion';
import type { CSSProperties, ReactNode } from 'react';
import { buildWaUrl } from '@/lib/wa-deeplink';
import { useAttentionSheet } from '@/lib/attention-sheet-context';

/**
 * Universal "tap any element to do the right thing" wrapper.
 *
 * The dashboard's underlying intent is "every visible thing is a way INTO
 * the conversation OR into a richer in-app view." This wrapper picks the
 * right surface based on what's available:
 *
 *   1. ``attentionId`` present → open the in-app AttentionSheet.
 *      For attention-backed blocks (trackers, watches, open loops,
 *      reminders, briefs) this is the right move — the user wants to
 *      SEE the data, not talk about it. AttentionSheet shows history,
 *      structured actions, etc.
 *
 *   2. ``primer`` present → open WhatsApp with the primer pre-filled.
 *      Right for free-form discussion ("tell me about X"), recipe
 *      setup, or anything where the user wants to TALK.
 *
 * If both are present, ``attentionId`` wins. If only primer, falls back
 * to WhatsApp. The same call site can pass ``attentionId={item.attention_id}``
 * (which may be undefined) and ``primer="tell me about X"`` and the
 * component does the right thing whether the row is attention-backed or
 * not — no per-row branching at the call site.
 *
 * Visual contract:
 * - Renders an `<a>` (WA fallback) or `<button>` (sheet open) styled to
 *   inherit the parent's typography. Strips link affordances by default
 *   so the tap target is invisible — tappability is discovered by touch.
 * - Three decorations (`row` / `label` / `block`) tune the hover gesture.
 */

export type TapDecoration = 'none' | 'row' | 'label' | 'block';

export interface TapToTalkProps {
  /** Open the in-app AttentionSheet for this attention id (preferred). */
  attentionId?: string;
  /** WhatsApp primer text — used when no attentionId, or as fallback. */
  primer?: string;
  decoration?: TapDecoration;
  children: ReactNode;
  style?: CSSProperties;
  className?: string;
  ariaLabel?: string;
}

const baseStyle: CSSProperties = {
  display: 'block',
  textDecoration: 'none',
  color: 'inherit',
  cursor: 'pointer',
  background: 'transparent',
  border: 'none',
  padding: 0,
  font: 'inherit',
  textAlign: 'inherit' as CSSProperties['textAlign'],
  WebkitTapHighlightColor: 'transparent',
};

const decoStyleFor = (decoration: TapDecoration): CSSProperties => {
  if (decoration === 'label') return { display: 'inline', cursor: 'pointer' };
  return { display: 'block' };
};

const hoverFor = (decoration: TapDecoration) => {
  if (decoration === 'label') return { color: 'var(--ink-900, #1E1A18)' };
  if (decoration === 'row') return { x: 1 };
  if (decoration === 'block') return { y: -1 };
  return undefined;
};

export default function TapToTalk({
  attentionId,
  primer,
  decoration = 'none',
  children,
  style,
  className,
  ariaLabel,
}: TapToTalkProps) {
  const { openSheet } = useAttentionSheet();
  const decoStyle = decoStyleFor(decoration);
  const hover = hoverFor(decoration);

  // attention-backed → open in-app sheet
  if (attentionId) {
    return (
      <motion.button
        type="button"
        onClick={() => openSheet(attentionId)}
        aria-label={ariaLabel ?? primer ?? 'open details'}
        className={className}
        whileHover={hover}
        transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
        style={{ ...baseStyle, ...decoStyle, ...style }}
      >
        {children}
      </motion.button>
    );
  }

  // No primer either → render plain markup, not interactive
  if (!primer) {
    return (
      <div className={className} style={style}>
        {children}
      </div>
    );
  }

  // primer-only → WhatsApp deeplink
  const href = buildWaUrl(primer);
  return (
    <motion.a
      href={href}
      target="_blank"
      rel="noreferrer"
      aria-label={ariaLabel ?? primer}
      className={className}
      whileHover={hover}
      transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
      style={{ ...baseStyle, ...decoStyle, ...style }}
    >
      {children}
    </motion.a>
  );
}
