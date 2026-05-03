/**
 * DashboardPlan — the contract between Donna's generator and the renderer.
 *
 * The generator (future: LLM + memory pipeline; today: static fixtures + rule-based composer)
 * produces a DashboardPlan. The renderer maps each Block to a component.
 *
 * Blocks carry EMOTIONAL REGISTER, not just information. Register is a design primitive:
 *   witness | confrontation | celebration | permission | reflection | invitation | reminder
 * The generator picks blocks to serve a THESIS — the single sentence for this moment.
 */

export type IconName =
  | 'phone' | 'drop' | 'bowl' | 'flower' | 'flame' | 'rupee'
  | 'moon' | 'sun' | 'heart' | 'leaf' | 'eye' | 'hourglass'
  | 'bell' | 'plug' | 'sparkles' | 'pencil' | 'mic' | 'check' | 'x';

// ── ActionVerb ────────────────────────────────────────────────────────────
// Every interactive element on the dashboard carries an ActionVerb. Tap →
// POST /api/dashboard/action → backend executes verb → brain notified →
// WhatsApp ack. The dashboard never mutates state directly.
export type ActionVerb =
  | { v: 'start_tracker'; name: string }
  | { v: 'log_value'; tracker: string; value: number; unit?: string }
  | { v: 'complete_pick'; pickId: string }
  | { v: 'snooze_reminder'; reminderId: string; until: string }
  | { v: 'mark_reminder_done'; reminderId: string }
  | { v: 'dismiss_attention'; attentionId: string }
  | { v: 'accept_attention'; attentionId: string }
  | { v: 'connect_integration'; provider: string }
  | { v: 'accept_draft'; draftId: string }
  | { v: 'decide_option'; decisionId: string; optionId: string }
  | { v: 'quick_log'; kind: string; payload: unknown }
  | { v: 'open_relationship'; personId: string }
  | { v: 'open_news'; newsId: string }
  | { v: 'open_tracker'; tracker: string }
  | { v: 'open_attention'; attentionId: string }
  | { v: 'reply_chip'; intent: string };

export type SignalTone = 'ink' | 'rust' | 'moss' | 'amber' | 'oxblood';

// ── Domain ─────────────────────────────────────────────────────────────────
// User-side surfaces of interest. Blocks on Page 2 carry a domain so the
// renderer can group them under sticky headers ("body", "people", "work")
// and collapse rails with no signal. Page 1 blocks may also carry a
// domain, but the renderer doesn't group them — the editorial cover
// stays flat.
export type Domain =
  | 'body'    // calories, sleep, water, mood, training, weight
  | 'people'  // last touch, drafts to send, who's on user's mind
  | 'work'    // open loops, decisions, drafts, projects, meeting prep
  | 'money'   // spend, runway, recurring subs, refunds
  | 'mind'   // reflections, patterns, contradictions
  | 'day';    // schedule, time, what's coming next

export type MomentTag =
  | 'dawn' | 'morning' | 'midday' | 'afternoon' | 'evening' | 'night' | 'late';

export type Register =
  | 'witness' | 'confrontation' | 'celebration' | 'permission'
  | 'reflection' | 'invitation' | 'reminder';

// ── Block: thesis — the one sentence for this moment ─────────────────────
export interface ThesisBlock {
  type: 'thesis';
  /** The one sentence. Keep it under 90 chars. Lowercase, blunt. */
  sentence: string;
  /** Optional kicker: "today" | "this evening" | "right now" */
  kicker?: string;
}

// ── Block: hero ───────────────────────────────────────────────────────────
export interface HeroBlock {
  type: 'hero';
  date: string;
  greeting: string;
  subtext: string;
  illustration?: 'mumbai' | 'singapore' | 'none';
}

// ── Block: whisper (Donna's voice; omit for minimal-voice plans) ──────────
export interface WhisperBlock {
  type: 'whisper';
  kicker: string;
  body: string;
  level?: 'subtle' | 'loud';
}

// ── Block: witness — "i saw you" ──────────────────────────────────────────
export interface WitnessBlock {
  type: 'witness';
  /** What Donna saw. Third-person observation of the user. */
  observation: string;
  /** Optional: where she saw it ("tuesday's chat", "your calendar") */
  source?: string;
}

// ── Block: confrontation — "stop lying to yourself" ──────────────────────
export interface ConfrontationBlock {
  type: 'confrontation';
  /** Short, declarative. No softening. */
  title: string;
  body: string;
  /** Optional: what would count as a response */
  ask?: string;
}

// ── Block: celebration — "you did the thing" ─────────────────────────────
export interface CelebrationBlock {
  type: 'celebration';
  title: string;
  body: string;
  /** Optional streak or count */
  badge?: string;
}

