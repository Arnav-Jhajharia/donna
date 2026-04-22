import { LeafIcon } from '../icons';
import type { PermissionBlock as PermissionBlockSpec } from '@/lib/plan';

export default function PermissionBlock({ spec }: { spec: PermissionBlockSpec }) {
  return (
    <div
      style={{
        margin: '14px 16px 0',
        padding: '16px 18px',
        background: 'var(--paper-50)',
        border: '1px dashed var(--border-strong)',
        borderRadius: 12,
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
    </div>
  );
}
