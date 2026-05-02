'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { useToasts } from '@/lib/action-context';

/**
 * Floating toast stack — bottom-anchored on mobile, surfaces fake-WA acks
 * after dashboard actions. Lives inside the ActionProvider so toasts hook
 * straight off the action context.
 */
export default function Toasts() {
  const { toasts, dismissToast } = useToasts();

  return (
    <div
      style={{
        position: 'fixed',
        left: '50%',
        bottom: 24,
        transform: 'translateX(-50%)',
        width: 'min(420px, calc(100vw - 32px))',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        zIndex: 50,
        pointerEvents: 'none',
      }}
    >
      <AnimatePresence>
        {toasts.map((t) => (
          <motion.div
            key={t.id}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
            onClick={() => dismissToast(t.id)}
            style={{
              pointerEvents: 'auto',
              cursor: 'pointer',
              background:
                t.tone === 'error'
                  ? 'var(--oxblood-700, #6a1818)'
                  : 'var(--ink-900)',
              color: 'var(--paper-100)',
              borderRadius: 12,
              padding: '12px 14px',
              boxShadow: '0 8px 24px rgba(0,0,0,0.22)',
              display: 'flex',
              flexDirection: 'column',
              gap: 4,
            }}
          >
            <div
              style={{
                fontSize: 10,
                letterSpacing: '0.14em',
                textTransform: 'uppercase',
                color:
                  t.tone === 'error'
                    ? 'var(--paper-300, #d6b8b8)'
                    : 'var(--rust-300)',
                fontWeight: 500,
              }}
            >
              {t.kicker}
            </div>
            <div style={{ fontSize: 13.5, lineHeight: 1.4, color: 'var(--paper-100)' }}>{t.body}</div>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
