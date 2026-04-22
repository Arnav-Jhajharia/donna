import type { OpenLoopsBlock as OpenLoopsBlockSpec } from '@/lib/plan';
import SectionHead from './SectionHead';

export default function OpenLoopsBlock({ spec }: { spec: OpenLoopsBlockSpec }) {
  return (
    <section style={{ margin: '22px 16px 0' }}>
      <SectionHead title={spec.title} right={String(spec.items.length)} />
      <div
        style={{
          marginTop: 10,
          borderTop: '1px solid var(--border-hairline)',
        }}
      >
        {spec.items.map((loop) => (
          <div
            key={loop.id}
            style={{
              padding: '12px 4px',
              borderBottom: '1px solid var(--border-hairline)',
              display: 'flex',
              alignItems: 'flex-start',
              justifyContent: 'space-between',
              gap: 12,
            }}
          >
            <div style={{ flex: 1 }}>
              <div
                style={{
                  fontFamily: 'var(--font-serif)',
                  fontSize: 15,
                  fontWeight: 500,
                  color: 'var(--fg-primary)',
                  letterSpacing: '-0.005em',
                  lineHeight: 1.3,
                }}
              >
                {loop.title}
              </div>
              <div
                style={{
                  fontSize: 12,
                  color: 'var(--fg-muted)',
                  marginTop: 4,
                  fontStyle: 'italic',
                }}
              >
                {loop.commitment}
              </div>
            </div>
            <div
              style={{
                fontSize: 11,
                letterSpacing: '0.06em',
                textTransform: 'uppercase',
                color: 'var(--rust-700)',
                fontWeight: 500,
                paddingTop: 2,
                whiteSpace: 'nowrap',
              }}
            >
              {loop.age}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
