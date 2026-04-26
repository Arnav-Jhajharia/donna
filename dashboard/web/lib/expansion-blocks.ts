/**
 * Expansion blocks · innovation from simplicity.
 *
 * Six new Lego blocks extracted from the 12 day-one surfaces in
 * `dashboard/project/screens/`. Each unlocks a just-in-time pattern
 * the primary seven (EventStream, Tally, Brief, PrepDoc, OpenLoop, Ping,
 * Offer) don't cover: provenance, temporal rhythm, promotion ritual,
 * lifecycle, bootstrap, extreme compression.
 *
 * Composed from the same closed palette + type scale. No new tokens.
 *
 * Contracts: see `donna-design-system/components.md` for layout rules.
 */

import type { Register } from './plan';

// ── 1 · SparklineStatus ─────────────────────────────────────────────────
// Temporal rhythm over 7–14 days. Each day is hit/half/miss.

export type SparkDayState = 'hit' | 'half' | 'miss';

export interface SparklineStatusBlock {
  type: 'sparkline-status';
  title: string;
  /** Left-to-right, oldest → today. Length must be 7–14. */
  days: Array<{ state: SparkDayState }>;
  /** Human window label, e.g. "mon → sun" */
  window: string;
  hitCount: number;
  total: number;
}

// ── 2 · ProvenanceFactRow ───────────────────────────────────────────────
// Auditable living profile. Each row shows where donna learned the fact.

export type ProvenanceKind =
  | 'told-me'       // user said it to donna
  | 'observed'      // donna inferred from behavior
  | 'inferred'      // donna guessed (with confidence)
  | 'from-calendar'
  | 'from-email'
  | 'from-chat'
  | 'auto';

export interface ProvenanceRow {
  key: string;       // caps-label, rust
  value: string;     // serif body (italic accent permitted on proper nouns)
  kind: ProvenanceKind;
  /** Human source detail. e.g. "tuesday 9:14" or "confidence 0.68" */
  detail: string;
}

export interface ProvenanceFactRowBlock {
  type: 'provenance-facts';
  title?: string;
  rows: ProvenanceRow[];  // max 8
}

// ── 3 · DryRunOffer · the promotion ritual ──────────────────────────────
// Used when promoting a shadow attention to live. The three-button pattern
// forces the user to see the attention's kind before saying yes.

export type AttentionKind =
  | 'event_stream' | 'tally' | 'brief' | 'prep_doc' | 'open_loop' | 'ping';

export interface DryRunOfferBlock {
  type: 'dryrun-offer';
  kind: AttentionKind;
  /** "dry-run · awaiting you" or similar. Caps rust. */
  status: string;
  /** Headline as [prefix] [accent] where accent is one rust italic word. */
  headline: { prefix: string; accent: string; suffix?: string };
  body: string;
  sources: string[];
  /** Three actions. "live" is primary (rust). "tweak" and "dismiss" are ghost. */
  actions: {
    live: string;
    tweak: string;
    dismiss: string;
  };
}

// ── 4 · LifecycleBand · unified state view ──────────────────────────────
// A band header. Attentions matching the state stack below the band.

export type LifecycleState =
  | 'living'    // Living profile facts
  | 'today'     // Today's thesis-tagged items
  | 'live'      // Running attentions
  | 'shadow'    // Silently watching
  | 'paused'    // User deferred
  | 'resolved'; // Harvested / archived

export interface LifecycleBandBlock {
  type: 'lifecycle-band';
  state: LifecycleState;
  label: string;  // "live · running"
  count: number;  // Hide band when 0.
}

// ── 5 · InvitationPrompt · bootstrap / cold-start ──────────────────────
// Day 1. Donna has no shadows to offer — invites the user to author intent.

export interface InvitationPromptBlock {
  type: 'invitation-prompt';
  eyebrow: string;        // "ASK ME TO"
  verb: string;           // "watch" — rendered with italic rust accent
  placeholder: string;    // "keep an eye on "
  hints: string[];        // max 4; pill chips that prefill the input
}

// ── 6 · MiniStatGrid · three tallies, one glance ───────────────────────

export interface MiniStatCell {
  key: string;       // caps label, rust
  value: string;     // tabular number
  total?: string;    // "/8" or "/2,200" — muted inline suffix
  sub: string;       // caption below
}

export interface MiniStatGridBlock {
  type: 'mini-stats';
  cells: [MiniStatCell, MiniStatCell, MiniStatCell];  // exactly 3
}

// ── Union & register mapping ───────────────────────────────────────────

export type ExpansionBlock =
  | SparklineStatusBlock
  | ProvenanceFactRowBlock
  | DryRunOfferBlock
  | LifecycleBandBlock
  | InvitationPromptBlock
  | MiniStatGridBlock;

/** Density weights, for integrating with the validatePlan budget. */
export const EXPANSION_DENSITY_WEIGHTS: Record<ExpansionBlock['type'], number> = {
  'sparkline-status':  1,
  'provenance-facts':  2,
  'dryrun-offer':      2,
  'lifecycle-band':    1,
  'invitation-prompt': 2,
  'mini-stats':        2,
};

/** Emotional register implied by each expansion block. */
export const EXPANSION_REGISTER: Record<ExpansionBlock['type'], Register> = {
  'sparkline-status':  'witness',      // "i saw you, for 7 days"
  'provenance-facts':  'witness',      // "here's what i know and how i know it"
  'dryrun-offer':      'invitation',   // "we could try this"
  'lifecycle-band':    'reminder',     // "this is still open"
  'invitation-prompt': 'invitation',   // "we could try this"
  'mini-stats':        'witness',      // "here's your state, briefly"
};

/** Which attention CardType naturally feeds each expansion block. */
export const EXPANSION_CARD_FIT: Record<ExpansionBlock['type'], AttentionKind[]> = {
  'sparkline-status':  ['tally', 'event_stream'],
  'provenance-facts':  [],  // consumes living profile, not an attention card
  'dryrun-offer':      ['event_stream', 'tally', 'brief', 'prep_doc', 'open_loop', 'ping'],
  'lifecycle-band':    [],  // structural, not content
  'invitation-prompt': [],  // bootstrap, not attention-driven
  'mini-stats':        ['tally'],
};
