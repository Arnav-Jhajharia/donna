import type { ReflectionBlock as ReflectionBlockSpec } from '@/lib/plan';
import SectionHead from './SectionHead';

export default function ReflectionBlock({ spec }: { spec: ReflectionBlockSpec }) {
  return (
    <section style={{ margin: '22px 16px 0' }}>
      <SectionHead title={spec.title} />
      <div
        style={{
          marginTop: 10,
          padding: '18px 20px',
          background: 'var(--bg-inset)',
          border: '1px solid var(--border-hairline)',
          borderRadius: 12,
          display: 'flex',
          flexDirection: 'column',
          gap: 14,
        }}
      >
        {spec.prompts.map((p, i) => (
          <div
            key={i}
            style={{
              display: 'flex',
              gap: 12,
              alignItems: 'flex-start',
              paddingBottom: i < spec.prompts.length - 1 ? 14 : 0,
              borderBottom: i < spec.prompts.length - 1 ? '1px solid var(--border-hairline)' : 'none',
            }}
          >
            <div
              style={{
                fontFamily: 'var(--font-serif)',
                fontStyle: 'italic',
                fontSize: 13,
                color: 'var(--fg-placeholder)',
                paddingTop: 2,
                minWidth: 16,
              }}
            >
              {i + 1}
            </div>
            <div
              style={{
                fontFamily: 'var(--font-serif)',
                fontSize: 16,
                lineHeight: 1.38,
                color: 'var(--fg-secondary)',
                letterSpacing: '-0.005em',
              }}
            >
              {p}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
