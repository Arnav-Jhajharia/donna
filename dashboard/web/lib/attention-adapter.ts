/**
 * Attention → Dashboard Block adapter.
 *
 * Donna's attention subsystem produces exactly six CardTypes
 * (donna/attention/vocabulary.py:70). This file is the bridge between
 * those semantic shapes and the dashboard's renderable Block vocabulary
 * (lib/plan.ts). Every attention Donna writes is one of these six; every
 * one of these six has a deterministic block shape on the dashboard.
 *
 * This is the Lego promise made real: we do not design one UI per domain.
 * We design one renderer per card type, and every future affordance slots
 * in. Hydration tracker, fundraising brief, maya's flight — all pass
 * through here, all come out as Block[].
 *
 *   Attention.card = EVENT_STREAM  →  OpenLoopsBlock  (already exists)
 *   Attention.card = TALLY         →  TrackerGridBlock
 *   Attention.card = BRIEF         →  WitnessBlock  (headline+evidence)
 *   Attention.card = PREP_DOC      →  ReflectionBlock-like (talking points)
 *   Attention.card = OPEN_LOOP     →  OpenLoopsBlock (single-item form)
 *   Attention.card = PING          →  WhisperBlock
 *
 * The adapter is pure: (AttentionOutput, rendering hints) → Block.
 * Policy (which attentions to render, in what order, which claims rust)
 * lives in lib/generator.ts — NOT here.
 */

import type {
  Block,
  IconName,
  OpenLoop,
  OpenLoopsBlock,
  ReflectionBlock,
  SignalTone,
  TrackerItem,
  TrackerGridBlock,
  WhisperBlock,
  WitnessBlock,
} from './plan';

// ── Attention output payloads (mirror of donna/attention/vocabulary.py) ────
// These match output_schema_for_card() exactly. Keep them in sync.

export interface EventStreamPayload {
  events: Array<{
    id: string;
    timestamp?: string;
    title: string;
    summary?: string;
    relevance?: number;
  }>;
}

export interface TallyPayload {
  count: number;
  unit?: string;
  window?: string;
  entries?: Array<Record<string, unknown>>;
}

export interface BriefPayload {
  headline: string;
  bullets: string[];
  sources?: string[];
}

export interface PrepDocPayload {
  for_event: string;
  context?: string;
  talking_points: string[];
  open_questions?: string[];
}

export interface OpenLoopPayload {
  loop_summary: string;
  last_activity_at?: string;
  waiting_on?: string;
  is_resolved: boolean;
}

export interface PingPayload {
  message: string;
  fire_at?: string;
}

// ── Rendering hints (what the policy layer passes alongside the payload) ──

export interface RenderHints {
  /** Human title shown above the block (usually the attention's subject.name). */
  title: string;
  /** Rendering surface level from the attention (silent never reaches here). */
  surfaceLevel: 'digest' | 'notify' | 'urgent';
  /** Domain tag for icon/tone defaults. */
  domain?:
    | 'work' | 'fundraising' | 'social' | 'logistics' | 'finance' | 'learning'
    | 'health' | 'travel' | 'competitive_intel' | 'meeting' | 'research'
    | 'subscription' | 'shipment' | 'flight' | 'openloop' | 'reminder' | 'habit';
  /** If the policy picked THIS block as the rust moment for the screen. */
  claimsRust?: boolean;
}

// ── Domain → icon/tone defaults ────────────────────────────────────────────

const DOMAIN_ICON: Record<NonNullable<RenderHints['domain']>, IconName> = {
  work:               'eye',
  fundraising:        'rupee',
  social:             'heart',
  logistics:          'hourglass',
  finance:            'rupee',
  learning:           'leaf',
  health:             'drop',
  travel:             'sun',
  competitive_intel:  'eye',
  meeting:            'phone',
  research:           'leaf',
  subscription:       'rupee',
  shipment:           'hourglass',
  flight:             'sun',
  openloop:           'hourglass',
  reminder:           'moon',
  habit:              'leaf',
};

const DOMAIN_TONE: Record<NonNullable<RenderHints['domain']>, SignalTone> = {
  work:               'ink',
  fundraising:        'rust',
  social:             'rust',
  logistics:          'amber',
  finance:            'amber',
  learning:           'moss',
  health:             'moss',
  travel:             'amber',
  competitive_intel:  'ink',
  meeting:            'rust',
  research:           'ink',
  subscription:       'amber',
  shipment:           'amber',
  flight:             'amber',
  openloop:           'rust',
  reminder:           'ink',
  habit:              'moss',
};

function iconFor(hints: RenderHints): IconName {
  return hints.domain ? DOMAIN_ICON[hints.domain] : 'eye';
}

function toneFor(hints: RenderHints): SignalTone {
  return hints.domain ? DOMAIN_TONE[hints.domain] : 'ink';
}

// ── Per-card adapters ──────────────────────────────────────────────────────

