/**
 * Thesis-first generator — the seam where Donna's LLM will eventually sit.
 *
 * Today: rule-based composer that proves the architecture.
 * Tomorrow: the same shape, same MomentContext input, same DashboardPlan
 * output, but the compose(thesis) and compose(blocks) steps will be LLM calls
 * grounded in the real memory layers.
 *
 * The key discipline: THESIS FIRST. A plan is a commitment to one sentence.
 * Blocks are chosen to serve that sentence, never the other way around.
 */

import type {
  Block,
  DashboardPlan,
  MomentTag,
  OpenLoop,
  TrackerItem,
  CalendarSlot,
} from './plan';
import { planDensity, validatePlan, DENSITY_BUDGET } from './plan';

// ── MomentContext — the read-side snapshot ────────────────────────────────
// This is what a future "dashboard state collector" would return. It unions
// signals from all 9 memory backends. Keep it boring; let the generator be
// interesting.

export interface MomentContext {
  user: { name: string; initial: string };
  now: Date;
  /** 0..1 — Donna's read of energy right now */
  energy: number;
  /** One-word mood tag */
  mood: string;
  /** Evidence for the mood/energy read */
  moodBasis: string;
  /** Is yesterday classified as "hard"? (poor sleep, disengaged, low output) */
  yesterdayWasHard: boolean;
  /** Did a significant loop close in the last hour? (call made, deck sent) */
  recentWin?: { title: string; body: string; badge?: string };
  /** A pattern Donna wants to confront, if severe enough */
  patternToConfront?: { title: string; body: string; ask?: string };
  /** Open loops Donna is tracking */
  openLoops: OpenLoop[];
  /** Trackers with progress */
  trackers: TrackerItem[];
  /** The shape of today, if calendar has any entries left */
  calendarSlots: CalendarSlot[];
  /** If user has opened the dashboard repeatedly in a short window, set this */
  isSpiralling: boolean;
}

// ── Moment tagging ────────────────────────────────────────────────────────

/** IST (UTC+5:30) hour of day, 0..23. Donna is Mumbai-native; we anchor to IST. */
export function istHourOf(date: Date): number {
  const utcMs = date.getTime();
  const istMs = utcMs + (5 * 60 + 30) * 60 * 1000;
  return new Date(istMs).getUTCHours();
}

export function momentTagFor(date: Date): MomentTag {
  const h = istHourOf(date);
  if (h < 5)  return 'late';
  if (h < 6)  return 'dawn';
  if (h < 10) return 'morning';
  if (h < 14) return 'midday';
  if (h < 17) return 'afternoon';
  if (h < 21) return 'evening';
  if (h < 24) return 'night';
  return 'late';
}

// ── Thesis composer ───────────────────────────────────────────────────────
// Given context, write the one sentence. This is where the LLM earns its cost.
// Rules encode the priorities: safety > celebration > confrontation > loops > default.

export function composeThesis(ctx: MomentContext): string {
  const tag = momentTagFor(ctx.now);

  if (tag === 'late' && ctx.isSpiralling) {
    return `go to bed, ${ctx.user.name.toLowerCase()}. nothing here needs you right now.`;
  }
  if (ctx.recentWin) {
    return `you did ${ctx.recentWin.title.toLowerCase()}. that was the week's weight.`;
  }
  if (ctx.yesterdayWasHard && (tag === 'morning' || tag === 'dawn')) {
    return "yesterday was hard. today doesn't have to be big.";
  }
  if (tag === 'evening' || tag === 'night') {
    return 'what was today, actually?';
  }
  if (ctx.openLoops.length > 0 && (tag === 'morning' || tag === 'midday')) {
    const top = ctx.openLoops[0];
    return `today is about ${top.title.toLowerCase()} before it gets weirder.`;
  }
  if (tag === 'midday') {
    const open = ctx.openLoops.length;
    return `halfway through. ${open > 0 ? `${open} open, rest on track.` : 'rest on track.'}`;
  }
  return 'a quiet moment. nothing loud to surface.';
}

// ── Block composer ────────────────────────────────────────────────────────
// Given the thesis + context, pick blocks that serve it. Budget-aware.
// Rules encode register coherence and density discipline.

