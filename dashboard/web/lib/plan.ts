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
  | 'moon' | 'sun' | 'heart' | 'leaf' | 'eye' | 'hourglass';

export type SignalTone = 'ink' | 'rust' | 'moss' | 'amber' | 'oxblood';

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
  illustration?: 'mumbai' | 'none';
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
}

// ── Block: footer ─────────────────────────────────────────────────────────
export interface FooterBlock {
  type: 'footer';
  text: string;
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
  | FooterBlock;

export interface DashboardPlan {
  id: string;
  generatedAt: string;
  user: { name: string; initial: string };
  /** The one sentence this plan commits to. Required. */
  thesis: string;
  /** Moment tag that produced this plan. */
  moment: MomentTag;
  blocks: Block[];
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
  footer: 0,
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
