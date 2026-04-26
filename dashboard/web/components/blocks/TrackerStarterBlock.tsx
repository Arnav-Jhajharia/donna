'use client';

import { motion } from 'framer-motion';
import { ChevIcon, ICONS } from '../icons';
import { useAction } from '@/lib/action-context';
import type { TrackerStarterBlock as TrackerStarterSpec } from '@/lib/plan';

/**
 * TrackerStarterBlock — "want me to start tracking X?"
 * The user signal Donna observed appears as an italic pull-quote;
 * tap to fire the start_tracker verb.
 */
export default function TrackerStarterBlock({ spec }: { spec: TrackerStarterSpec }) {
  const fire = useAction();
  const Icon = ICONS[spec.icon];
  const onTap = () => {
    void fire(spec.action);
  };
  return (
    <section style={{ margin: '20px 16px 0' }}>
      <motion.div
        whileTap={{ scale: 0.99 }}
        role="button"
        tabIndex={0}
        onClick={onTap}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onTap();
          }
        }}
        style={{
          background: 'var(--paper-50)',
          border: '1px solid var(--border-hairline)',
          borderLeft: '2px solid var(--rust-700)',
          borderRadius: 10,
          padding: '14px 16px',
          display: 'grid',
          gridTemplateColumns: '36px 1fr auto',
          alignItems: 'flex-start',
          gap: 12,
          cursor: 'pointer',
        }}
      >
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: 8,
            background: 'var(--rust-100)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Icon color="var(--rust-700)" />
        </div>
        <div>
          <div
            style={{
              fontSize: 10,
              letterSpacing: '0.14em',
              textTransform: 'uppercase',
              color: 'var(--rust-700)',
              fontWeight: 500,
              marginBottom: 4,
            }}
          >
            {spec.title}
          </div>
          <div
            style={{
              fontFamily: 'var(--font-serif)',
              fontStyle: 'italic',
              fontSize: 16,
              fontWeight: 400,
              lineHeight: 1.35,
              letterSpacing: '-0.005em',
              color: 'var(--fg-primary)',
              marginBottom: 6,
            }}
          >
            {spec.rationale}
          </div>
          <div
            style={{
              fontSize: 13,
              color: 'var(--fg-secondary)',
              lineHeight: 1.45,
            }}
          >
            start tracking <span style={{ fontWeight: 500, color: 'var(--fg-primary)' }}>{spec.trackerName}</span>?
          </div>
        </div>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            fontSize: 12,
            fontWeight: 500,
            color: 'var(--rust-700)',
            marginTop: 6,
          }}
        >
          {spec.cta}
          <ChevIcon size={11} color="var(--rust-700)" />
        </div>
      </motion.div>
    </section>
  );
}
