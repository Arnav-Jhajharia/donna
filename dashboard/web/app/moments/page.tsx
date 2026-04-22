import DashboardRenderer from '@/components/DashboardRenderer';
import type { DashboardPlan } from '@/lib/plan';
import { planDensity } from '@/lib/plan';
import { morningCrispPlan } from '@/lib/plans/morning-crisp';
import { morningAfterBadDayPlan } from '@/lib/plans/morning-after-bad-day';
import { middayCheckPlan } from '@/lib/plans/midday-check';
import { eveningReflectionPlan } from '@/lib/plans/evening-reflection';
import { celebrationMomentPlan } from '@/lib/plans/celebration-moment';
import { lowEnergyPlan } from '@/lib/plans/low-energy';

interface GalleryEntry {
  plan: DashboardPlan;
  label: string;
  subtitle: string;
}

const GALLERY: GalleryEntry[] = [
  {
    plan: morningCrispPlan,
    label: 'morning · crisp',
    subtitle: 'slept well · calendar is reasonable · forward-leaning',
  },
  {
    plan: morningAfterBadDayPlan,
    label: 'morning · after a hard day',
    subtitle: 'four hours sleep · recovery register · permission + witness',
  },
  {
    plan: middayCheckPlan,
    label: 'midday · drive-by',
    subtitle: 'short, functional, trackers + one open loop',
  },
  {
    plan: eveningReflectionPlan,
    label: 'evening · reflection',
    subtitle: 'thesis is a question · prompts + gentle confrontation',
  },
  {
    plan: celebrationMomentPlan,
    label: 'celebration · something landed',
    subtitle: 'lead with the landing · one witness · forward-look',
  },
  {
    plan: lowEnergyPlan,
    label: 'late · restraint',
    subtitle: 'user is spiralling · donna chooses small',
  },
];

export default function MomentsPage() {
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
          donna · dashboard
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
          moments
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
          the same user, different moments. each plan commits to one thesis and picks blocks
          that serve it. the dashboard is not a feed — it's a point of view.
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
        {GALLERY.map((entry) => (
          <MomentColumn key={entry.plan.id} entry={entry} />
        ))}
      </div>
    </main>
  );
}

function MomentColumn({ entry }: { entry: GalleryEntry }) {
  const density = planDensity(entry.plan);
  return (
    <section>
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
            {entry.label}
          </div>
          <div
            style={{
              fontSize: 10,
              color: 'var(--fg-placeholder)',
              letterSpacing: '0.08em',
              fontFamily: 'var(--font-sans)',
            }}
          >
            density {density}/12
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
          {entry.subtitle}
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
          <span style={{ marginRight: 8 }}>thesis</span>
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
            {entry.plan.thesis}
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
        <DashboardRenderer plan={entry.plan} />
      </div>
    </section>
  );
}
