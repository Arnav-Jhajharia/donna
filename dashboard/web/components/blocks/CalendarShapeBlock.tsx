'use client';

import { motion } from 'framer-motion';
import type { CalendarShapeBlock as CalShapeSpec, CalendarSlot } from '@/lib/plan';
import SectionHead from './SectionHead';

const KIND_TONE: Record<CalendarSlot['kind'], { bg: string; bar: string; label: string }> = {
  meeting:  { bg: 'var(--rust-100)',   bar: 'var(--rust-700)',   label: 'meet'     },
  focus:    { bg: 'var(--moss-100)',   bar: 'var(--moss-700)',   label: 'focus'    },
  break:    { bg: 'var(--paper-200)',  bar: 'var(--ink-400)',    label: 'break'    },
  travel:   { bg: 'var(--amber-100)',  bar: 'var(--amber-700)',  label: 'travel'   },
  personal: { bg: 'var(--rust-50)',    bar: 'var(--rust-500)',   label: 'personal' },
};

export default function CalendarShapeBlock({ spec }: { spec: CalShapeSpec }) {
  const total = spec.slots.reduce((n, s) => n + s.duration, 0) || 1;
  return (
    <section style={{ margin: '22px 16px 0' }}>
      <SectionHead title={spec.title} right={`${spec.slots.length} blocks`} />
      {spec.shapeRead && (
        <div
          style={{
            fontSize: 12.5,
            color: 'var(--fg-muted)',
            marginTop: 6,
            marginBottom: 10,
            fontStyle: 'italic',
            letterSpacing: '-0.005em',
          }}
        >
          {spec.shapeRead}
        </div>
      )}
      <div
        style={{
          marginTop: 10,
          display: 'flex',
          gap: 3,
          height: 10,
          borderRadius: 3,
          overflow: 'hidden',
          background: 'var(--paper-200)',
        }}
      >
        {spec.slots.map((s, i) => {
          const t = KIND_TONE[s.kind];
          return (
            <motion.div
              key={s.id}
              initial={{ flexGrow: 0, opacity: 0 }}
              animate={{ flexGrow: s.duration / total, opacity: 1 }}
              transition={{ duration: 0.6, delay: 0.1 + i * 0.04, ease: [0.22, 1, 0.36, 1] }}
              style={{
                flexBasis: 0,
                background: t.bar,
              }}
            />
          );
        })}
      </div>
      <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {spec.slots.map((s) => {
          const t = KIND_TONE[s.kind];
          return (
            <div
              key={s.id}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '8px 10px',
                background: t.bg,
                borderRadius: 6,
              }}
            >
              <div
                style={{
                  fontFamily: 'var(--font-sans)',
                  fontSize: 11,
                  fontWeight: 600,
                  color: t.bar,
                  width: 46,
                  letterSpacing: '0.02em',
                }}
              >
                {s.at}
              </div>
              <div
                style={{
                  fontSize: 13,
                  color: 'var(--fg-primary)',
                  flex: 1,
                  letterSpacing: '-0.005em',
                }}
              >
                {s.label}
              </div>
              <div
                style={{
                  fontSize: 10,
                  color: t.bar,
                  textTransform: 'uppercase',
                  letterSpacing: '0.12em',
                  fontWeight: 600,
                }}
              >
                {t.label}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