// ── Block: reflection — evening, journal-adjacent ────────────────────────
export interface ReflectionBlock {
  type: 'reflection';
  title: string;
  /** 1–3 prompts Donna is offering. Keep them short. */
  prompts: string[];
}

// ── Block: open-loops — threads donna is tracking ────────────────────────
export interface OpenLoop {
  id: string;
  title: string;
  /** "3 days ago" · "you said thursday" */
  age: string;
  /** short commitment text */
  commitment: string;
}
export interface OpenLoopsBlock {
  type: 'open-loops';
  title: string;
  items: OpenLoop[];
}

// ── Block: weather-of-you — emotional/energy snapshot ────────────────────
export interface WeatherOfYouBlock {
  type: 'weather-of-you';
  /** One-word tag: "tired" | "scattered" | "bright" | "anxious" | "steady" */
  mood: string;
  /** 0..1, Donna's read on energy */
  energy: number;
  /** Evidence line: what made her think this */
  basis: string;
}

// ── Block: calendar-shape — the day at a glance ──────────────────────────
export interface CalendarSlot {
  id: string;
  /** "9:00" */
  at: string;
  label: string;
  /** duration in minutes, used for relative width */
  duration: number;
  kind: 'meeting' | 'focus' | 'break' | 'travel' | 'personal';
}
export interface CalendarShapeBlock {
  type: 'calendar-shape';
  title: string;
  slots: CalendarSlot[];
  /** free-text read of the day: "four meetings, tight gaps" */
  shapeRead?: string;
}

// ── Block: todo-list ──────────────────────────────────────────────────────
export interface TodoItem {
  id: string;
  label: string;
  meta: string;
  source: string;
  done?: boolean;
  /** Optional action fired when the user taps the checkbox. */
  action?: ActionVerb;
}
export interface TodoListBlock {
  type: 'todo-list';
  title: string;
  items: TodoItem[];
}

// ── Block: tracker-grid ───────────────────────────────────────────────────
export interface TrackerItem {
  id: string;
  title: string;
  value: string;
  unit: string;
  sub: string;
  progress: number; // 0..1
  icon: IconName;
  tone: SignalTone;
  tint: 'amber' | 'moss' | 'rust' | 'paper';
  /** Tap to drill in or quick-log. */
  action?: ActionVerb;
}
export interface TrackerGridBlock {
  type: 'tracker-grid';
  title: string;
  items: TrackerItem[];
}

// ── Block: nudge-grid ─────────────────────────────────────────────────────
export type NudgeVariant = 'neutral' | 'moss' | 'amber' | 'featured';
export interface NudgeItem {
  id: string;
  title: string;
  meta: string;
  cta: string;
  icon: IconName;
  variant: NudgeVariant;
  progress?: number;
  /** Optional action fired when the user taps the nudge card. */
  action?: ActionVerb;
}
export interface NudgeGridBlock {
  type: 'nudge-grid';
  title: string;
  items: NudgeItem[];
}

// ── Block: permission — "rest is work" ────────────────────────────────────
export interface PermissionBlock {
  type: 'permission';
  title: string;
  body: string;
  /** Optional acknowledgement action. */
  action?: ActionVerb;
}

// ── Block: reminders — time-anchored alerts for today ─────────────────────
export interface ReminderItem {
  id: string;
  /** "9:00 am" · "in 2h" · "by 6 pm" */
  at: string;
  label: string;
  /** optional one-line context */
  meta?: string;
  done?: boolean;
  action?: ActionVerb;
}
export interface RemindersBlock {
  type: 'reminders';
  title: string;
  items: ReminderItem[];
}

// ── Block: tracker-starter — Donna offers to start a new tracker ──────────
export interface TrackerStarterBlock {
  type: 'tracker-starter';
  title: string;
  /** Why she's offering this — quoted user signal. */
  rationale: string;
  /** What the tracker would track, in user-facing language. */
  trackerName: string;
  cta: string;
  icon: IconName;
  /** Tap to confirm starting the tracker — fires start_tracker verb. */
  action: ActionVerb;
}

// ── Block: relationship — people Donna is tracking ────────────────────────
export interface RelationshipItem {
  id: string;
  name: string;
  /** "your dad" · "Luca" · "Priya, cofounder" */
  role?: string;
  /** "6 days since" · "you said this week" */
  lastTouch: string;
  /** Optional nudge — what Donna thinks should happen next. */
  nudge?: string;
  /** Optional avatar initial (fallback when no image). */
  initial: string;
  action?: ActionVerb;
}
export interface RelationshipBlock {
  type: 'relationship';
  title: string;
  items: RelationshipItem[];
}

