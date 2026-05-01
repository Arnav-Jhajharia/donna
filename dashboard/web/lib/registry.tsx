'use client';

/**
 * Block registry — maps Block.type → a content renderer that lives inside
 * a <Frame>. The registry is the only thing that knows how to turn a block
 * spec into UI in the new row-based path.
 *
 * Content renderers MUST NOT render their own border, radius, padding, or
 * background. Frame owns chrome. They render kicker / title / body and any
 * inline primitives (checkbox, tap-chip, pill, progress, source, note).
 *
 * If the brain emits a kind without a registered renderer, the cell shows
 * a <PlaceholderFrame> with the kind name. This is the visual contract's
 * fallback — see system.html §2.
 *
 * Adding a new block kind is two steps:
 *   1) extend the Block union in plan.ts
 *   2) register a renderer here
 */

import type { ReactNode } from 'react';
import type {
  Block,
  CelebrationBlock,
  ConfrontationBlock,
  HeroBlock,
  NewsBriefBlock,
  NoteBlock,
  NudgeGridBlock,
  OpenLoopsBlock,
  PermissionBlock,
  ReflectionBlock,
  RelationshipBlock,
  RemindersBlock,
  ThesisBlock,
  TodoListBlock,
  TrackerGridBlock,
  TrackerStarterBlock,
  WeatherOfYouBlock,
  WhisperBlock,
  WitnessBlock,
  CalendarShapeBlock,
  FooterBlock,
} from './plan';
import { useAction } from './action-context';
import { Frame, PlaceholderFrame } from '@/components/Frame';
import NoteBlockComponent from '@/components/blocks/NoteBlock';
import CatTrackerComp from '@/components/blocks/catalogue/CatTracker';
import CatCapabilityComp from '@/components/blocks/catalogue/CatCapability';
import {
  CatWatch,
  CatBrief,
  CatPrep,
  CatSchedule,
  CatStreak,
  CatPerson,
  CatReminder,
  CatQuickLog,
  CatPick,
  CatOffer,
  CatDraft,
  CatDecision,
  CatConfront,
  CatReflection,
  CatOpenLoop,
  CatPermission,
  CatRead,
} from '@/components/blocks/catalogue/CatBlocks';
import type {
  CatTrackerSpec,
  CatWatchSpec,
  CatBriefSpec,
  CatPrepSpec,
  CatScheduleSpec,
  CatStreakSpec,
  CatPersonSpec,
  CatReminderSpec,
  CatQuickLogSpec,
  CatPickSpec,
  CatOfferSpec,
  CatDraftSpec,
  CatDecisionSpec,
  CatConfrontSpec,
  CatReflectionSpec,
  CatOpenLoopSpec,
  CatPermissionSpec,
  CatReadSpec,
  CatCapabilitySpec,
} from './plan';

type Renderer<B extends Block> = (block: B) => ReactNode;

// ── Per-kind content renderers ────────────────────────────────────────────

const renderThesis: Renderer<ThesisBlock> = (b) => (
  <Frame kicker={b.kicker}>
    <p
      className="frame__body"
      style={{ fontFamily: 'var(--font-serif)', fontSize: 22, lineHeight: '28px', color: 'var(--ink-900)' }}
    >
      {b.sentence}
    </p>
  </Frame>
);

const renderHero: Renderer<HeroBlock> = (b) => (
  // Hero in row context becomes a Frame with the date kicker + greeting.
  <Frame kicker={b.date}>
    <p style={{ fontFamily: 'var(--font-serif)', fontSize: 32, lineHeight: '36px', margin: 0, color: 'var(--ink-900)' }}>
      {b.greeting}
    </p>
    {b.subtext && <p className="frame__body" style={{ marginTop: 8 }}>{b.subtext}</p>}
  </Frame>
);

const renderWhisper: Renderer<WhisperBlock> = (b) => (
  <Frame kicker={b.kicker}>
    <p className="whisper-body">{b.body}</p>
  </Frame>
);

const renderWitness: Renderer<WitnessBlock> = (b) => (
  <Frame kicker={b.source ? `from ${b.source}` : undefined}>
    <p className="frame__body">{b.observation}</p>
  </Frame>
);

