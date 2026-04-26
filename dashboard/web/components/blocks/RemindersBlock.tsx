'use client';

import { motion } from 'framer-motion';
import { useState } from 'react';
import { BellIcon, CheckIcon } from '../icons';
import SectionHead from './SectionHead';
import { useAction } from '@/lib/action-context';
import type { ReminderItem, RemindersBlock as RemindersSpec } from '@/lib/plan';

export default function RemindersBlock({ spec }: { spec: RemindersSpec }) {
  const open = spec.items.filter((r) => !r.done).length;
  return (
    <section style={{ margin: '26px 16px 0' }}>
      <SectionHead
        title={spec.title}
        right={open > 0 ? `${open} open` : 'all kept'}
      />
      <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {spec.items.map((r) => (
          <ReminderRow key={r.id} reminder={r} />
        ))}
      </div>
    </section>
  );
}

function ReminderRow({ reminder }: { reminder: ReminderItem }) {
  const fire = useAction();
  const [optimisticDone, setOptimisticDone] = useState<boolean | null>(null);
  const done = optimisticDone ?? Boolean(reminder.done);

  const onCheck = () => {
    if (done || !reminder.action) return;
    setOptimisticDone(true);
    void fire(reminder.action);
  };

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '64px 22px 1fr',
        gap: 10,
        padding: '10px 12px',
        alignItems: 'center',
        background: done ? 'var(--paper-200)' : 'var(--paper-50)',
        border: '1px solid var(--border-hairline)',
        borderRadius: 10,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          fontSize: 11.5,
          color: done ? 'var(--fg-muted)' : 'var(--rust-700)',
          fontWeight: 500,
          letterSpacing: '-0.005em',
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        <BellIcon size={12} color={done ? 'var(--fg-muted)' : 'var(--rust-700)'} />
        {reminder.at}
      </div>
      <motion.div
        whileTap={{ scale: 0.92 }}
        role="button"
        aria-pressed={done}
        aria-label={done ? `${reminder.label} kept` : `mark ${reminder.label} done`}
        tabIndex={reminder.action ? 0 : -1}
        onClick={onCheck}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onCheck();
          }
        }}
        style={{
          width: 18,
          height: 18,
          borderRadius: 4,
          border: `1.25px solid ${done ? 'var(--moss-700)' : 'var(--border-strong)'}`,
          background: done ? 'var(--moss-700)' : 'transparent',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: reminder.action ? 'pointer' : 'default',
        }}
      >
        {done && <CheckIcon size={10} color="var(--paper-100)" />}
      </motion.div>
      <div>
        <div
          style={{
            fontSize: 14.5,
            color: done ? 'var(--fg-muted)' : 'var(--fg-primary)',
            fontWeight: 500,
            textDecoration: done ? 'line-through' : 'none',
            textDecorationColor: 'var(--ink-300)',
            letterSpacing: '-0.005em',
            lineHeight: 1.3,
          }}
        >
          {reminder.label}
        </div>
        {reminder.meta && (
          <div style={{ fontSize: 12, color: 'var(--fg-muted)', marginTop: 2 }}>{reminder.meta}</div>
        )}
      </div>
    </div>
  );
}