export function composeBlocks(ctx: MomentContext, thesis: string): Block[] {
  const tag = momentTagFor(ctx.now);
  const blocks: Block[] = [];

  // Special case: late-night spiral. Minimal surface.
  if (tag === 'late' && ctx.isSpiralling) {
    blocks.push({ type: 'thesis', kicker: 'right now', sentence: thesis });
    blocks.push({
      type: 'permission',
      title: 'the list will still be here in the morning.',
      body: "you check your phone when you're spiralling. close it. drink water. lie down.",
    });
    blocks.push({
      type: 'witness',
      observation: "you opened this dashboard more than once in the last hour. you're looking for a reason. there isn't one tonight.",
    });
    blocks.push({ type: 'footer', text: "I'll be here tomorrow. rest." });
    return blocks;
  }

  // Morning: add hero. Other moments: no hero, thesis is the opener.
  if (tag === 'morning' || tag === 'dawn') {
    blocks.push({
      type: 'hero',
      date: formatDate(ctx.now),
      greeting: greetingFor(tag, ctx.user.name),
      subtext: 'Mumbai · 28° · morning',
      illustration: ctx.yesterdayWasHard ? 'none' : 'mumbai',
    });
  }

  blocks.push({
    type: 'thesis',
    kicker: kickerFor(tag),
    sentence: thesis,
  });

  // Recovery morning: weather + permission + quiet witness. No trackers.
  if (ctx.yesterdayWasHard && (tag === 'morning' || tag === 'dawn')) {
    blocks.push({
      type: 'weather-of-you',
      mood: ctx.mood,
      energy: ctx.energy,
      basis: ctx.moodBasis,
    });
    blocks.push({
      type: 'permission',
      title: 'one thing is enough today.',
      body: "you don't owe anyone a productive day. pick one small thing. let the rest slide.",
    });
    blocks.push({ type: 'footer', text: "I'm here when you want me" });
    return blocks;
  }

  // Celebration path: lead with the landing, then quiet forward-look.
  if (ctx.recentWin) {
    blocks.push({
      type: 'celebration',
      title: ctx.recentWin.title,
      body: ctx.recentWin.body,
      badge: ctx.recentWin.badge,
    });
    if (canAfford(blocks, 2)) {
      blocks.push({
        type: 'witness',
        observation: 'you sounded lighter afterward. that\'s the sentence worth remembering next time.',
      });
    }
    blocks.push({ type: 'footer', text: "rest easy. I'll see you tomorrow." });
    return blocks;
  }

  // Evening reflection path.
  if (tag === 'evening' || tag === 'night') {
    if (canAfford(blocks, 1)) {
      blocks.push({
        type: 'weather-of-you',
        mood: ctx.mood,
        energy: ctx.energy,
        basis: ctx.moodBasis,
      });
    }
    if (canAfford(blocks, 2)) {
      blocks.push({
        type: 'reflection',
        title: 'three to sit with',
        prompts: [
          'what felt right about today, even briefly?',
          "where did you lose yourself to other people's pace?",
          'what wants to stay here, not tomorrow?',
        ],
      });
    }
    if (ctx.patternToConfront && canAfford(blocks, 2)) {
      blocks.push({
        type: 'confrontation',
        title: ctx.patternToConfront.title,
        body: ctx.patternToConfront.body,
        ask: ctx.patternToConfront.ask,
      });
    }
    blocks.push({ type: 'footer', text: "I'm here before bed" });
    return blocks;
  }

  // Morning / midday forward-leaning path.
  if (ctx.calendarSlots.length > 0 && canAfford(blocks, 2) && (tag === 'morning' || tag === 'dawn')) {
    blocks.push({
      type: 'calendar-shape',
      title: "today's shape",
      shapeRead: readCalendarShape(ctx.calendarSlots),
      slots: ctx.calendarSlots,
    });
  }

  if (ctx.trackers.length > 0 && canAfford(blocks, 2) && tag === 'midday') {
    blocks.push({
      type: 'tracker-grid',
      title: 'so far today',
      items: ctx.trackers.slice(0, 3),
    });
  }

  if (ctx.openLoops.length > 0 && canAfford(blocks, 2)) {
    blocks.push({
      type: 'open-loops',
      title: 'still open',
      items: ctx.openLoops.slice(0, 3),
    });
  }

  blocks.push({ type: 'footer', text: "I'm listening · tap to talk" });
  return blocks;

  // Local helper: keep the plan within density budget.
  function canAfford(current: Block[], weight: number): boolean {
    const used = current.reduce((n, b) => n + weightOf(b), 0);
    return used + weight <= DENSITY_BUDGET;
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────

function weightOf(b: Block): number {
  const w: Record<Block['type'], number> = {
    thesis: 1, hero: 3, whisper: 1, witness: 1, confrontation: 2,
    celebration: 2, reflection: 2, 'open-loops': 2, 'weather-of-you': 1,
    'calendar-shape': 2, 'todo-list': 3, 'tracker-grid': 2, 'nudge-grid': 3,
    permission: 1, footer: 0,
  };
  return w[b.type];
}

function greetingFor(tag: MomentTag, name: string): string {
  if (tag === 'dawn') return `early, ${name}.`;
  return `morning, ${name}.`;
}

function kickerFor(tag: MomentTag): string {
  if (tag === 'morning' || tag === 'dawn') return 'today';
  if (tag === 'midday') return 'right now';
  if (tag === 'evening' || tag === 'night') return 'this evening';
  if (tag === 'afternoon') return 'this afternoon';
  return 'right now';
}

function formatDate(d: Date): string {
  const days = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
  const months = ['January','February','March','April','May','June','July','August','September','October','November','December'];
  return `${days[d.getDay()]} · ${d.getDate()} ${months[d.getMonth()]}`;
}

function readCalendarShape(slots: CalendarSlot[]): string {
  const meetings = slots.filter((s) => s.kind === 'meeting').length;
  const focus = slots.filter((s) => s.kind === 'focus').length;
  if (meetings >= 4) return `${meetings} meetings, tight gaps`;
  if (focus >= 2) return `room to think between blocks`;
  return `a reasonable day`;
}

// ── Top-level compose ─────────────────────────────────────────────────────

export function generatePlan(ctx: MomentContext): DashboardPlan {
  const thesis = composeThesis(ctx);
  const blocks = composeBlocks(ctx, thesis);
  const plan: DashboardPlan = {
    id: `plan:${ctx.user.name.toLowerCase()}:${ctx.now.toISOString().slice(0,10)}:${momentTagFor(ctx.now)}`,
    generatedAt: ctx.now.toISOString(),
    user: ctx.user,
    thesis,
    moment: momentTagFor(ctx.now),
    blocks,
  };

  if (process.env.NODE_ENV !== 'production') {
    const issues = validatePlan(plan);
    const density = planDensity(plan);
    // eslint-disable-next-line no-console
    console.info(`[generator] thesis="${thesis}" density=${density}/${DENSITY_BUDGET} issues=${issues.length}`);
  }

  return plan;
}
