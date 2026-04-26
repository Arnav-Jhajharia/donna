'use client';

import { motion } from 'framer-motion';
import { LeafIcon } from '../icons';
import { useAction } from '@/lib/action-context';
import type { PermissionBlock as PermissionBlockSpec } from '@/lib/plan';

export default function PermissionBlock({ spec }: { spec: PermissionBlockSpec }) {
  const fire = useAction();
  const tappable = Boolean(spec.action);
  const onTap = () => {
    if (spec.action) void fire(spec.action);
  };
  return (
    <motion.div
      whileTap={tappable ? { scale: 0.99 } : undefined}
      role={tappable ? 'button' : undefined}
      tabIndex={tappable ? 0 : undefined}
      onClick={tappable ? onTap : undefined}
      onKeyDown={
        tappable
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onTap();
              }
            }
          : undefined
      }
      style={{
        margin: '14px 16px 0',
        padding: '16px 18px',
        background: 'var(--paper-50)',
        border: '1px dashed var(--border-strong)',
        borderRadius: 12,
        cursor: tappable ? 'pointer' : 'default',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          marginBottom: 8,
        }}
      >
        <LeafIcon size={14} color="var(--moss-700)" />
        <div
          style={{
            fontSize: 10,
            letterSpacing: '0.18em',
            textTransform: 'uppercase',
            color: 'var(--moss-700)',
            fontWeight: 600,
          }}
        >
          permission
        </div>
      </div>
      <div
        style={{
          fontFamily: 'var(--font-serif)',
          fontStyle: 'italic',
          fontSize: 17,
          fontWeight: 400,
          lineHeight: 1.3,
          letterSpacing: '-0.01em',
          color: 'var(--fg-primary)',
          marginBottom: 6,
        }}
      >
        {spec.title}
      </div>
      <div style={{ fontSize: 13, lineHeight: 1.55, color: 'var(--fg-secondary)' }}>
        {spec.body}
      </div>
    </motion.div>
  );
}
