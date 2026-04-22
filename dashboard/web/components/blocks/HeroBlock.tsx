import MumbaiLineArt from '../MumbaiLineArt';
import type { HeroBlock as HeroBlockSpec } from '@/lib/plan';

export default function HeroBlock({ spec }: { spec: HeroBlockSpec }) {
  return (
    <div
      style={{
        margin: '0 16px',
        borderRadius: 14,
        overflow: 'hidden',
        background: 'var(--bg-inset)',
        border: '1px solid var(--border-hairline)',
      }}
    >
      <div style={{ padding: '22px 22px 10px' }}>
        <div
          style={{
            fontSize: 11,
            letterSpacing: '0.14em',
            textTransform: 'uppercase',
            color: 'var(--fg-placeholder)',
            fontWeight: 500,
          }}
        >
          {spec.date}
        </div>
        <div
          style={{
            fontFamily: 'var(--font-serif)',
            fontWeight: 400,
            fontSize: 32,
            lineHeight: 1.08,
            letterSpacing: '-0.02em',
            color: 'var(--fg-primary)',
            marginTop: 8,
          }}
        >
          {spec.greeting}
        </div>
        <div style={{ fontSize: 13, color: 'var(--fg-muted)', marginTop: 10, letterSpacing: '-0.005em' }}>
          {spec.subtext}
        </div>
      </div>
      {spec.illustration !== 'none' && (
        <div style={{ marginTop: 8 }}>
          <MumbaiLineArt />
        </div>
      )}
    </div>
  );
}