const renderConfrontation: Renderer<ConfrontationBlock> = (b) => (
  <Frame title={b.title}>
    <p className="frame__kicker confront-kicker">this is the third week</p>
    <p className="frame__body">{b.body}</p>
    {b.ask && (
      <div style={{ marginTop: 'auto', paddingTop: 16, display: 'flex', gap: 12 }}>
        <button className="tap-chip">keep</button>
        <button className="tap-chip" style={{ color: 'var(--ink-500)' }}>skip</button>
      </div>
    )}
  </Frame>
);

const renderCelebration: Renderer<CelebrationBlock> = (b) => (
  <Frame kicker={b.badge}>
    <h3 style={{ fontFamily: 'var(--font-serif)', fontSize: 28, lineHeight: '32px', margin: '0 0 12px', color: 'var(--ink-900)' }}>
      {b.title}
    </h3>
    <p className="frame__body">{b.body}</p>
  </Frame>
);

const renderReflection: Renderer<ReflectionBlock> = (b) => (
  <Frame title={b.title}>
    <ul style={{ margin: 0, paddingLeft: 18, fontFamily: 'var(--font-serif)', fontSize: 18, lineHeight: '28px', color: 'var(--ink-700)' }}>
      {b.prompts.map((p, i) => (
        <li key={i} style={{ marginBottom: 8 }}>{p}</li>
      ))}
    </ul>
  </Frame>
);

const renderOpenLoops: Renderer<OpenLoopsBlock> = (b) => (
  <Frame title={b.title}>
    <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
      {b.items.map((item) => (
        <li key={item.id} style={{ padding: '10px 0', borderBottom: '1px solid var(--alpha-ink-08)' }}>
          <p className="frame__title" style={{ marginBottom: 4 }}>{item.title}</p>
          <p style={{ fontFamily: 'var(--font-sans)', fontSize: 13, color: 'var(--ink-500)', margin: 0 }}>
            {item.commitment} · <span className="source">{item.age}</span>
          </p>
        </li>
      ))}
    </ul>
  </Frame>
);

const renderWeatherOfYou: Renderer<WeatherOfYouBlock> = (b) => (
  <Frame kicker="weather of you">
    <h4 className="frame__title">{b.mood}</h4>
    <div className="progress" style={{ margin: '8px 0' }}>
      <div className="progress__fill" style={{ width: `${Math.round(b.energy * 100)}%` }} />
    </div>
    <p className="tracker-sub">{b.basis}</p>
  </Frame>
);

const renderCalendarShape: Renderer<CalendarShapeBlock> = (b) => (
  <Frame title={b.title}>
    {b.shapeRead && <p className="frame__body" style={{ marginBottom: 12 }}>{b.shapeRead}</p>}
    <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
      {b.slots.map((s) => (
        <li key={s.id} style={{ padding: '6px 0', borderBottom: '1px solid var(--alpha-ink-08)', display: 'flex', gap: 12 }}>
          <span style={{ fontFamily: 'var(--font-sans)', fontSize: 13, color: 'var(--ink-500)', fontVariantNumeric: 'tabular-nums', width: 56 }}>{s.at}</span>
          <span style={{ fontFamily: 'var(--font-sans)', fontSize: 14, color: 'var(--ink-900)' }}>{s.label}</span>
        </li>
      ))}
    </ul>
  </Frame>
);

function ChipRow({ children }: { children: ReactNode }) {
  return <div style={{ marginTop: 'auto', paddingTop: 16, display: 'flex', alignItems: 'center', gap: 12 }}>{children}</div>;
}

