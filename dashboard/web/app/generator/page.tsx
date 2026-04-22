import DashboardRenderer from '@/components/DashboardRenderer';
import { generatePlan } from '@/lib/generator';
import { planDensity } from '@/lib/plan';
import { SCENARIOS } from '@/lib/scenarios';

export default function GeneratorPage() {
  return (
    <main style={{ minHeight: '100vh', padding: '48px 24px 96px' }}>
      <header style={{ maxWidth: 960, margin: '0 auto 40px' }}>
        <div
          style={{
            fontSize: 11,
            letterSpacing: '0.18em',
            textTransform: 'uppercase',
            color: 'var(--fg-placeholder)',
            fontWeight: 500,
          }}
        >
          donna · live generator
        </div>
        <h1
          style={{
            fontFamily: 'var(--font-serif)',
            fontSize: 40,
            fontWeight: 400,
            letterSpacing: '-0.02em',
            color: 'var(--fg-primary)',
            margin: '12px 0 6px',
            lineHeight: 1.08,
          }}
        >
          the generator, thinking
        </h1>
        <p
          style={{
            fontFamily: 'var(--font-serif)',
            fontStyle: 'italic',
            fontSize: 18,
            lineHeight: 1.45,
            color: 'var(--fg-secondary)',
            maxWidth: 620,
            margin: 0,
          }}
        >
          these dashboards aren't fixtures — they're composed by the generator at render
          time from a MomentContext. the LLM will eventually replace the rule-based composer,
          but the shape stays the same.
        </p>
      </header>

      <div
        style={{
          maxWidth: 1600,
          margin: '0 auto',
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))',
          gap: 32,
          alignItems: 'start',
        }}
      >
        {SCENARIOS.map((s) => {
          const plan = generatePlan(s.ctx);
          const density = planDensity(plan);
          return (
            <section key={s.id}>
              <header style={{ marginBottom: 14, paddingLeft: 4 }}>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'baseline',
                    justifyContent: 'space-between',
                    gap: 12,
                  }}
                >
                  <div
                    style={{
                      fontSize: 11,
                      letterSpacing: '0.16em',
                      textTransform: 'uppercase',
                      color: 'var(--rust-700)',
                      fontWeight: 600,
                    }}
                  >
                    {s.label}
                  </div>
                  <div
                    style={{
                      fontSize: 10,
                      color: 'var(--fg-placeholder)',
                      letterSpacing: '0.08em',
                    }}
                  >
                    density {density}/12 · {plan.blocks.length} blocks
                  </div>
                </div>
                <div
                  style={{
                    fontFamily: 'var(--font-serif)',
                    fontStyle: 'italic',
                    fontSize: 15,
                    lineHeight: 1.4,
                    color: 'var(--fg-muted)',
                    marginTop: 6,
                  }}
                >
                  {s.description}
                </div>
                <div
                  style={{
                    marginTop: 12,
                    padding: '10px 12px',
                    background: 'var(--paper-50)',
                    border: '1px solid var(--border-hairline)',
                    borderRadius: 6,
                    fontSize: 10,
                    letterSpacing: '0.14em',
                    textTransform: 'uppercase',
                    color: 'var(--fg-placeholder)',
                    fontWeight: 500,
                  }}
                >
                  <span style={{ marginRight: 8 }}>composed thesis</span>
                  <span
                    style={{
                      textTransform: 'none',
                      letterSpacing: '-0.005em',
                      fontFamily: 'var(--font-serif)',
                      fontStyle: 'italic',
                      fontSize: 13,
                      color: 'var(--fg-secondary)',
                      fontWeight: 400,
                    }}
                  >
                    {plan.thesis}
                  </span>
                </div>
              </header>
              <div
                style={{
                  width: '100%',
                  maxWidth: 440,
                  margin: '0 auto',
                  background: 'var(--bg-canvas)',
                  borderLeft: '1px solid var(--border-hairline)',
                  borderRight: '1px solid var(--border-hairline)',
                  overflow: 'hidden',
                }}
              >
                <DashboardRenderer plan={plan} />
              </div>
            </section>
          );
        })}
      </div>
    </main>
  );
}
