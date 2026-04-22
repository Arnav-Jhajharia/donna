import { EyeIcon } from '../icons';
import type { WitnessBlock as WitnessBlockSpec } from '@/lib/plan';

export default function WitnessBlock({ spec }: { spec: WitnessBlockSpec }) {
  return (
    <div
      style={{
        margin: '14px 16px 0',
        padding: '14px 16px',
        background: 'var(--bg-inset)',
        border: '1px solid var(--border-hairline)',
        borderRadius: 10,
        display: 'flex',
        alignItems: 'flex-start',
        gap: 12,
      }}
    >
      <div
        style={{
          width: 28,
          height: 28,
          borderRadius: 14,
          background: 'var(--paper-200)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
        }}
      >
        <EyeIcon size={14} color="var(--fg-tertiary)" />
      </div>
      <div style={{ flex: 1 }}>
        <div
          style={{
            fontFamily: 'var(--font-serif)',
            fontSize: 15,
            lineHeight: 1.42,
            color: 'var(--fg-secondary)',
            letterSpacing: '-0.005em',
          }}
        >
          {spec.observation}
        </div>
        {spec.source && (
          <div
            style={{
              fontSize: 11,
              color: 'var(--fg-placeholder)',
              marginTop: 6,
              letterSpacing: '0.04em',
              textTransform: 'uppercase',
              fontWeight: 500,
            }}
          >
            from {spec.source}
          </div>
        )}
      </div>
    </div>
  );
}