// ── Block: news-brief — proactive content cards ───────────────────────────
export interface NewsBriefItem {
  id: string;
  /** A single sharp sentence — Donna's read on why this is worth surfacing. */
  headline: string;
  /** Source domain or feed name. */
  source: string;
  /** Optional "since yesterday" / "today" tag. */
  tag?: string;
  url?: string;
  action?: ActionVerb;
}
export interface NewsBriefBlock {
  type: 'news-brief';
  title: string;
  items: NewsBriefItem[];
}

// ── Catalogue blocks (#04–#21, faithful ports from the design specimen) ──
// All catalogue archetypes use the `c-` prefix to coexist with legacy block
// types. They define their own visual treatment internally; the renderer just
// dispatches by `type`.
export type {
  CatTrackerSpec,
  TrackerCatItem,
  TrackerTint,
} from '@/components/blocks/catalogue/CatTracker';
export type {
  CatWatchSpec,
  WatchItem,
  CatBriefSpec,
  BriefIndexItem,
  CatPrepSpec,
  PrepItem,
  CatScheduleSpec,
  ScheduleSlot,
  ScheduleStripBlock,
  CatStreakSpec,
  CatPersonSpec,
  PersonItem,
  CatReminderSpec,
  ReminderItemCat,
  CatQuickLogSpec,
  QuickLogChip,
  CatPickSpec,
  CatOfferSpec,
  CatDraftSpec,
  CatDecisionSpec,
  DecisionOption,
  CatConfrontSpec,
  CatReflectionSpec,
  CatOpenLoopSpec,
  OpenLoopItem,
  CatPermissionSpec,
  CatReadSpec,
  ReadItem,
} from '@/components/blocks/catalogue/CatBlocks';

import type {
  CatTrackerSpec,
} from '@/components/blocks/catalogue/CatTracker';
import type {
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
} from '@/components/blocks/catalogue/CatBlocks';

// ── Block: note ───────────────────────────────────────────────────────────
// Catalogue archetype #02. Donna's voice on the moment, sits below the intro.
// Three flavors: editorial (borderless, breathing), bar (rust-tint left-stripe),
// confront (oxblood, heavier — for kind=confrontation only).
export interface NoteBlock {
  type: 'note';
  kind?: 'editorial' | 'bar' | 'confront';
  eyebrow?: string;       // default: "a note from me"
  body: string;
  actions?: {
    primary?: string;     // default: "noted"
    secondary?: string;   // default: "say more" — accent color
    tertiary?: string;    // default: "skip"
  };
}

// ── Block: footer ─────────────────────────────────────────────────────────
// Catalogue archetype #03. Three flavors: caps (status line), italic (warmest),
// mark (the donna mark with hairline rules — for morning-hero moments).
export interface FooterBlock {
  type: 'footer';
  text: string;
  kind?: 'caps' | 'italic' | 'mark';
}

// ── Capability block (#22) — "things donna can do for you" ───────────────
// Catalogue archetype #22. Tappable chips/rows. Each item is a verb the
// user can fire by tapping; the tap sends `intent` to donna over WhatsApp
// so she can do the thing. This is the dashboard's command palette.
export interface CapabilityItem {
  label: string;
  intent: string;
  icon?: import('@/components/blocks/catalogue/icons').CatIconName;
}
export interface CatCapabilitySpec {
  type: 'c-capability';
  variant: 'chips' | 'rows';
  title?: string;
  eyebrow?: string;
  items: CapabilityItem[];
}

// 23 · Recipe mosaic — Day 1 / sparse-signal CTA surface.
// Each tile = "one tap and donna sets up a multi-step pipeline." On
// tap the tile opens a WhatsApp deeplink with `primer` pre-filled;
// donna's normal tool loop handles the actual setup on the inbound.
export interface RecipeItem {
  title: string;
  body: string;
  primer: string;
  tone?: 'ink' | 'rust' | 'moss' | 'amber' | 'oxblood';
  icon?: import('@/components/blocks/catalogue/icons').CatIconName;
  size?: 'short' | 'tall';
}
export interface CatRecipeMosaicSpec {
  type: 'c-recipe-mosaic';
  /** ``mosaic`` = full pinterest masonry (Day 1).
   *  ``chips``  = compact pill row (Page 2 footer for established users). */
  variant?: 'mosaic' | 'chips';
  eyebrow?: string;
  title?: string;
  items: RecipeItem[];
}

