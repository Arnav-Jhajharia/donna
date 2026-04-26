/**
 * Expansion blocks · live preview.
 *
 * Renders all six expansion Lego blocks with demo data so the team can see
 * them in the Next.js runtime. Mirrors the showcase HTML, but live.
 */

import { ScreenRoot } from '@/components/ds';
import {
  DryRunOfferBlock,
  InvitationPromptBlock,
  LifecycleBandBlock,
  MiniStatGridBlock,
  ProvenanceFactRowBlock,
  SparklineStatusBlock,
} from '@/components/blocks/expansion';
import type {
  DryRunOfferBlock as DryRunOfferSpec,
  InvitationPromptBlock as InvitationPromptSpec,
  LifecycleBandBlock as LifecycleBandSpec,
  MiniStatGridBlock as MiniStatGridSpec,
  ProvenanceFactRowBlock as ProvenanceFactRowSpec,
  SparklineStatusBlock as SparklineStatusSpec,
} from '@/lib/expansion-blocks';

const sparkline: SparklineStatusSpec = {
  type: 'sparkline-status',
  title: 'lunch · last 7 days',
  days: [
    { state: 'miss' }, { state: 'hit' }, { state: 'miss' }, { state: 'miss' },
    { state: 'half' }, { state: 'hit' }, { state: 'miss' },
  ],
  window: 'mon → sun',
  hitCount: 2,
  total: 7,
};

const provenance: ProvenanceFactRowSpec = {
  type: 'provenance-facts',
  title: 'aarav, partial',
  rows: [
    { key: 'place',   value: 'mumbai · bandra',                  kind: 'told-me',  detail: 'tuesday 9:14' },
    { key: 'season',  value: 'antler quarter',                   kind: 'inferred', detail: 'confidence 0.68' },
    { key: 'pattern', value: 'sleeps poorly when priya slips',   kind: 'observed', detail: '3 weeks of chat' },
    { key: 'people',  value: 'priya · luca · dad · oscar',       kind: 'observed', detail: 'named 12× in 14 days' },
  ],
};

const dryrun: DryRunOfferSpec = {
  type: 'dryrun-offer',
  kind: 'event_stream',
  status: 'dry-run · awaiting you',
  headline: { prefix: 'keep an eye on ', accent: 'luca' },
  body: 'the antler deck thread, not email. daily 07:30 check-in. first update tomorrow.',
  sources: ['email', 'calendar', 'chat'],
  actions: { live: 'live', tweak: 'tweak', dismiss: 'not yet' },
};

const invitation: InvitationPromptSpec = {
  type: 'invitation-prompt',
  eyebrow: 'ask me to',
  verb: 'watch',
  placeholder: 'keep an eye on ',
  hints: ['priya', 'luca — antler', 'my cofounder', "the shipment from oscar's"],
};

const miniStats: MiniStatGridSpec = {
  type: 'mini-stats',
  cells: [
    { key: 'calories', value: '820', total: '/2,200', sub: 'chicken bowl at 1:30' },
    { key: 'water',    value: '3',   total: '/8',     sub: 'so far today' },
    { key: 'loops',    value: '2',                    sub: 'open · dad, priya' },
  ],
};

const bands: LifecycleBandSpec[] = [
  { type: 'lifecycle-band', state: 'live',     label: 'live · running',           count: 8  },
  { type: 'lifecycle-band', state: 'shadow',   label: 'shadow · watching quietly', count: 3  },
  { type: 'lifecycle-band', state: 'paused',   label: 'paused · you said not yet', count: 2  },
  { type: 'lifecycle-band', state: 'resolved', label: 'resolved · harvested',      count: 12 },
];

export default function ExpansionPage() {
  return (
    <ScreenRoot>
      <main
        style={{
          minHeight: '100vh',
          background: 'var(--color-paper)',
          paddingTop: 48,
          paddingBottom: 96,
        }}
      >
        <header style={{ maxWidth: 880, margin: '0 auto var(--space-7)', padding: '0 var(--space-5)' }}>
          <div className="type-label">expansion · six new lego blocks</div>
          <h1
            className="type-h1"
            style={{ color: 'var(--color-ink)', margin: 'var(--space-3) 0 var(--space-4)' }}
          >
            innovation from <em className="italic-accent-heading" style={{ color: 'var(--color-rust)' }}>simplicity</em>.
          </h1>
          <p className="type-lead" style={{ color: 'var(--color-muted)', maxWidth: '58ch' }}>
            extracted from the 12 day-one surfaces. zero new tokens. each unlocks a
            just-in-time pattern the primary seven blocks don't cover.
          </p>
        </header>

        <div style={{ maxWidth: 880, margin: '0 auto' }}>
          <SparklineStatusBlock   spec={sparkline} />
          <ProvenanceFactRowBlock spec={provenance} />
          <DryRunOfferBlock       spec={dryrun} />
          <InvitationPromptBlock  spec={invitation} />
          <MiniStatGridBlock      spec={miniStats} />

          <div style={{ marginTop: 'var(--space-7)', padding: '0 var(--space-4)' }}>
            <div className="type-label">lifecycle bands · every attention, visible</div>
          </div>
          {bands.map((b) => (
            <LifecycleBandBlock key={b.state} spec={b} />
          ))}
        </div>
      </main>
    </ScreenRoot>
  );
}
