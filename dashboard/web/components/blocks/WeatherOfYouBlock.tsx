'use client';

import { motion } from 'framer-motion';
import type { WeatherOfYouBlock as WeatherSpec } from '@/lib/plan';

/** Pick accent tone based on energy level. */
function toneFor(energy: number): { bg: string; fg: string; dot: string } {
  if (energy < 0.33) return { bg: 'var(--paper-200)', fg: 'var(--ink-600)', dot: 'var(--ink-500)' };
  if (energy < 0.66) return { bg: 'var(--amber-100)', fg: 'var(--amber-700)', dot: 'var(--amber-700)' };
  return { bg: 'var(--moss-100)', fg: 'var(--moss-700)', dot: 'var(--moss-700)' };
}

export default function WeatherOfYouBlock({ spec }: { spec: WeatherSpec }) {
  const t = toneFor(spec.energy);
  const pct = Math.max(0, Math.min(1, spec.energy));
  return (
    <div
      style={{
        margin: '16px 16px 0',
        padding: '16px 18px',
        background: t.bg,
        border: '1px solid var(--border-hairline)',
        borderRadius: 12,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          justifyContent: 'space-between',
          gap: 12,
        }}
      >
        <div>
          <div
            style={{
              fontSize: 10,
              letterSpacing: '0.16em',
              textTransform: 'uppercase',
              color: t.fg,
              fontWeight: 600,
            }}
          >
            weather of you
          </div>
          <div
            style={{
              fontFamily: 'var(--font-serif)',
              fontSize: 24,
              fontWeight: 400,
              letterSpacing: '-0.015em',
              color: 'var(--fg-primary)',
              marginTop: 6,
              lineHeight: 1.05,
              textTransform: 'lowercase',
            }}
          >
            {spec.mood}
          </div>
        </div>
        <div
          style={{
            fontSize: 12,
            color: t.fg,
            fontWeight: 500,
            letterSpacing: '-0.005em',
          }}
        >
          {Math.round(pct * 100)}%
        </div>
      </div>
      <div
        style={{
          marginTop: 14,
          height: 4,
          background: 'rgba(30,26,24,0.06)',
          borderRadius: 3,
          overflow: 'hidden',
        }}
      >
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${pct * 100}%` }}
          transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1], delay: 0.2 }}
          style={{ height: '100%', background: t.dot }}
        />
      </div>
      <div
        style={{
          fontSize: 12.5,
          color: 'var(--fg-muted)',
          marginTop: 10,
          lineHeight: 1.45,
          fontStyle: 'italic',
        }}
      >
        {spec.basis}
      </div>
    </div>
  );
}