export type Block =
  | ThesisBlock
  | HeroBlock
  | WhisperBlock
  | WitnessBlock
  | ConfrontationBlock
  | CelebrationBlock
  | ReflectionBlock
  | OpenLoopsBlock
  | WeatherOfYouBlock
  | CalendarShapeBlock
  | TodoListBlock
  | TrackerGridBlock
  | NudgeGridBlock
  | PermissionBlock
  | RemindersBlock
  | TrackerStarterBlock
  | RelationshipBlock
  | NewsBriefBlock
  | NoteBlock
  | FooterBlock
  | CatTrackerSpec
  | CatWatchSpec
  | CatBriefSpec
  | CatPrepSpec
  | CatScheduleSpec
  | CatStreakSpec
  | CatPersonSpec
  | CatReminderSpec
  | CatQuickLogSpec
  | CatPickSpec
  | CatOfferSpec
  | CatDraftSpec
  | CatDecisionSpec
  | CatConfrontSpec
  | CatReflectionSpec
  | CatOpenLoopSpec
  | CatPermissionSpec
  | CatReadSpec
  | CatCapabilitySpec
  | CatRecipeMosaicSpec;

// ── Multi-page composition (catalogue v2) ────────────────────────────────
// The dashboard is three pages, not one screen.
//   id="now"   — the editorial read for this moment (hero-led, restrained)
//   id="today" — the operational view (schedule, trackers, watches, briefs)
//   id="hold"  — what donna is holding + what she can do
//
// Renderer prefers `pages[]` when present; falls back to flat `blocks[]`.
export type PageId = 'now' | 'today' | 'hold';

export interface DashboardPage {
  id: PageId;
  /** short eyebrow rendered above the page title (e.g. "now", "today") */
  kicker?: string;
  /** optional page-level read */
  thesis?: string;
  blocks: Block[];
}

export interface DashboardPlan {
  id: string;
  generatedAt: string;
  user: { name: string; initial: string };
  /** The one sentence this plan commits to. Required. */
  thesis: string;
  /** Moment tag that produced this plan. */
  moment: MomentTag;
  blocks: Block[];
  /**
   * Optional row-based composition. Legacy — most catalogue plans omit this.
   */
  rows?: Row[];
  /** Optional intro region (legacy). Catalogue plans use a hero block instead. */
  intro?: IntroSpec;
  /**
   * Three-page layout (catalogue mode v2). When present, the renderer
   * shows a paged surface; the flat `blocks[]` is ignored. Each page
   * carries its own kicker + thesis + blocks.
   */
  pages?: DashboardPage[];
}

// ── Row-based composition (visual contract) ───────────────────────────────
// A Row is a slice of the dashboard with up to four cells. Each cell holds
// a single Block (the content) sized to a SlotSize (the layout). The
// renderer walks rows → cells → blocks and wraps each cell's block in a
// <Frame>.

export type SlotSize =
  | 'full'
  | 'three-quarters'
  | 'two-thirds'
  | 'half'
  | 'third'
  | 'quarter';

export interface Cell {
  size: SlotSize;
  block: Block;
}

export interface Row {
  /** Optional row-level title rendered as a section title above the cells. */
  title?: string;
  /** Optional right-aligned meta count, e.g. "1 of 3 kept". */
  meta?: string;
  cols: Cell[];
}

/** Intro region — the fixed top region (system.html §6). */
export interface IntroSpec {
  /** "friday · 18 april" — uppercase tracking label. */
  kicker: string;
  /** Greeting prefix before the accent: "good morning, " */
  greetingPrefix?: string;
  /** Italic rust accent (usually the name). */
  accent?: string;
  /** Trailing punctuation after the accent: "." */
  greetingSuffix?: string;
  /** Full greeting (alternative to prefix/accent split). */
  greeting?: string;
  /** "mumbai · 29° · slight haze, cooler by the sea" */
  place?: string;
  /** Illustration ID — renderer maps to an SVG. */
  illustrationId?: 'mumbai' | 'tea' | 'book' | 'moon' | 'glass' | 'walk' | 'none';
}

// ── Validation ────────────────────────────────────────────────────────────
// Enforces design-system rules that types alone can't capture.

export interface PlanIssue {
  severity: 'error' | 'warning';
  rule: string;
  message: string;
}

