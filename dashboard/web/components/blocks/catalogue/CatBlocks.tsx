/**
 * Catalogue archetypes #05–#21, ported faithfully from the design specimen.
 * Each archetype exports one component and all its visual variants.
 * Tracker (#04) is in CatTracker.tsx separately because it carries 3 variants
 * with richer schema; the rest live here for compactness.
 */

'use client';

import { useState } from 'react';
import ActionChip from '@/components/ActionChip';
import TapToTalk from '@/components/TapToTalk';
import type { ActionVerb } from '@/lib/plan';
import { tallyLogPrimer } from '@/lib/wa-deeplink';
import { cIcons, type CatIconName } from './icons';
import { SERIF, SANS, BORDER, BORDER_STRONG, BORDER_ACCENT, Eyebrow, SectionHead } from './atoms';

// Generic block-footer action chip strip. Composer can decorate any block
// with ``actions`` and the footer renders them in order. Tone is inferred
// from verb type — affirmative verbs lean rust, destructive lean
// destructive, neutral lean paper.
export function BlockActions({ actions, align = 'right' }: { actions?: ActionVerb[]; align?: 'left' | 'right' | 'center' }) {
  if (!actions || actions.length === 0) return null;
  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 8,
        margin: '12px 22px 0',
        justifyContent:
          align === 'right' ? 'flex-end' : align === 'center' ? 'center' : 'flex-start',
      }}
    >
      {actions.map((verb, i) => (
        <ActionChip
          key={`${verb.v}-${i}`}
          verb={verb}
          tone={toneForVerb(verb)}
          size="sm"
        >
          {labelForVerb(verb)}
        </ActionChip>
      ))}
    </div>
  );
}

export function toneForVerb(verb: ActionVerb): 'rust' | 'paper' | 'amber' | 'moss' | 'oxblood' | 'destructive' {
  switch (verb.v) {
    case 'mark_reminder_done':
    case 'complete_pick':
    case 'log_value':
    case 'quick_log':
      return 'moss';
    case 'accept_attention':
    case 'accept_draft':
    case 'start_tracker':
      return 'rust';
    case 'decide_option':
      return 'amber';
    case 'dismiss_attention':
      return 'destructive';
    case 'snooze_reminder':
      return 'paper';
    case 'open_attention':
      return 'rust';
    case 'connect_integration':
    case 'open_relationship':
    case 'open_news':
    case 'open_tracker':
    case 'reply_chip':
    default:
      return 'paper';
  }
}

export function labelForVerb(verb: ActionVerb): string {
  switch (verb.v) {
    case 'mark_reminder_done': return 'mark done';
    case 'snooze_reminder':    return 'snooze';
    case 'complete_pick':      return 'keep';
    case 'decide_option':      return 'pick this';
    case 'accept_attention':   return 'yes';
    case 'dismiss_attention':  return 'not now';
    case 'accept_draft':       return 'send it';
    case 'start_tracker':      return `start ${verb.name}`;
    case 'log_value':          return 'log';
    case 'quick_log':          return verb.kind || 'log';
    case 'connect_integration': return `connect ${verb.provider}`;
    case 'open_relationship':  return 'open';
    case 'open_news':          return 'open';
    case 'open_tracker':       return 'see all';
    case 'open_attention':     return 'open';
    case 'reply_chip':         return verb.intent;
    default:                   return 'do';
  }
}

