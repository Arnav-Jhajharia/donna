'use client';

import { motion } from 'framer-motion';
import { CheckIcon } from '../icons';
import SectionHead from './SectionHead';
import type { TodoItem, TodoListBlock as TodoListSpec } from '@/lib/plan';

export default function TodoListBlock({ spec }: { spec: TodoListSpec }) {
  const kept = spec.items.filter((t) => t.done).length;
  return (
    <section style={{ margin: '26px 16px 0' }}>
      <SectionHead title={spec.title} right={`${kept} of ${spec.items.length} kept`} />
      <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
        {spec.items.map((t) => (
          <TodoRow key={t.id} todo={t} />
        ))}
      </div>
    </section>
  );
}

function TodoRow({ todo }: { todo: TodoItem }) {
  const { label, meta, source, done } = todo;
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '22px 1fr auto',
        gap: 12,
        padding: '10px 0',
        alignItems: 'flex-start',
        borderBottom: '1px solid var(--border-hairline)',
      }}
    >
      <motion.div
        whileTap={{ scale: 0.92 }}
        style={{
          width: 18,
          height: 18,
          borderRadius: 4,
          border: `1.25px solid ${done ? 'var(--moss-700)' : 'var(--border-strong)'}`,
          background: done ? 'var(--moss-700)' : 'transparent',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          marginTop: 2,
          cursor: 'pointer',
        }}
      >
        {done && <CheckIcon color="var(--paper-100)" />}
      </motion.div>
      <div>
        <div
          style={{
            fontSize: 15,
            color: done ? 'var(--fg-muted)' : 'var(--fg-primary)',
            fontWeight: 500,
            textDecoration: done ? 'line-through' : 'none',
            textDecorationColor: 'var(--ink-300)',
            letterSpacing: '-0.005em',
          }}
        >
          {label}
        </div>
        <div style={{ fontSize: 12.5, color: 'var(--fg-muted)', marginTop: 2 }}>
          {meta} <span style={{ color: 'var(--fg-placeholder)' }}>· from {source}</span>
        </div>
      </div>
      <span
        style={{
          fontSize: 11,
          color: done ? 'var(--moss-700)' : 'var(--fg-placeholder)',
          marginTop: 3,
          fontWeight: done ? 500 : 400,
        }}
      >
        {done ? 'kept' : ''}
      </span>
    </div>
  );
}