/** Weights used by the density budget. Heavier blocks cost more. */
const DENSITY_WEIGHTS: Record<Block['type'], number> = {
  thesis: 1,
  hero: 3,
  whisper: 1,
  witness: 1,
  confrontation: 2,
  celebration: 2,
  reflection: 2,
  'open-loops': 2,
  'weather-of-you': 1,
  'calendar-shape': 2,
  'todo-list': 3,
  'tracker-grid': 2,
  'nudge-grid': 3,
  permission: 1,
  reminders: 2,
  'tracker-starter': 2,
  relationship: 2,
  'news-brief': 2,
  note: 1,
  footer: 0,
  'c-tracker': 2,
  'c-watch': 2,
  'c-brief': 2,
  'c-prep': 2,
  'c-schedule': 2,
  'c-streak': 1,
  'c-person': 2,
  'c-reminder': 2,
  'c-quicklog': 1,
  'c-pick': 1,
  'c-offer': 2,
  'c-draft': 2,
  'c-decision': 2,
  'c-confront': 2,
  'c-reflection': 2,
  'c-openloop': 2,
  'c-permission': 1,
  'c-read': 2,
  'c-capability': 2,
  'c-recipe-mosaic': 4,
};

export const DENSITY_BUDGET = 12;

export function validatePlan(plan: DashboardPlan): PlanIssue[] {
  const issues: PlanIssue[] = [];

  // R-C1 · One rust per screen — at most one featured nudge.
  const featuredCount = plan.blocks.reduce((n, b) => {
    if (b.type !== 'nudge-grid') return n;
    return n + b.items.filter((i) => i.variant === 'featured').length;
  }, 0);
  if (featuredCount > 1) {
    issues.push({
      severity: 'error',
      rule: 'R-C1',
      message: `One rust per screen: found ${featuredCount} featured nudges.`,
    });
  }

  // P-H1 · At most one hero, at the top.
  const heroIndices = plan.blocks
    .map((b, i) => (b.type === 'hero' ? i : -1))
    .filter((i) => i >= 0);
  if (heroIndices.length > 1) {
    issues.push({ severity: 'error', rule: 'P-H1', message: 'Multiple hero blocks in plan.' });
  }
  if (heroIndices.length === 1 && heroIndices[0] !== 0) {
    issues.push({ severity: 'warning', rule: 'P-H1', message: 'Hero should be the first block.' });
  }

  // P-TH1 · At most one thesis block, should be near the top.
  const thesisCount = plan.blocks.filter((b) => b.type === 'thesis').length;
  if (thesisCount > 1) {
    issues.push({ severity: 'error', rule: 'P-TH1', message: 'Multiple thesis blocks in plan.' });
  }

  // P-R1 · Register budget — max one confrontation AND one celebration per plan.
  const confrontCount = plan.blocks.filter((b) => b.type === 'confrontation').length;
  const celebrateCount = plan.blocks.filter((b) => b.type === 'celebration').length;
  if (confrontCount > 1) {
    issues.push({
      severity: 'error',
      rule: 'P-R1',
      message: `Register budget: found ${confrontCount} confrontations (max 1).`,
    });
  }
  if (celebrateCount > 1) {
    issues.push({
      severity: 'error',
      rule: 'P-R1',
      message: `Register budget: found ${celebrateCount} celebrations (max 1).`,
    });
  }
  if (confrontCount >= 1 && celebrateCount >= 1) {
    issues.push({
      severity: 'warning',
      rule: 'P-R2',
      message: 'Confrontation + celebration in same plan is emotionally incoherent.',
    });
  }

  // P-D1 · Density budget — total visual weight.
  const density = plan.blocks.reduce((n, b) => n + DENSITY_WEIGHTS[b.type], 0);
  if (density > DENSITY_BUDGET) {
    issues.push({
      severity: 'warning',
      rule: 'P-D1',
      message: `Plan density ${density} exceeds budget ${DENSITY_BUDGET} — screen will feel heavy.`,
    });
  }

  // P-T1 · Tracker grid: 1..3 items.
  for (const b of plan.blocks) {
    if (b.type === 'tracker-grid' && (b.items.length < 1 || b.items.length > 3)) {
      issues.push({
        severity: 'warning',
        rule: 'P-T1',
        message: `Tracker grid has ${b.items.length} items; layout is tuned for 1–3.`,
      });
    }
  }

  // P-TH2 · Plan must have a thesis string.
  if (!plan.thesis || plan.thesis.trim().length === 0) {
    issues.push({ severity: 'error', rule: 'P-TH2', message: 'Plan is missing a thesis.' });
  }

  return issues;
}

export function planDensity(plan: DashboardPlan): number {
  return plan.blocks.reduce((n, b) => n + DENSITY_WEIGHTS[b.type], 0);
}

/**
 * The generator seam. Today: returns a static fixture. Tomorrow: calls
 * the v2 memory pipeline + LLM to compose a plan per user per moment.
 */
export type PlanSource = (userId: string, now: Date) => Promise<DashboardPlan> | DashboardPlan;