// ═════════════════════════════════════════════════════════════════════════
// 05 · WATCH
// ═════════════════════════════════════════════════════════════════════════
export interface WatchItem {
  subject: string;
  signal: string;
  at: string;
  delta?: string;
  up?: boolean;
  /** Backing attention id; if present, tapping the row opens the
   *  AttentionSheet instead of falling back to a WhatsApp primer. */
  attention_id?: string;
}
export interface CatWatchSpec {
  type: 'c-watch';
  variant: 'rows' | 'ticker';
  title?: string;
  items: WatchItem[];
  /** Optional footer actions, rendered as ActionChips by BlockActions. */
  actions?: ActionVerb[];
}
export function CatWatch({ spec }: { spec: CatWatchSpec }) {
  if (spec.variant === 'ticker') return <WatchTicker spec={spec} />;
  return <WatchRows spec={spec} />;
}
function WatchRows({ spec }: { spec: CatWatchSpec }) {
  return (
    <div style={{ margin: '12px 22px 0' }}>
      <SectionHead title={spec.title ?? "what i've got eyes on"} />
      {spec.items.map((it, i) => (
        <TapToTalk
          key={i}
          attentionId={it.attention_id}
          primer={`tell me more about ${it.subject}`}
          decoration="row"
          style={{
            display: 'grid',
            gridTemplateColumns: '14px 1fr auto',
            gap: 10,
            padding: '10px 0',
            borderBottom: `1px solid ${BORDER}`,
            alignItems: 'baseline',
          }}
        >
          <cIcons.eye s={12} c="var(--rust-700)" />
          <div>
            <div style={{ fontFamily: SANS, fontSize: 13.5, color: 'var(--ink-900)', fontWeight: 500 }}>
              {it.subject}
              {it.delta && (
                <span
                  style={{
                    color: it.up ? 'var(--moss-700)' : 'var(--oxblood-700)',
                    fontFamily: SANS,
                    fontSize: 11.5,
                    marginLeft: 6,
                  }}
                >
                  {it.delta}
                </span>
              )}
            </div>
            <div style={{ fontFamily: SANS, fontSize: 12, color: 'var(--ink-500)', marginTop: 2, lineHeight: 1.4 }}>
              {it.signal}
            </div>
          </div>
          <span style={{ fontFamily: SANS, fontSize: 10.5, color: 'var(--ink-400)' }}>{it.at}</span>
        </TapToTalk>
      ))}
      <BlockActions actions={spec.actions} />
    </div>
  );
}
function WatchTicker({ spec }: { spec: CatWatchSpec }) {
  return (
    <div style={{ margin: '12px 16px 0', display: 'flex', flexDirection: 'column', gap: 8 }}>
      <SectionHead title={spec.title ?? 'watching'} />
      {spec.items.map((it, i) => (
        <div
          key={i}
          style={{
            background: 'var(--paper-100)',
            border: `1px solid ${BORDER}`,
            borderRadius: 12,
            padding: '12px 14px',
            display: 'flex',
            alignItems: 'center',
            gap: 12,
          }}
        >
          <div
            style={{
              width: 34,
              height: 34,
              borderRadius: 8,
              background: 'var(--paper-300)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontFamily: SANS,
              fontSize: 11,
              fontWeight: 600,
              color: 'var(--ink-900)',
              letterSpacing: '0.02em',
            }}
          >
            {it.subject.slice(0, 4)}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontFamily: SERIF, fontSize: 15, fontWeight: 500, color: 'var(--ink-900)', lineHeight: 1.2 }}>
              {it.subject}
            </div>
            <div
              style={{
                fontFamily: SANS,
                fontSize: 11.5,
                color: 'var(--ink-500)',
                marginTop: 2,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {it.signal}
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            {it.delta && (
              <div
                style={{
                  fontFamily: SANS,
                  fontSize: 13,
                  color: it.up ? 'var(--moss-700)' : 'var(--rust-700)',
                  fontWeight: 500,
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {it.delta}
              </div>
            )}
            <div style={{ fontFamily: SANS, fontSize: 10, color: 'var(--ink-400)', marginTop: 2 }}>{it.at}</div>
          </div>
        </div>
      ))}
      <BlockActions actions={spec.actions} />
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════
// 06 · BRIEF
// ═════════════════════════════════════════════════════════════════════════
export interface BriefIndexItem { subject: string; cadence: string; nextFire: string; attention_id?: string; }
export interface CatBriefSpec {
  type: 'c-brief';
  variant: 'newsstand' | 'index';
  // newsstand
  cadenceLabel?: string;
  fireWindow?: string;
  title?: string;
  highlight?: string;
  teaser?: string;
  chips?: string[];
  // index
  items?: BriefIndexItem[];
  /** Optional footer actions, rendered as ActionChips by BlockActions. */
  actions?: ActionVerb[];
}
export function CatBrief({ spec }: { spec: CatBriefSpec }) {
  if (spec.variant === 'index') {
    return (
      <div style={{ margin: '12px 22px 0' }}>
        <SectionHead title="briefs i run for you" />
        <div style={{ marginTop: 6 }}>
          {(spec.items ?? []).map((b, i) => (
            <TapToTalk
              key={i}
              attentionId={b.attention_id}
              primer={`tell me about the ${b.subject} brief`}
              decoration="row"
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr auto',
                gap: 8,
                padding: '12px 0',
                borderBottom: `1px solid ${BORDER}`,
                alignItems: 'baseline',
              }}
            >
              <div>
                <div style={{ fontFamily: SERIF, fontSize: 16, fontWeight: 500, color: 'var(--ink-900)', lineHeight: 1.2 }}>
                  {b.subject}
                </div>
                <div style={{ fontFamily: SANS, fontSize: 11.5, color: 'var(--ink-500)', marginTop: 2 }}>{b.cadence}</div>
              </div>
              <span style={{ fontFamily: SANS, fontSize: 11, color: 'var(--rust-700)', fontWeight: 500 }}>
                {b.nextFire}
              </span>
            </TapToTalk>
          ))}
        </div>
      </div>
    );
  }
  return (
    <TapToTalk
      primer={`open the brief: ${spec.title ?? spec.cadenceLabel ?? 'this week'}`}
      decoration="block"
      style={{
        margin: '12px 16px 0',
        padding: '16px 16px 14px',
        background: 'var(--paper-200)',
        border: `1px solid ${BORDER}`,
        borderRadius: 14,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <Eyebrow tone="var(--rust-700)">{spec.cadenceLabel ?? 'brief · weekly'}</Eyebrow>
        {spec.fireWindow && <span style={{ fontFamily: SANS, fontSize: 10, color: 'var(--ink-400)' }}>{spec.fireWindow}</span>}
      </div>
      <div
        style={{
          fontFamily: SERIF,
          fontSize: 22,
          fontWeight: 500,
          color: 'var(--ink-900)',
          marginTop: 6,
          lineHeight: 1.15,
          letterSpacing: '-0.015em',
        }}
      >
        {spec.title}{spec.highlight && <em style={{ color: 'var(--rust-700)' }}> {spec.highlight}</em>}
      </div>
      {spec.teaser && (
        <div style={{ fontFamily: SANS, fontSize: 12.5, color: 'var(--ink-500)', marginTop: 6, lineHeight: 1.5 }}>
          {spec.teaser}
        </div>
      )}
      {spec.chips && spec.chips.length > 0 && (
        <div style={{ display: 'flex', gap: 6, marginTop: 10, flexWrap: 'wrap' }}>
          {spec.chips.map((t) => (
            <span
              key={t}
              style={{
                fontFamily: SANS,
                fontSize: 10.5,
                color: 'var(--ink-500)',
                fontWeight: 500,
                border: `1px solid ${BORDER}`,
                borderRadius: 999,
                padding: '3px 8px',
                background: 'var(--paper-100)',
              }}
            >
              {t}
            </span>
          ))}
        </div>
      )}
      <BlockActions actions={spec.actions} />
    </TapToTalk>
  );
}

// ═════════════════════════════════════════════════════════════════════════
// 07 · PREP
// ═════════════════════════════════════════════════════════════════════════
export interface PrepItem { label: string; done?: boolean; }
export interface CatPrepSpec {
  type: 'c-prep';
  variant: 'inline' | 'card';
  eyebrow?: string;
  title: string;
  items: PrepItem[];
  nextLine?: string;
  meta?: string;
  /** Optional footer actions, rendered as ActionChips by BlockActions. */
  actions?: ActionVerb[];
}
export function CatPrep({ spec }: { spec: CatPrepSpec }) {
  if (spec.variant === 'card') {
    const doneCount = spec.items.filter((i) => i.done).length;
    return (
      <div
        style={{
          margin: '12px 16px 0',
          padding: '14px 14px 12px',
          background: 'var(--paper-100)',
          border: `1px solid ${BORDER_ACCENT}`,
          borderRadius: 12,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <Eyebrow tone="var(--rust-700)">{spec.eyebrow ?? 'prep'}</Eyebrow>
          {spec.meta && <span style={{ fontFamily: SANS, fontSize: 11, color: 'var(--ink-400)' }}>{spec.meta}</span>}
        </div>
        <div style={{ fontFamily: SERIF, fontSize: 18, fontWeight: 500, color: 'var(--ink-900)', marginTop: 3, lineHeight: 1.2 }}>
          {spec.title}
        </div>
        <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ flex: 1, height: 4, background: 'var(--paper-400)', borderRadius: 2, overflow: 'hidden' }}>
            <div
              style={{
                width: `${(doneCount / Math.max(1, spec.items.length)) * 100}%`,
                height: '100%',
                background: 'var(--rust-700)',
              }}
            />
          </div>
          <span style={{ fontFamily: SANS, fontSize: 11, color: 'var(--ink-500)', fontVariantNumeric: 'tabular-nums' }}>
            {doneCount} of {spec.items.length}
          </span>
        </div>
        {spec.nextLine && (
          <div style={{ fontFamily: SANS, fontSize: 12, color: 'var(--ink-500)', marginTop: 8, lineHeight: 1.45 }}>
            next: {spec.nextLine}
          </div>
        )}
      </div>
    );
  }
  // inline checklist
  return (
    <div style={{ margin: '12px 22px 0' }}>
      <Eyebrow tone="var(--rust-700)">{spec.eyebrow ?? 'prep'}</Eyebrow>
      <div
        style={{
          fontFamily: SERIF,
          fontSize: 22,
          fontWeight: 500,
          color: 'var(--ink-900)',
          marginTop: 4,
          letterSpacing: '-0.015em',
          lineHeight: 1.15,
        }}
      >
        {spec.title}
      </div>
      <div style={{ marginTop: 10 }}>
        {spec.items.map((it, i) => (
          <TapToTalk
            key={i}
            primer={it.done ? `unmark prep: ${it.label}` : `done: ${it.label}`}
            decoration="row"
            style={{
              display: 'grid',
              gridTemplateColumns: '18px 1fr',
              gap: 10,
              padding: '8px 0',
              borderBottom: `1px solid ${BORDER}`,
              alignItems: 'flex-start',
            }}
          >
            <div
              style={{
                width: 14,
                height: 14,
                borderRadius: 3,
                marginTop: 4,
                border: `1.25px solid ${it.done ? 'var(--moss-700)' : BORDER_STRONG}`,
                background: it.done ? 'var(--moss-700)' : 'transparent',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              {it.done && <cIcons.check s={9} c="var(--paper-100)" />}
            </div>
            <div
              style={{
                fontFamily: SANS,
                fontSize: 13,
                color: it.done ? 'var(--ink-500)' : 'var(--ink-900)',
                textDecoration: it.done ? 'line-through' : 'none',
                textDecorationColor: 'var(--ink-300)',
                lineHeight: 1.4,
              }}
            >
              {it.label}
            </div>
          </TapToTalk>
        ))}
      </div>
      <BlockActions actions={spec.actions} />
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════
// 08 · SCHEDULE
// ═════════════════════════════════════════════════════════════════════════
type SlotKind = 'meeting' | 'focus' | 'break' | 'travel' | 'personal';
const slotTone: Record<SlotKind, string> = {
  meeting: 'var(--rust-700)',
  focus: 'var(--moss-700)',
  break: 'var(--ink-400)',
  travel: 'var(--amber-700)',
  personal: 'var(--oxblood-700)',
};
export interface ScheduleSlot { at: string; label: string; duration: string; kind: SlotKind; }
export interface ScheduleStripBlock { x: number; w: number; kind: SlotKind; }
export interface CatScheduleSpec {
  type: 'c-schedule';
  variant: 'column' | 'strip';
  title?: string;
  right?: string;
  slots?: ScheduleSlot[];
  // strip variant
  blocks?: ScheduleStripBlock[];
  ticks?: string[];
  glance?: string;
  range?: string;
  /** Optional footer actions, rendered as ActionChips by BlockActions. */
  actions?: ActionVerb[];
}
export function CatSchedule({ spec }: { spec: CatScheduleSpec }) {
  if (spec.variant === 'strip') {
    return (
      <div
        style={{
          margin: '12px 16px 0',
          padding: '14px 14px 12px',
          background: 'var(--paper-100)',
          border: `1px solid ${BORDER}`,
          borderRadius: 12,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <Eyebrow>the day, at a glance</Eyebrow>
          {spec.range && <span style={{ fontFamily: SANS, fontSize: 10.5, color: 'var(--ink-400)' }}>{spec.range}</span>}
        </div>
        <div
          style={{
            position: 'relative',
            marginTop: 14,
            height: 24,
            background: 'var(--paper-300)',
            borderRadius: 6,
            overflow: 'hidden',
          }}
        >
          {(spec.blocks ?? []).map((b, i) => (
            <div
              key={i}
              style={{
                position: 'absolute',
                left: `${b.x}%`,
                width: `${b.w}%`,
                top: 0,
                bottom: 0,
                background: slotTone[b.kind],
                opacity: 0.85,
                borderRadius: 2,
              }}
            />
          ))}
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6 }}>
          {(spec.ticks ?? ['9', '12', '15', '18', '21']).map((t) => (
            <span key={t} style={{ fontFamily: SANS, fontSize: 10, color: 'var(--ink-400)' }}>
              {t}
            </span>
          ))}
        </div>
        {spec.glance && (
          <div style={{ fontFamily: SANS, fontSize: 12, color: 'var(--ink-700)', marginTop: 10, lineHeight: 1.5 }}>
            {spec.glance}
          </div>
        )}
      </div>
    );
  }
  // column
  return (
    <div style={{ margin: '12px 22px 0' }}>
      <SectionHead title={spec.title ?? "today's shape"} right={spec.right ?? `${(spec.slots ?? []).length} blocks`} />
      <div style={{ marginTop: 6 }}>
        {(spec.slots ?? []).map((s, i) => (
          <TapToTalk
            key={i}
            primer={`tell me about: ${s.label} at ${s.at}`}
            decoration="row"
            style={{
              display: 'grid',
              gridTemplateColumns: '52px 8px 1fr auto',
              gap: 10,
              padding: '10px 0',
              borderBottom: `1px solid ${BORDER}`,
              alignItems: 'baseline',
            }}
          >
            <span
              style={{
                fontFamily: SANS,
                fontSize: 12.5,
                color: 'var(--ink-500)',
                fontVariantNumeric: 'tabular-nums',
                fontWeight: 500,
              }}
            >
              {s.at}
            </span>
            <span
              style={{
                width: 5,
                height: 5,
                borderRadius: 999,
                background: slotTone[s.kind],
                marginTop: 7,
              }}
            />
            <span style={{ fontFamily: SANS, fontSize: 13.5, color: 'var(--ink-900)', fontWeight: 500 }}>
              {s.label}
            </span>
            <span style={{ fontFamily: SANS, fontSize: 11, color: 'var(--ink-400)' }}>{s.duration}</span>
          </TapToTalk>
        ))}
      </div>
      <BlockActions actions={spec.actions} />
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════
// 09 · STREAK / MILESTONE
// ═════════════════════════════════════════════════════════════════════════
export interface CatStreakSpec {
  type: 'c-streak';
  variant: 'inline' | 'badge';
  eyebrow: string;
  body: string;
  count?: number;
  /** Optional footer actions, rendered as ActionChips by BlockActions. */
  actions?: ActionVerb[];
}
export function CatStreak({ spec }: { spec: CatStreakSpec }) {
  if (spec.variant === 'badge') {
    return (
      <TapToTalk
        primer={`celebrate this with me: ${spec.body}`}
        decoration="block"
        style={{
          margin: '12px 16px 0',
          padding: '14px 14px',
          background: 'var(--moss-100)',
          border: `1px solid ${BORDER}`,
          borderRadius: 12,
          display: 'grid',
          gridTemplateColumns: '52px 1fr',
          gap: 14,
          alignItems: 'center',
        }}
      >
        <div
          style={{
            width: 52,
            height: 52,
            borderRadius: 999,
            background: 'var(--paper-100)',
            border: `1px solid ${BORDER}`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <div
            style={{
              fontFamily: SERIF,
              fontSize: 22,
              fontWeight: 500,
              color: 'var(--moss-700)',
              fontVariantNumeric: 'tabular-nums',
              letterSpacing: '-0.02em',
            }}
          >
            {spec.count ?? 7}
          </div>
        </div>
        <div>
          <Eyebrow tone="var(--moss-700)">{spec.eyebrow}</Eyebrow>
          <div style={{ fontFamily: SERIF, fontSize: 15, fontWeight: 500, color: 'var(--ink-900)', marginTop: 2, lineHeight: 1.3 }}>
            {spec.body}
          </div>
        </div>
      </TapToTalk>
    );
  }
  const dots = Array.from({ length: spec.count ?? 7 });
  return (
    <div style={{ margin: '12px 22px 0' }}>
      <Eyebrow tone="var(--moss-700)">{spec.eyebrow}</Eyebrow>
      <div
        style={{
          fontFamily: SERIF,
          fontSize: 22,
          fontWeight: 500,
          color: 'var(--ink-900)',
          marginTop: 4,
          letterSpacing: '-0.015em',
          lineHeight: 1.2,
        }}
      >
        {spec.body}
      </div>
      <div style={{ display: 'flex', gap: 6, marginTop: 12 }}>
        {dots.map((_, i) => (
          <div
            key={i}
            style={{
              width: 18,
              height: 18,
              borderRadius: 999,
              background: 'var(--moss-700)',
              opacity: 0.4 + i * 0.085,
            }}
          />
        ))}
      </div>
      <BlockActions actions={spec.actions} />
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════
// 10 · PERSON
// ═════════════════════════════════════════════════════════════════════════
export interface PersonItem { name: string; role?: string; nudge: string; ago: string; }
export interface CatPersonSpec {
  type: 'c-person';
  variant: 'list' | 'hero';
  title?: string;
  items?: PersonItem[];
  // hero
  heroName?: string;
  heroEyebrow?: string;
  heroBody?: string;
  ctaPrimary?: string;
  ctaSecondary?: string;
  /** Optional footer actions, rendered as ActionChips by BlockActions. */
  actions?: ActionVerb[];
}
export function CatPerson({ spec }: { spec: CatPersonSpec }) {
  if (spec.variant === 'hero') {
    const initial = (spec.heroName ?? 'K').charAt(0).toUpperCase();
    return (
      <div
        style={{
          margin: '12px 16px 0',
          padding: '16px 16px 14px',
          background: 'var(--paper-100)',
          border: `1px solid ${BORDER}`,
          borderRadius: 14,
        }}
      >
        <div style={{ display: 'grid', gridTemplateColumns: '48px 1fr', gap: 14, alignItems: 'center' }}>
          <div
            style={{
              width: 48,
              height: 48,
              borderRadius: 999,
              background: 'var(--paper-300)',
              border: `1px solid ${BORDER}`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontFamily: SERIF,
              fontSize: 18,
              fontWeight: 500,
              color: 'var(--ink-900)',
              fontStyle: 'italic',
            }}
          >
            {initial}
          </div>
          <div>
            {spec.heroEyebrow && <Eyebrow>{spec.heroEyebrow}</Eyebrow>}
            <div
              style={{
                fontFamily: SERIF,
                fontSize: 20,
                fontWeight: 500,
                color: 'var(--ink-900)',
                marginTop: 2,
                lineHeight: 1.15,
              }}
            >
              {spec.heroName}
            </div>
          </div>
        </div>
        {spec.heroBody && (
          <div style={{ fontFamily: SANS, fontSize: 13, color: 'var(--ink-700)', marginTop: 10, lineHeight: 1.5 }}>
            {spec.heroBody}
          </div>
        )}
        <div style={{ display: 'flex', gap: 8, marginTop: 10, paddingTop: 10, borderTop: `1px solid ${BORDER}` }}>
          <TapToTalk
            primer={`draft a message to ${spec.heroName}`}
            decoration="label"
            style={{
              fontFamily: SANS,
              fontSize: 11.5,
              color: 'var(--paper-100)',
              background: 'var(--rust-700)',
              padding: '5px 12px',
              borderRadius: 999,
              fontWeight: 500,
            }}
          >
            {spec.ctaPrimary ?? 'draft a thought'}
          </TapToTalk>
          <TapToTalk
            primer={`open the thread with ${spec.heroName}`}
            decoration="label"
            style={{ fontFamily: SANS, fontSize: 11.5, color: 'var(--ink-500)', padding: '5px 6px' }}
          >
            {spec.ctaSecondary ?? 'open thread'}
          </TapToTalk>
        </div>
      </div>
    );
  }
  // list (postcard)
  return (
    <div style={{ margin: '12px 22px 0' }}>
      <SectionHead title={spec.title ?? "people i've been thinking of"} />
      <div style={{ marginTop: 6 }}>
        {(spec.items ?? []).map((p, i) => {
          const initials = p.name
            .split(' ')
            .map((s) => s[0])
            .slice(0, 2)
            .join('');
          return (
            <TapToTalk
              key={i}
              primer={`tell me about ${p.name}${p.role ? ` (${p.role})` : ''}`}
              decoration="row"
              style={{
                display: 'grid',
                gridTemplateColumns: '34px 1fr auto',
                gap: 12,
                padding: '12px 0',
                borderBottom: `1px solid ${BORDER}`,
                alignItems: 'center',
              }}
            >
              <div
                style={{
                  width: 34,
                  height: 34,
                  borderRadius: 999,
                  background: 'var(--paper-300)',
                  border: `1px solid ${BORDER}`,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontFamily: SERIF,
                  fontSize: 14,
                  fontWeight: 500,
                  color: 'var(--ink-900)',
                }}
              >
                {initials}
              </div>
              <div>
                <div style={{ fontFamily: SANS, fontSize: 13.5, color: 'var(--ink-900)', fontWeight: 500 }}>
                  {p.name}
                  {p.role && <span style={{ fontWeight: 400, color: 'var(--ink-400)' }}> · {p.role}</span>}
                </div>
                <div style={{ fontFamily: SANS, fontSize: 12, color: 'var(--ink-500)', marginTop: 2, lineHeight: 1.4 }}>
                  {p.nudge}
                </div>
              </div>
              <span style={{ fontFamily: SANS, fontSize: 11, color: 'var(--ink-400)' }}>{p.ago}</span>
            </TapToTalk>
          );
        })}
      </div>
      <BlockActions actions={spec.actions} />
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════
// 11 · REMINDER
// ═════════════════════════════════════════════════════════════════════════
export interface ReminderItemCat {
  /** Stable id; required to fire mark_reminder_done / snooze_reminder. */
  id?: string;
  label: string;
  at: string;
  done?: boolean;
  /** Optional override action set for this row (advanced use). */
  actions?: ActionVerb[];
  /** Backing attention id; if present, tapping the row body opens the
   *  AttentionSheet (the per-row mark-done / snooze chips remain). */
  attention_id?: string;
}
export interface CatReminderSpec {
  type: 'c-reminder';
  variant: 'editorial' | 'pill';
  title?: string;
  right?: string;
  items: ReminderItemCat[];
  /** Block-level footer actions (e.g. "see all"). */
  actions?: ActionVerb[];
}
export function CatReminder({ spec }: { spec: CatReminderSpec }) {
  if (spec.variant === 'pill') {
    const it = spec.items[0];
    if (!it) return null;
    return (
      <div style={{ margin: '12px 16px 0' }}>
        <TapToTalk
          attentionId={it.attention_id}
          primer={`done: ${it.label}`}
          decoration="block"
          style={{
            background: 'var(--rust-100)',
            border: `1px solid ${BORDER_ACCENT}`,
            borderRadius: 999,
            padding: '10px 14px',
            display: 'grid',
            gridTemplateColumns: '18px 1fr auto',
            gap: 12,
            alignItems: 'center',
          }}
        >
          <div
            style={{
              width: 16,
              height: 16,
              borderRadius: 999,
              border: `1.4px solid var(--rust-700)`,
            }}
          />
          <span style={{ fontFamily: SANS, fontSize: 13.5, color: 'var(--ink-900)', fontWeight: 500 }}>
            {it.label}
          </span>
          <span style={{ fontFamily: SANS, fontSize: 11, color: 'var(--rust-700)', fontWeight: 500 }}>
            {it.at}
          </span>
        </TapToTalk>
      </div>
    );
  }
  const left = spec.items.filter((i) => !i.done).length;
  return (
    <div style={{ margin: '12px 22px 0' }}>
      <SectionHead
        title={spec.title ?? `${spec.items.length} small ping${spec.items.length === 1 ? '' : 's'}`}
        right={spec.right ?? `${left} left`}
      />
      <div style={{ marginTop: 8 }}>
        {spec.items.map((t, i) => (
          <ReminderRow key={t.id || i} item={t} />
        ))}
      </div>
      <BlockActions actions={spec.actions} />
    </div>
  );
}

function ReminderRow({ item: t }: { item: ReminderItemCat }) {
  // Local optimistic state — when the user taps "done" the row collapses
  // before the server ack lands so the UI feels instant.
  const initialDone = !!t.done;
  const [doneNow, setDoneNow] = useState(initialDone);
  const itemActions: ActionVerb[] = t.actions ?? (
    t.id && !doneNow
      ? [
          { v: 'mark_reminder_done', reminderId: t.id },
          {
            v: 'snooze_reminder',
            reminderId: t.id,
            until: snoozeUntil(60 * 60 * 1000), // +1h
          },
        ]
      : []
  );
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '22px 1fr auto',
        gap: 12,
        padding: '10px 0',
        borderBottom: `1px solid ${BORDER}`,
        alignItems: 'flex-start',
      }}
    >
      <div
        style={{
          width: 18,
          height: 18,
          borderRadius: 999,
          border: `1.4px solid ${doneNow ? 'var(--moss-700)' : BORDER_STRONG}`,
          background: doneNow ? 'var(--moss-700)' : 'transparent',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          marginTop: 1,
          transition: 'background-color 200ms, border-color 200ms',
        }}
      >
        {doneNow && <cIcons.check s={10} c="var(--paper-100)" />}
      </div>
      <div>
        <div
          style={{
            fontFamily: SANS,
            fontSize: 14,
            fontWeight: 500,
            color: doneNow ? 'var(--ink-500)' : 'var(--ink-900)',
            textDecoration: doneNow ? 'line-through' : 'none',
            textDecorationColor: 'var(--ink-300)',
            transition: 'color 200ms',
          }}
        >
          {t.label}
        </div>
        {itemActions.length > 0 && (
          <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
            {itemActions.map((verb, i) => {
              const tone = toneForVerb(verb);
              const label = verb.v === 'snooze_reminder' ? 'snooze 1h' : labelForVerb(verb);
              return (
                <ActionChip
                  key={`${verb.v}-${i}`}
                  verb={verb}
                  tone={tone}
                  size="sm"
                  onResult={(r) => {
                    if (r.ok && verb.v === 'mark_reminder_done') setDoneNow(true);
                  }}
                >
                  {label}
                </ActionChip>
              );
            })}
          </div>
        )}
      </div>
      <span
        style={{
          fontFamily: SANS,
          fontSize: 11,
          color: doneNow ? 'var(--moss-700)' : 'var(--rust-700)',
          fontWeight: 500,
          marginTop: 2,
        }}
      >
        {doneNow ? 'done' : t.at}
      </span>
    </div>
  );
}

function snoozeUntil(deltaMs: number): string {
  const d = new Date(Date.now() + deltaMs);
  // Local-formatted "in 1h" wording for the UI is generated by the toast.
  return d.toISOString();
}

// ═════════════════════════════════════════════════════════════════════════
// 12 · QUICK LOG
// ═════════════════════════════════════════════════════════════════════════
export interface QuickLogChip { label: string; icon: CatIconName; tint?: 'amber' | 'rust' | 'moss'; }
export interface CatQuickLogSpec {
  type: 'c-quicklog';
  variant: 'chips' | 'tray';
  chips: QuickLogChip[];
  /** Optional footer actions, rendered as ActionChips by BlockActions. */
  actions?: ActionVerb[];
}
export function CatQuickLog({ spec }: { spec: CatQuickLogSpec }) {
  if (spec.variant === 'tray') {
    const tints = {
      amber: { tint: 'var(--amber-100)', ic: 'var(--amber-700)' },
      rust: { tint: 'var(--rust-100)', ic: 'var(--rust-700)' },
      moss: { tint: 'var(--moss-100)', ic: 'var(--moss-700)' },
    };
    return (
      <div
        style={{
          margin: '12px 16px 0',
          padding: '12px 12px 10px',
          background: 'var(--paper-200)',
          borderRadius: 12,
          border: `1px solid ${BORDER}`,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <Eyebrow>quick log</Eyebrow>
          <span style={{ fontFamily: SANS, fontSize: 10.5, color: 'var(--ink-400)' }}>tap to write</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginTop: 8 }}>
          {spec.chips.slice(0, 3).map((c, i) => {
            const Icon = cIcons[c.icon];
            const tint = tints[c.tint ?? 'rust'];
            return (
              <TapToTalk
                key={i}
                primer={tallyLogPrimer(c.label)}
                decoration="block"
                style={{
                  background: 'var(--paper-100)',
                  border: `1px solid ${BORDER}`,
                  borderRadius: 10,
                  padding: '10px 8px',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: 6,
                }}
              >
                <div
                  style={{
                    width: 30,
                    height: 30,
                    borderRadius: 8,
                    background: tint.tint,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <Icon s={15} c={tint.ic} />
                </div>
                <span style={{ fontFamily: SANS, fontSize: 11.5, color: 'var(--ink-900)', fontWeight: 500 }}>
                  {c.label}
                </span>
              </TapToTalk>
            );
          })}
        </div>
      </div>
    );
  }
  // chips
  return (
    <div style={{ margin: '12px 22px 0' }}>
      <Eyebrow>quick log</Eyebrow>
      <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {spec.chips.map((c, i) => {
          const Icon = cIcons[c.icon];
          return (
            <TapToTalk
              key={i}
              primer={tallyLogPrimer(c.label)}
              decoration="label"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                padding: '7px 12px',
                borderRadius: 999,
                background: 'var(--paper-100)',
                border: `1px solid ${BORDER_STRONG}`,
                fontFamily: SANS,
                fontSize: 12.5,
                color: 'var(--ink-900)',
                fontWeight: 500,
              }}
            >
              <Icon s={13} c="var(--ink-700)" />
              {c.label}
            </TapToTalk>
          );
        })}
      </div>
      <BlockActions actions={spec.actions} />
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════
// 13 · PICK
// ═════════════════════════════════════════════════════════════════════════
export interface CatPickSpec {
  type: 'c-pick';
  variant: 'editorial' | 'card';
  kind: string; // 'read' · 'watch' · 'listen' · 'place' · 'thing' · 'person'
  title: string;
  body?: string;
  source?: string;
  year?: string;
  /** Optional footer actions, rendered as ActionChips by BlockActions. */
  actions?: ActionVerb[];
}
export function CatPick({ spec }: { spec: CatPickSpec }) {
  if (spec.variant === 'card') {
    return (
      <TapToTalk
        primer={`tell me more about: ${spec.title}`}
        decoration="block"
        style={{
          margin: '12px 16px 0',
          display: 'flex',
          background: 'var(--paper-100)',
          border: `1px solid ${BORDER}`,
          borderRadius: 12,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: 80,
            background: 'var(--rust-100)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <cIcons.book s={28} c="var(--rust-700)" />
        </div>
        <div style={{ flex: 1, padding: '12px 14px' }}>
          <Eyebrow tone="var(--rust-700)">pick · {spec.kind}</Eyebrow>
          <div
            style={{
              fontFamily: SERIF,
              fontSize: 16,
              fontWeight: 500,
              color: 'var(--ink-900)',
              marginTop: 2,
              lineHeight: 1.2,
              fontStyle: 'italic',
            }}
          >
            {spec.title}
          </div>
          {(spec.source || spec.year) && (
            <div style={{ fontFamily: SANS, fontSize: 11.5, color: 'var(--ink-500)', marginTop: 3, lineHeight: 1.45 }}>
              {[spec.source, spec.year].filter(Boolean).join(' · ')}
            </div>
          )}
        </div>
      </TapToTalk>
    );
  }
  return (
    <div style={{ margin: '12px 22px 0' }}>
      <Eyebrow tone="var(--rust-700)">a pick · {spec.kind}</Eyebrow>
      <div
        style={{
          fontFamily: SERIF,
          fontSize: 22,
          fontWeight: 500,
          color: 'var(--ink-900)',
          marginTop: 4,
          letterSpacing: '-0.015em',
          lineHeight: 1.15,
          fontStyle: 'italic',
        }}
      >
        {spec.title}
      </div>
      {spec.body && (
        <div style={{ fontFamily: SANS, fontSize: 12.5, color: 'var(--ink-500)', marginTop: 4, lineHeight: 1.5 }}>
          {spec.body}
        </div>
      )}
      <div
        style={{
          marginTop: 12,
          paddingTop: 10,
          borderTop: `1px solid ${BORDER}`,
          display: 'flex',
          gap: 18,
        }}
      >
        <TapToTalk
          primer={`save this for me: ${spec.title}`}
          decoration="label"
          style={{ fontFamily: SANS, fontSize: 12, color: 'var(--rust-700)', fontWeight: 500 }}
        >
          save
        </TapToTalk>
        <TapToTalk
          primer={`tell me more about: ${spec.title}`}
          decoration="label"
          style={{ fontFamily: SANS, fontSize: 12, color: 'var(--ink-500)' }}
        >
          say more
        </TapToTalk>
        <TapToTalk
          primer={`drop this from my picks: ${spec.title}`}
          decoration="label"
          style={{ fontFamily: SANS, fontSize: 12, color: 'var(--ink-400)', marginLeft: 'auto' }}
        >
          drop
        </TapToTalk>
      </div>
      <BlockActions actions={spec.actions} />
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════
// 14 · OFFER
// ═════════════════════════════════════════════════════════════════════════
export interface CatOfferSpec {
  type: 'c-offer';
  variant: 'hero' | 'twoline';
  eyebrow?: string;
  title: string;
  rationale?: string;
  ctaAccept: string;
  ctaDismiss?: string;
  /** Optional footer actions, rendered as ActionChips by BlockActions. */
  actions?: ActionVerb[];
}
export function CatOffer({ spec }: { spec: CatOfferSpec }) {
  if (spec.variant === 'hero') {
    return (
      <div
        style={{
          margin: '12px 16px 0',
          padding: '16px 16px 14px',
          background: 'var(--rust-700)',
          border: `1px solid var(--rust-900)`,
          borderRadius: 14,
          color: 'var(--paper-100)',
        }}
      >
        <Eyebrow tone="rgba(251,247,245,0.7)">{spec.eyebrow ?? 'offer'}</Eyebrow>
        <div
          style={{
            fontFamily: SERIF,
            fontSize: 22,
            fontWeight: 500,
            color: 'var(--paper-100)',
            marginTop: 4,
            letterSpacing: '-0.015em',
            lineHeight: 1.15,
          }}
        >
          {spec.title}
        </div>
        {spec.rationale && (
          <div
            style={{
              fontFamily: SANS,
              fontSize: 13,
              color: 'rgba(251,247,245,0.78)',
              marginTop: 6,
              lineHeight: 1.5,
            }}
          >
            {spec.rationale}
          </div>
        )}
        <div style={{ display: 'flex', gap: 10, marginTop: 14, alignItems: 'center' }}>
          <span
            style={{
              fontFamily: SANS,
              fontSize: 12.5,
              fontWeight: 500,
              color: 'var(--rust-900)',
              background: 'var(--paper-100)',
              padding: '7px 14px',
              borderRadius: 999,
            }}
          >
            {spec.ctaAccept}
          </span>
          <span style={{ fontFamily: SANS, fontSize: 12.5, color: 'rgba(251,247,245,0.7)' }}>
            {spec.ctaDismiss ?? 'not now'}
          </span>
        </div>
      </div>
    );
  }
  return (
    <div style={{ margin: '12px 22px 0' }}>
      <Eyebrow tone="var(--rust-700)">{spec.eyebrow ?? 'offer'}</Eyebrow>
      <div
        style={{
          fontFamily: SERIF,
          fontSize: 18,
          fontWeight: 500,
          color: 'var(--ink-900)',
          marginTop: 3,
          letterSpacing: '-0.01em',
          lineHeight: 1.25,
        }}
      >
        {spec.title}
      </div>
      {spec.rationale && (
        <div style={{ fontFamily: SANS, fontSize: 12.5, color: 'var(--ink-500)', marginTop: 3, lineHeight: 1.5 }}>
          {spec.rationale}
        </div>
      )}
      <div style={{ display: 'flex', gap: 10, marginTop: 10 }}>
        <span
          style={{
            fontFamily: SANS,
            fontSize: 12,
            color: 'var(--paper-100)',
            background: 'var(--rust-700)',
            padding: '6px 12px',
            borderRadius: 999,
            fontWeight: 500,
          }}
        >
          {spec.ctaAccept}
        </span>
        <span style={{ fontFamily: SANS, fontSize: 12, color: 'var(--ink-500)', padding: '6px 4px' }}>
          {spec.ctaDismiss ?? 'not now'}
        </span>
      </div>
      <BlockActions actions={spec.actions} />
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════
// 15 · DRAFT
// ═════════════════════════════════════════════════════════════════════════
export interface CatDraftSpec {
  type: 'c-draft';
  variant: 'letter' | 'inline';
  recipient: string;
  subject: string;
  preview: string;
  /** Optional footer actions, rendered as ActionChips by BlockActions. */
  actions?: ActionVerb[];
}
export function CatDraft({ spec }: { spec: CatDraftSpec }) {
  if (spec.variant === 'letter') {
    return (
      <div
        style={{
          margin: '12px 16px 0',
          padding: '14px 14px',
          background: 'var(--paper-50)',
          border: `1px solid ${BORDER_ACCENT}`,
          borderRadius: 12,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <Eyebrow tone="var(--rust-700)">draft · ready to send</Eyebrow>
          <cIcons.envelope s={13} c="var(--rust-700)" />
        </div>
        <div style={{ fontFamily: SANS, fontSize: 11.5, color: 'var(--ink-500)', marginTop: 8 }}>
          to <span style={{ color: 'var(--ink-900)', fontWeight: 500 }}>{spec.recipient}</span> · {spec.subject}
        </div>
        <div
          style={{
            marginTop: 8,
            paddingTop: 8,
            borderTop: `1px solid ${BORDER}`,
            fontFamily: SERIF,
            fontSize: 14,
            color: 'var(--ink-900)',
            lineHeight: 1.45,
            fontStyle: 'italic',
          }}
        >
          “{spec.preview}”
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <TapToTalk
            primer={`send the draft to ${spec.recipient}: ${spec.subject}`}
            decoration="label"
            style={{
              fontFamily: SANS,
              fontSize: 12,
              color: 'var(--paper-100)',
              background: 'var(--rust-700)',
              padding: '6px 13px',
              borderRadius: 999,
              fontWeight: 500,
            }}
          >
            send
          </TapToTalk>
          <TapToTalk
            primer={`open the draft to ${spec.recipient}`}
            decoration="label"
            style={{ fontFamily: SANS, fontSize: 12, color: 'var(--ink-500)', padding: '6px 4px' }}
          >
            open
          </TapToTalk>
          <TapToTalk
            primer={`drop the draft to ${spec.recipient}`}
            decoration="label"
            style={{ fontFamily: SANS, fontSize: 12, color: 'var(--ink-400)', padding: '6px 4px', marginLeft: 'auto' }}
          >
            drop
          </TapToTalk>
        </div>
      </div>
    );
  }
  return (
    <div style={{ margin: '12px 22px 0' }}>
      <Eyebrow tone="var(--rust-700)">draft for {spec.recipient} · {spec.subject}</Eyebrow>
      <div
        style={{
          fontFamily: SERIF,
          fontSize: 16,
          fontStyle: 'italic',
          color: 'var(--ink-900)',
          marginTop: 6,
          lineHeight: 1.5,
        }}
      >
        “{spec.preview}”
      </div>
      <div
        style={{
          marginTop: 10,
          paddingTop: 10,
          borderTop: `1px solid ${BORDER}`,
          display: 'flex',
          gap: 18,
        }}
      >
        <TapToTalk
          primer={`send the draft to ${spec.recipient}: ${spec.subject}`}
          decoration="label"
          style={{ fontFamily: SANS, fontSize: 12, color: 'var(--rust-700)', fontWeight: 500 }}
        >
          send
        </TapToTalk>
        <TapToTalk
          primer={`open the draft to ${spec.recipient} to edit`}
          decoration="label"
          style={{ fontFamily: SANS, fontSize: 12, color: 'var(--ink-500)' }}
        >
          open to edit
        </TapToTalk>
        <TapToTalk
          primer={`drop the draft to ${spec.recipient}`}
          decoration="label"
          style={{ fontFamily: SANS, fontSize: 12, color: 'var(--ink-400)', marginLeft: 'auto' }}
        >
          drop
        </TapToTalk>
      </div>
      <BlockActions actions={spec.actions} />
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════
// 16 · DECISION
// ═════════════════════════════════════════════════════════════════════════
export interface DecisionOption { label: string; hint?: string; }
export interface CatDecisionSpec {
  type: 'c-decision';
  variant: 'tiles' | 'stack';
  question: string;
  highlight?: string; // italic-rust word inside the question (stack only)
  options: DecisionOption[];
  /** Optional footer actions, rendered as ActionChips by BlockActions. */
  actions?: ActionVerb[];
}
export function CatDecision({ spec }: { spec: CatDecisionSpec }) {
  if (spec.variant === 'stack') {
    return (
      <div style={{ margin: '12px 22px 0' }}>
        <Eyebrow>quick decide</Eyebrow>
        <div
          style={{
            fontFamily: SERIF,
            fontSize: 20,
            fontWeight: 500,
            color: 'var(--ink-900)',
            marginTop: 3,
            letterSpacing: '-0.015em',
          }}
        >
          {spec.question}
          {spec.highlight && (
            <em style={{ color: 'var(--rust-700)' }}> {spec.highlight}</em>
          )}
        </div>
        <div style={{ marginTop: 10 }}>
          {spec.options.slice(0, 3).map((o, i) => (
            <TapToTalk
              key={i}
              primer={`${spec.question.replace(/\?$/, '')} — ${o.label}`}
              decoration="row"
              style={{
                display: 'grid',
                gridTemplateColumns: '14px 1fr auto',
                gap: 12,
                padding: '12px 0',
                borderBottom: `1px solid ${BORDER}`,
                alignItems: 'baseline',
              }}
            >
              <span
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: 999,
                  border: `1.3px solid ${BORDER_STRONG}`,
                  marginTop: 5,
                }}
              />
              <div>
                <div style={{ fontFamily: SANS, fontSize: 13.5, color: 'var(--ink-900)', fontWeight: 500 }}>
                  {o.label}
                </div>
                {o.hint && (
                  <div style={{ fontFamily: SANS, fontSize: 11.5, color: 'var(--ink-500)', marginTop: 2 }}>{o.hint}</div>
                )}
              </div>
              <cIcons.chev s={11} c="var(--ink-400)" />
            </TapToTalk>
          ))}
        </div>
      </div>
    );
  }
  return (
    <div style={{ margin: '12px 16px 0' }}>
      <Eyebrow>quick decide</Eyebrow>
      <div
        style={{
          fontFamily: SERIF,
          fontSize: 18,
          fontWeight: 500,
          color: 'var(--ink-900)',
          marginTop: 3,
          letterSpacing: '-0.01em',
        }}
      >
        {spec.question}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginTop: 10 }}>
        {spec.options.slice(0, 3).map((o, i) => (
          <TapToTalk
            key={i}
            primer={`${spec.question.replace(/\?$/, '')} — ${o.label}`}
            decoration="block"
            style={{
              background: 'var(--paper-100)',
              border: `1px solid ${BORDER}`,
              borderRadius: 10,
              padding: '10px 8px',
              textAlign: 'center',
            }}
          >
            <div style={{ fontFamily: SERIF, fontSize: 13.5, fontWeight: 500, color: 'var(--ink-900)' }}>
              {o.label}
            </div>
            {o.hint && (
              <div
                style={{
                  fontFamily: SANS,
                  fontSize: 10.5,
                  color: 'var(--ink-400)',
                  marginTop: 3,
                  fontStyle: 'italic',
                }}
              >
                {o.hint}
              </div>
            )}
          </TapToTalk>
        ))}
      </div>
      <BlockActions actions={spec.actions} />
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════
// 17 · CONFRONTATION
// ═════════════════════════════════════════════════════════════════════════
export interface CatConfrontSpec {
  type: 'c-confront';
  variant: 'quiet' | 'card';
  eyebrow?: string;
  title: string;
  body?: string;
  /** Optional footer actions, rendered as ActionChips by BlockActions. */
  actions?: ActionVerb[];
}
export function CatConfront({ spec }: { spec: CatConfrontSpec }) {
  if (spec.variant === 'card') {
    return (
      <div
        style={{
          margin: '12px 16px 0',
          padding: '14px 14px',
          background: 'var(--oxblood-100)',
          border: `1px solid ${BORDER}`,
          borderLeft: '3px solid var(--oxblood-700)',
          borderRadius: 8,
        }}
      >
        <Eyebrow tone="var(--oxblood-700)">{spec.eyebrow ?? 'confrontation'}</Eyebrow>
        <div
          style={{
            fontFamily: SERIF,
            fontSize: 17,
            fontWeight: 500,
            color: 'var(--ink-900)',
            marginTop: 3,
            lineHeight: 1.25,
          }}
        >
          {spec.title}
        </div>
        {spec.body && (
          <div style={{ fontFamily: SANS, fontSize: 12.5, color: 'var(--ink-700)', marginTop: 5, lineHeight: 1.5 }}>
            {spec.body}
          </div>
        )}
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          <TapToTalk
            primer={`i'm on it: ${spec.title}`}
            decoration="label"
            style={{
              fontFamily: SANS,
              fontSize: 12,
              color: 'var(--paper-100)',
              background: 'var(--ink-900)',
              padding: '6px 12px',
              borderRadius: 999,
              fontWeight: 500,
            }}
          >
            on it
          </TapToTalk>
          <TapToTalk
            primer={`not now: ${spec.title}`}
            decoration="label"
            style={{ fontFamily: SANS, fontSize: 12, color: 'var(--ink-500)', padding: '6px 4px' }}
          >
            later
          </TapToTalk>
          <TapToTalk
            primer={`talk to me about: ${spec.title}`}
            decoration="label"
            style={{ fontFamily: SANS, fontSize: 12, color: 'var(--ink-500)', padding: '6px 4px' }}
          >
            talk to me
          </TapToTalk>
        </div>
      </div>
    );
  }
  return (
    <div style={{ margin: '12px 22px 0' }}>
      <Eyebrow tone="var(--oxblood-700)">{spec.eyebrow ?? "i won't soften this"}</Eyebrow>
      <div
        style={{
          fontFamily: SERIF,
          fontSize: 22,
          fontWeight: 500,
          color: 'var(--ink-900)',
          marginTop: 6,
          letterSpacing: '-0.015em',
          lineHeight: 1.2,
        }}
      >
        {spec.title}
      </div>
      {spec.body && (
        <div style={{ fontFamily: SANS, fontSize: 13, color: 'var(--ink-700)', marginTop: 8, lineHeight: 1.55 }}>
          {spec.body}
        </div>
      )}
      <div
        style={{
          marginTop: 14,
          paddingTop: 10,
          borderTop: `1px solid ${BORDER}`,
          display: 'flex',
          gap: 18,
        }}
      >
        <TapToTalk
          primer={`i'm on it: ${spec.title}`}
          decoration="label"
          style={{ fontFamily: SANS, fontSize: 12, color: 'var(--ink-900)', fontWeight: 500 }}
        >
          on it
        </TapToTalk>
        <TapToTalk
          primer={`not now: ${spec.title}`}
          decoration="label"
          style={{ fontFamily: SANS, fontSize: 12, color: 'var(--ink-500)' }}
        >
          later
        </TapToTalk>
        <TapToTalk
          primer={`talk to me about: ${spec.title}`}
          decoration="label"
          style={{ fontFamily: SANS, fontSize: 12, color: 'var(--rust-700)', fontWeight: 500, marginLeft: 'auto' }}
        >
          talk to me
        </TapToTalk>
      </div>
      <BlockActions actions={spec.actions} />
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════
// 18 · REFLECTION
// ═════════════════════════════════════════════════════════════════════════
export interface CatReflectionSpec {
  type: 'c-reflection';
  variant: 'prompt' | 'card';
  eyebrow?: string;
  prompt: string;
  /** Optional footer actions, rendered as ActionChips by BlockActions. */
  actions?: ActionVerb[];
}
export function CatReflection({ spec }: { spec: CatReflectionSpec }) {
  if (spec.variant === 'card') {
    return (
      <div
        style={{
          margin: '12px 16px 0',
          padding: '16px 16px',
          background: 'var(--paper-200)',
          border: `1px solid ${BORDER}`,
          borderRadius: 12,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
          <span
            style={{
              fontFamily: SERIF,
              fontStyle: 'italic',
              fontSize: 36,
              color: 'var(--rust-700)',
              lineHeight: 0.6,
              fontWeight: 500,
            }}
          >
            “
          </span>
          <div
            style={{
              fontFamily: SERIF,
              fontStyle: 'italic',
              fontWeight: 400,
              fontSize: 18,
              color: 'var(--ink-900)',
              lineHeight: 1.3,
              marginTop: 6,
            }}
          >
            {spec.prompt}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, marginTop: 14 }}>
          <TapToTalk
            primer={spec.prompt}
            decoration="label"
            style={{
              fontFamily: SANS,
              fontSize: 12,
              color: 'var(--paper-100)',
              background: 'var(--rust-700)',
              padding: '6px 13px',
              borderRadius: 999,
              fontWeight: 500,
            }}
          >
            answer
          </TapToTalk>
          <TapToTalk
            primer={`skip the reflection: ${spec.prompt}`}
            decoration="label"
            style={{ fontFamily: SANS, fontSize: 12, color: 'var(--ink-500)', padding: '6px 4px' }}
          >
            skip
          </TapToTalk>
        </div>
      </div>
    );
  }
  return (
    <div style={{ margin: '12px 22px 0' }}>
      <Eyebrow>{spec.eyebrow ?? 'a reflection · for tonight'}</Eyebrow>
      <div
        style={{
          fontFamily: SERIF,
          fontStyle: 'italic',
          fontWeight: 400,
          fontSize: 24,
          color: 'var(--ink-900)',
          marginTop: 8,
          letterSpacing: '-0.01em',
          lineHeight: 1.25,
          textWrap: 'pretty' as 'pretty',
        }}
      >
        {spec.prompt}
      </div>
      <div style={{ display: 'flex', gap: 18, marginTop: 14 }}>
        <TapToTalk
          primer={spec.prompt}
          decoration="label"
          style={{ fontFamily: SANS, fontSize: 12.5, color: 'var(--rust-700)', fontWeight: 500 }}
        >
          answer
        </TapToTalk>
        <TapToTalk
          primer={`skip the reflection: ${spec.prompt}`}
          decoration="label"
          style={{ fontFamily: SANS, fontSize: 12.5, color: 'var(--ink-500)' }}
        >
          skip for today
        </TapToTalk>
      </div>
      <BlockActions actions={spec.actions} />
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════
// 19 · OPEN LOOP
// ═════════════════════════════════════════════════════════════════════════
export interface OpenLoopItem { commitment: string; ago: string; due?: string; overdue?: boolean; attention_id?: string; }
export interface CatOpenLoopSpec {
  type: 'c-openloop';
  variant: 'quote' | 'dashed';
  title?: string;
  right?: string;
  items: OpenLoopItem[];
  /** Optional footer actions, rendered as ActionChips by BlockActions. */
  actions?: ActionVerb[];
}
export function CatOpenLoop({ spec }: { spec: CatOpenLoopSpec }) {
  if (spec.variant === 'dashed') {
    const it = spec.items[0];
    if (!it) return null;
    // Outer container is static so the three nested action TapToTalks
    // below stay valid HTML. The action row itself is the tap surface.
    return (
      <div
        style={{
          margin: '12px 16px 0',
          padding: '12px 14px',
          background: 'var(--paper-100)',
          border: `1px dashed ${BORDER_ACCENT}`,
          borderRadius: 12,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <Eyebrow tone="var(--rust-700)">open loop · {it.ago}</Eyebrow>
          {it.overdue && (
            <span style={{ fontFamily: SANS, fontSize: 11, color: 'var(--oxblood-700)', fontWeight: 500 }}>
              overdue
            </span>
          )}
        </div>
        <TapToTalk
          attentionId={it.attention_id}
          primer={`about my open loop: ${it.commitment}`}
          decoration="block"
          style={{
            fontFamily: SERIF,
            fontSize: 16,
            fontStyle: 'italic',
            color: 'var(--ink-900)',
            marginTop: 5,
            lineHeight: 1.3,
          }}
        >
          “{it.commitment}”
        </TapToTalk>
        <div style={{ display: 'flex', gap: 14, marginTop: 10 }}>
          <TapToTalk
            primer={`done: ${it.commitment}`}
            decoration="label"
            style={{ fontFamily: SANS, fontSize: 12, color: 'var(--moss-700)', fontWeight: 500 }}
          >
            i did this
          </TapToTalk>
          <TapToTalk
            primer={`snooze the loop: ${it.commitment}`}
            decoration="label"
            style={{ fontFamily: SANS, fontSize: 12, color: 'var(--ink-500)' }}
          >
            snooze
          </TapToTalk>
          <TapToTalk
            primer={`tell me more about: ${it.commitment}`}
            decoration="label"
            style={{ fontFamily: SANS, fontSize: 12, color: 'var(--ink-500)' }}
          >
            say more
          </TapToTalk>
        </div>
      </div>
    );
  }
  return (
    <div style={{ margin: '12px 22px 0' }}>
      <SectionHead
        title={spec.title ?? "things you said you'd do"}
        right={spec.right ?? `${spec.items.length} open`}
      />
      <div style={{ marginTop: 8 }}>
        {spec.items.map((l, i) => (
          <TapToTalk
            key={i}
            attentionId={l.attention_id}
            primer={`about my open loop: ${l.commitment}`}
            decoration="row"
            style={{ padding: '12px 0', borderBottom: `1px solid ${BORDER}` }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
              <Eyebrow tone={l.overdue ? 'var(--oxblood-700)' : 'var(--ink-400)'}>
                {l.ago} · {l.due ?? (l.overdue ? 'overdue' : 'open')}
              </Eyebrow>
              <cIcons.chev s={11} c="var(--ink-400)" />
            </div>
            <div
              style={{
                fontFamily: SERIF,
                fontSize: 15,
                color: 'var(--ink-900)',
                marginTop: 3,
                fontStyle: 'italic',
                lineHeight: 1.3,
              }}
            >
              “{l.commitment}”
            </div>
          </TapToTalk>
        ))}
      </div>
      <BlockActions actions={spec.actions} />
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════
// 20 · PERMISSION
// ═════════════════════════════════════════════════════════════════════════
export interface CatPermissionSpec {
  type: 'c-permission';
  variant: 'soft' | 'editorial';
  provider: string;
  body: string;
  ctaConnect?: string;
  ctaDismiss?: string;
  /** Optional footer actions, rendered as ActionChips by BlockActions. */
  actions?: ActionVerb[];
}
export function CatPermission({ spec }: { spec: CatPermissionSpec }) {
  if (spec.variant === 'editorial') {
    const connectVerb: ActionVerb = { v: 'connect_integration', provider: spec.provider };
    return (
      <div style={{ margin: '12px 22px 0' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <cIcons.plug s={16} c="var(--rust-700)" />
          <Eyebrow tone="var(--rust-700)">connect {spec.provider}</Eyebrow>
        </div>
        <div
          style={{
            fontFamily: SERIF,
            fontSize: 18,
            fontWeight: 500,
            color: 'var(--ink-900)',
            marginTop: 6,
            letterSpacing: '-0.01em',
            lineHeight: 1.25,
          }}
        >
          {spec.body}
        </div>
        <div
          style={{
            marginTop: 12,
            paddingTop: 10,
            borderTop: `1px solid ${BORDER}`,
            display: 'flex',
            gap: 12,
            alignItems: 'center',
          }}
        >
          <ActionChip verb={connectVerb} tone="rust" size="sm">
            {spec.ctaConnect ?? `connect ${spec.provider}`}
          </ActionChip>
          <TapToTalk
            primer={`not now: connecting ${spec.provider}`}
            decoration="label"
            style={{ fontFamily: SANS, fontSize: 12.5, color: 'var(--ink-500)' }}
          >
            {spec.ctaDismiss ?? 'not yet'}
          </TapToTalk>
        </div>
      </div>
    );
  }
  return (
    <div
      style={{
        margin: '12px 16px 0',
        padding: '12px 14px',
        background: 'var(--paper-200)',
        border: `1px solid ${BORDER}`,
        borderRadius: 12,
        display: 'grid',
        gridTemplateColumns: '1fr auto',
        gap: 12,
        alignItems: 'center',
      }}
    >
      <div>
        <Eyebrow>connect · {spec.provider}</Eyebrow>
        <div
          style={{
            fontFamily: SANS,
            fontSize: 13,
            color: 'var(--ink-900)',
            marginTop: 4,
            lineHeight: 1.45,
            fontWeight: 500,
          }}
        >
          {spec.body}
        </div>
      </div>
      <ActionChip
        verb={{ v: 'connect_integration', provider: spec.provider }}
        tone="rust"
        size="sm"
      >
        {spec.ctaConnect ?? `connect ${spec.provider}`}
      </ActionChip>
      <BlockActions actions={spec.actions} />
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════
// 21 · READ
// ═════════════════════════════════════════════════════════════════════════
export interface ReadItem { headline: string; source: string; tag?: string; meta?: string; }
export interface CatReadSpec {
  type: 'c-read';
  variant: 'index' | 'card';
  items: ReadItem[];
  /** Optional footer actions, rendered as ActionChips by BlockActions. */
  actions?: ActionVerb[];
}
export function CatRead({ spec }: { spec: CatReadSpec }) {
  if (spec.variant === 'card') {
    const it = spec.items[0];
    if (!it) return null;
    return (
      <TapToTalk
        primer={`tell me about: ${it.headline}`}
        decoration="block"
        style={{
          margin: '12px 16px 0',
          padding: '14px 14px',
          background: 'var(--paper-100)',
          border: `1px solid ${BORDER}`,
          borderRadius: 12,
          display: 'grid',
          gridTemplateColumns: '1fr 14px',
          gap: 10,
          alignItems: 'center',
        }}
      >
        <div>
          <Eyebrow>
            {it.source}
            {it.tag && ` · ${it.tag}`}
          </Eyebrow>
          <div
            style={{
              fontFamily: SERIF,
              fontSize: 16,
              fontWeight: 500,
              color: 'var(--ink-900)',
              marginTop: 4,
              lineHeight: 1.25,
              letterSpacing: '-0.005em',
            }}
          >
            {it.headline}
          </div>
          {it.meta && (
            <div style={{ fontFamily: SANS, fontSize: 11.5, color: 'var(--ink-500)', marginTop: 5 }}>
              {it.meta}
            </div>
          )}
        </div>
        <cIcons.link s={13} c="var(--ink-400)" />
      </TapToTalk>
    );
  }
  return (
    <div style={{ margin: '12px 22px 0' }}>
      <SectionHead title="three to read" right="picked for you" italic />
      <div style={{ marginTop: 6 }}>
        {spec.items.map((r, i) => (
          <TapToTalk
            key={i}
            primer={`tell me about: ${r.headline}`}
            decoration="row"
            style={{
              padding: '12px 0',
              borderBottom: `1px solid ${BORDER}`,
              display: 'grid',
              gridTemplateColumns: '1fr 14px',
              gap: 10,
              alignItems: 'flex-start',
            }}
          >
            <div>
              <Eyebrow>
                {r.source}
                {r.tag && ` · ${r.tag}`}
              </Eyebrow>
              <div
                style={{
                  fontFamily: SERIF,
                  fontSize: 15.5,
                  fontWeight: 500,
                  color: 'var(--ink-900)',
                  marginTop: 3,
                  lineHeight: 1.3,
                  letterSpacing: '-0.005em',
                }}
              >
                {r.headline}
              </div>
            </div>
            <cIcons.link s={12} c="var(--ink-400)" />
          </TapToTalk>
        ))}
      </div>
      <BlockActions actions={spec.actions} />
    </div>
  );
}