const RenderTodoList = (b: TodoListBlock) => {
  const dispatch = useAction();
  return (
    <Frame title={b.title}>
      <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {b.items.map((item) => (
          <li
            key={item.id}
            style={{
              padding: '10px 0',
              borderBottom: '1px solid var(--alpha-ink-08)',
              display: 'flex',
              alignItems: 'flex-start',
              gap: 12,
              opacity: item.done ? 0.55 : 1,
            }}
          >
            <span
              className={item.done ? 'checkbox checkbox--done' : 'checkbox'}
              role="button"
              tabIndex={0}
              onClick={() => item.action && dispatch(item.action)}
              onKeyDown={(e) => {
                if ((e.key === 'Enter' || e.key === ' ') && item.action) {
                  e.preventDefault();
                  dispatch(item.action);
                }
              }}
              aria-pressed={item.done}
            />
            <div style={{ flex: 1 }}>
              <p
                className="frame__title"
                style={{
                  marginBottom: 2,
                  textDecoration: item.done ? 'line-through' : 'none',
                  textDecorationColor: 'var(--ink-400)',
                }}
              >
                {item.label}
              </p>
              <p style={{ fontFamily: 'var(--font-sans)', fontSize: 13, color: 'var(--ink-500)', margin: 0 }}>
                {item.meta} · <span className="source">from {item.source}</span>
              </p>
            </div>
          </li>
        ))}
      </ul>
    </Frame>
  );
};