export function eventStreamToBlock(
  payload: EventStreamPayload,
  hints: RenderHints,
): OpenLoopsBlock {
  const items: OpenLoop[] = payload.events.slice(0, 3).map((e) => ({
    id: e.id,
    title: e.title,
    age: formatAge(e.timestamp),
    commitment: e.summary ?? '',
  }));
  return {
    type: 'open-loops',
    title: hints.title,
    items,
  };
}

export function tallyToBlock(
  payload: TallyPayload,
  hints: RenderHints,
): TrackerGridBlock {
  const tone = toneFor(hints);
  const item: TrackerItem = {
    id: `tally:${hints.title}`,
    title: hints.title,
    value: formatCount(payload.count),
    unit: [payload.unit, payload.window].filter(Boolean).join(' · ') || 'today',
    sub: '',
    progress: 0,  // adapter does not infer progress — policy may override
    icon: iconFor(hints),
    tone,
    tint: tintFor(tone),
  };
  return {
    type: 'tracker-grid',
    title: hints.title,
    items: [item],
  };
}

export function briefToBlock(
  payload: BriefPayload,
  hints: RenderHints,
): WitnessBlock {
  const observation = [
    payload.headline,
    ...payload.bullets.slice(0, 2),
  ].join(' · ');
  return {
    type: 'witness',
    observation,
    source: payload.sources?.[0],
  };
}

export function prepDocToBlock(
  payload: PrepDocPayload,
  hints: RenderHints,
): ReflectionBlock {
  const prompts = [
    ...payload.talking_points.slice(0, 2),
    ...(payload.open_questions ?? []).slice(0, 1),
  ];
  return {
    type: 'reflection',
    title: `for ${payload.for_event.toLowerCase()}`,
    prompts,
  };
}

export function openLoopToBlock(
  payload: OpenLoopPayload,
  hints: RenderHints,
): OpenLoopsBlock {
  if (payload.is_resolved) {
    // Resolved loops become an empty group — policy should have filtered.
    // Return a single-item group with a "done" marker for safety.
    return {
      type: 'open-loops',
      title: hints.title,
      items: [{
        id: `loop:${hints.title}`,
        title: payload.loop_summary,
        age: 'resolved',
        commitment: '',
      }],
    };
  }
  return {
    type: 'open-loops',
    title: hints.title,
    items: [{
      id: `loop:${hints.title}`,
      title: payload.loop_summary,
      age: formatAge(payload.last_activity_at),
      commitment: payload.waiting_on ?? '',
    }],
  };
}

export function pingToBlock(
  payload: PingPayload,
  hints: RenderHints,
): WhisperBlock {
  return {
    type: 'whisper',
    kicker: hints.surfaceLevel === 'urgent' ? 'right now' : 'a small thing',
    body: payload.message,
    level: hints.surfaceLevel === 'urgent' ? 'loud' : 'subtle',
  };
}

// ── Union entry point ─────────────────────────────────────────────────────

export type AttentionCard =
  | { card: 'event_stream'; payload: EventStreamPayload }
  | { card: 'tally';        payload: TallyPayload }
  | { card: 'brief';        payload: BriefPayload }
  | { card: 'prep_doc';     payload: PrepDocPayload }
  | { card: 'open_loop';    payload: OpenLoopPayload }
  | { card: 'ping';         payload: PingPayload };

/** One attention → one Block. Never emits multiple. */
export function attentionToBlock(
  attention: AttentionCard,
  hints: RenderHints,
): Block {
  switch (attention.card) {
    case 'event_stream': return eventStreamToBlock(attention.payload, hints);
    case 'tally':        return tallyToBlock(attention.payload, hints);
    case 'brief':        return briefToBlock(attention.payload, hints);
    case 'prep_doc':     return prepDocToBlock(attention.payload, hints);
    case 'open_loop':    return openLoopToBlock(attention.payload, hints);
    case 'ping':         return pingToBlock(attention.payload, hints);
    default: {
      const _exhaustive: never = attention;
      return _exhaustive;
    }
  }
}

/** Batch. Preserves input order; policy is expected to order upstream. */
export function attentionsToBlocks(
  items: Array<{ attention: AttentionCard; hints: RenderHints }>,
): Block[] {
  return items.map(({ attention, hints }) => attentionToBlock(attention, hints));
}

// ── Internal helpers ───────────────────────────────────────────────────────

function formatCount(n: number): string {
  if (n >= 1000) {
    const k = n / 1000;
    return `${k.toFixed(k >= 10 ? 0 : 1)}k`;
  }
  return String(n);
}

function formatAge(timestamp?: string): string {
  if (!timestamp) return '';
  const then = new Date(timestamp).getTime();
  if (Number.isNaN(then)) return '';
  const diffMs = Date.now() - then;
  const mins = Math.floor(diffMs / 60_000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function tintFor(tone: SignalTone): TrackerItem['tint'] {
  switch (tone) {
    case 'moss':    return 'moss';
    case 'amber':   return 'amber';
    case 'rust':    return 'rust';
    case 'oxblood': return 'paper';  // no oxblood tint in scale — fall back
    case 'ink':     return 'paper';
  }
}