const renderTrackerGrid: Renderer<TrackerGridBlock> = (b) => (
  <Frame title={b.title}>
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Math.min(b.items.length, 3)}, 1fr)`, gap: 16 }}>
      {b.items.map((t) => (
        <div key={t.id}>
          <p className="frame__kicker" style={{ marginBottom: 4 }}>{t.title}</p>
          <div>
            <span className="tracker-num" style={{ fontSize: 32, lineHeight: 1 }}>{t.value}</span>
            <span className="tracker-unit">{t.unit}</span>
          </div>
          <p className="tracker-sub">{t.sub}</p>
          {typeof t.progress === 'number' && (
            <div className="progress" style={{ marginTop: 8 }}>
              <div className="progress__fill" style={{ width: `${Math.round(t.progress * 100)}%` }} />
            </div>
          )}
        </div>
      ))}
    </div>
  </Frame>
);

const RenderNudgeGrid = (b: NudgeGridBlock) => {
  const dispatch = useAction();
  return (
    <Frame title={b.title}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12 }}>
        {b.items.map((n) => (
          <button
            key={n.id}
            onClick={() => n.action && dispatch(n.action)}
            style={{
              textAlign: 'left',
              background: n.variant === 'featured' ? 'var(--rust-100)' : 'var(--paper-300)',
              border: '1px solid var(--alpha-ink-08)',
              borderRadius: 'var(--radius-md)',
              padding: 12,
              cursor: 'pointer',
              fontFamily: 'inherit',
            }}
          >
            <p className="frame__title" style={{ marginBottom: 2 }}>{n.title}</p>
            <p style={{ fontFamily: 'var(--font-sans)', fontSize: 12, color: 'var(--ink-500)', margin: '0 0 6px' }}>{n.meta}</p>
            <span className="tap-chip">{n.cta}</span>
          </button>
        ))}
      </div>
    </Frame>
  );
};

const RenderPermission = (b: PermissionBlock) => {
  const dispatch = useAction();
  return (
    <Frame
      kicker="permission"
      onClick={b.action ? () => dispatch(b.action!) : undefined}
      variant={b.action ? 'tappable' : 'default'}
    >
      <h4 className="frame__title" style={{ fontStyle: 'italic', fontFamily: 'var(--font-serif)', fontWeight: 500, fontSize: 18 }}>
        {b.title}
      </h4>
      <p className="frame__body">{b.body}</p>
    </Frame>
  );
};

const RenderReminders = (b: RemindersBlock) => {
  const dispatch = useAction();
  return (
    <Frame title={b.title}>
      <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {b.items.map((r) => (
          <li
            key={r.id}
            style={{
              padding: '10px 0',
              borderBottom: '1px solid var(--alpha-ink-08)',
              display: 'flex',
              gap: 12,
              opacity: r.done ? 0.55 : 1,
            }}
          >
            <span style={{ fontFamily: 'var(--font-sans)', fontSize: 13, color: 'var(--ink-500)', fontVariantNumeric: 'tabular-nums', width: 72, paddingTop: 2 }}>
              {r.at}
            </span>
            <div style={{ flex: 1 }}>
              <p className="frame__title" style={{ marginBottom: 2, textDecoration: r.done ? 'line-through' : 'none' }}>
                {r.label}
              </p>
              {r.meta && <p style={{ fontFamily: 'var(--font-sans)', fontSize: 13, color: 'var(--ink-500)', margin: 0 }}>{r.meta}</p>}
            </div>
            <span
              className={r.done ? 'checkbox checkbox--done' : 'checkbox'}
              role="button"
              tabIndex={0}
              onClick={() => r.action && dispatch(r.action)}
              aria-pressed={r.done}
            />
          </li>
        ))}
      </ul>
    </Frame>
  );
};

const RenderTrackerStarter = (b: TrackerStarterBlock) => {
  const dispatch = useAction();
  return (
    <Frame
      kicker="i'd like to start tracking"
      title={<><em>{b.trackerName}</em></>}
      onClick={() => dispatch(b.action)}
      variant="tappable"
    >
      <p className="whisper-body" style={{ marginBottom: 12 }}>{b.rationale}</p>
      <ChipRow>
        <span className="tap-chip" style={{ marginLeft: 'auto' }}>{b.cta}</span>
      </ChipRow>
    </Frame>
  );
};

const RenderRelationship = (b: RelationshipBlock) => {
  const dispatch = useAction();
  return (
    <Frame title={b.title}>
      <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {b.items.map((p) => (
          <li
            key={p.id}
            style={{ padding: '10px 0', borderBottom: '1px solid var(--alpha-ink-08)', display: 'flex', gap: 12, alignItems: 'center', cursor: p.action ? 'pointer' : 'default' }}
            onClick={() => p.action && dispatch(p.action)}
          >
            <span
              style={{
                width: 32,
                height: 32,
                borderRadius: '50%',
                background: 'var(--rust-100)',
                color: 'var(--rust-700)',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontFamily: 'var(--font-serif)',
                fontWeight: 500,
              }}
            >
              {p.initial}
            </span>
            <div style={{ flex: 1 }}>
              <p className="frame__title" style={{ marginBottom: 0 }}>
                {p.name}{p.role && <span style={{ color: 'var(--ink-500)', fontWeight: 400 }}> · {p.role}</span>}
              </p>
              <p style={{ fontFamily: 'var(--font-sans)', fontSize: 13, color: 'var(--ink-500)', margin: 0 }}>{p.lastTouch}</p>
              {p.nudge && <p className="note" style={{ marginTop: 8 }}>{p.nudge}</p>}
            </div>
          </li>
        ))}
      </ul>
    </Frame>
  );
};

const RenderNewsBrief = (b: NewsBriefBlock) => {
  const dispatch = useAction();
  return (
    <Frame title={b.title}>
      <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {b.items.map((n) => (
          <li
            key={n.id}
            style={{ padding: '12px 0', borderBottom: '1px solid var(--alpha-ink-08)', cursor: n.action ? 'pointer' : 'default' }}
            onClick={() => n.action && dispatch(n.action)}
          >
            {n.tag && <p className="frame__kicker" style={{ marginBottom: 4 }}>{n.tag}</p>}
            <p style={{ fontFamily: 'var(--font-serif)', fontWeight: 500, fontSize: 18, lineHeight: '24px', color: 'var(--ink-900)', margin: '0 0 4px' }}>
              {n.headline}
            </p>
            <p className="source">from {n.source}</p>
          </li>
        ))}
      </ul>
    </Frame>
  );
};

const renderFooter: Renderer<FooterBlock> = (b) => (
  <Frame>
    <p className="frame__body" style={{ textAlign: 'center', color: 'var(--ink-500)' }}>{b.text}</p>
  </Frame>
);

// note (#02) — borderless by design; no Frame wrap. The block component
// handles kind=editorial/bar/confront internally per the catalogue spec.
const renderNote: Renderer<NoteBlock> = (b) => <NoteBlockComponent spec={b} />;

// ── Registry ─────────────────────────────────────────────────────────────

type AnyRenderer = (block: Block) => ReactNode;

const REGISTRY: Record<Block['type'], AnyRenderer> = {
  thesis:           ((b: Block) => renderThesis(b as ThesisBlock)),
  hero:             ((b: Block) => renderHero(b as HeroBlock)),
  whisper:          ((b: Block) => renderWhisper(b as WhisperBlock)),
  witness:          ((b: Block) => renderWitness(b as WitnessBlock)),
  confrontation:    ((b: Block) => renderConfrontation(b as ConfrontationBlock)),
  celebration:      ((b: Block) => renderCelebration(b as CelebrationBlock)),
  reflection:       ((b: Block) => renderReflection(b as ReflectionBlock)),
  'open-loops':     ((b: Block) => renderOpenLoops(b as OpenLoopsBlock)),
  'weather-of-you': ((b: Block) => renderWeatherOfYou(b as WeatherOfYouBlock)),
  'calendar-shape': ((b: Block) => renderCalendarShape(b as CalendarShapeBlock)),
  'todo-list':      ((b: Block) => RenderTodoList(b as TodoListBlock)),
  'tracker-grid':   ((b: Block) => renderTrackerGrid(b as TrackerGridBlock)),
  'nudge-grid':     ((b: Block) => RenderNudgeGrid(b as NudgeGridBlock)),
  permission:       ((b: Block) => RenderPermission(b as PermissionBlock)),
  reminders:        ((b: Block) => RenderReminders(b as RemindersBlock)),
  'tracker-starter':((b: Block) => RenderTrackerStarter(b as TrackerStarterBlock)),
  relationship:     ((b: Block) => RenderRelationship(b as RelationshipBlock)),
  'news-brief':     ((b: Block) => RenderNewsBrief(b as NewsBriefBlock)),
  note:             ((b: Block) => renderNote(b as NoteBlock)),
  footer:           ((b: Block) => renderFooter(b as FooterBlock)),
  // catalogue archetypes — render directly, no Frame wrapper (each handles
  // its own visual treatment per the catalogue specimen).
  'c-tracker':      ((b: Block) => <CatTrackerComp spec={b as CatTrackerSpec} />),
  'c-watch':        ((b: Block) => <CatWatch spec={b as CatWatchSpec} />),
  'c-brief':        ((b: Block) => <CatBrief spec={b as CatBriefSpec} />),
  'c-prep':         ((b: Block) => <CatPrep spec={b as CatPrepSpec} />),
  'c-schedule':     ((b: Block) => <CatSchedule spec={b as CatScheduleSpec} />),
  'c-streak':       ((b: Block) => <CatStreak spec={b as CatStreakSpec} />),
  'c-person':       ((b: Block) => <CatPerson spec={b as CatPersonSpec} />),
  'c-reminder':     ((b: Block) => <CatReminder spec={b as CatReminderSpec} />),
  'c-quicklog':     ((b: Block) => <CatQuickLog spec={b as CatQuickLogSpec} />),
  'c-pick':         ((b: Block) => <CatPick spec={b as CatPickSpec} />),
  'c-offer':        ((b: Block) => <CatOffer spec={b as CatOfferSpec} />),
  'c-draft':        ((b: Block) => <CatDraft spec={b as CatDraftSpec} />),
  'c-decision':     ((b: Block) => <CatDecision spec={b as CatDecisionSpec} />),
  'c-confront':     ((b: Block) => <CatConfront spec={b as CatConfrontSpec} />),
  'c-reflection':   ((b: Block) => <CatReflection spec={b as CatReflectionSpec} />),
  'c-openloop':     ((b: Block) => <CatOpenLoop spec={b as CatOpenLoopSpec} />),
  'c-permission':   ((b: Block) => <CatPermission spec={b as CatPermissionSpec} />),
  'c-read':         ((b: Block) => <CatRead spec={b as CatReadSpec} />),
  'c-capability':   ((b: Block) => <CatCapabilityComp spec={b as CatCapabilitySpec} />),
};

/** Render a single block through the registry, returning a Frame-wrapped node. */
export function renderBlock(block: Block): ReactNode {
  const renderer = REGISTRY[block.type];
  if (!renderer) return <PlaceholderFrame kind={String((block as { type?: string }).type ?? 'unknown')} />;
  return renderer(block);
}
