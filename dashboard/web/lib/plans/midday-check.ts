import type { DashboardPlan } from '../plan';

/**
 * Midday drive-by. Short, functional. Trackers + one open loop.
 * Thesis: a status line, not a story.
 * Register: reminder. Dense but not loud.
 */
export const middayCheckPlan: DashboardPlan = {
  id: 'plan:aarav:2026-04-22:midday',
  generatedAt: '2026-04-22T13:05:00+05:30',
  user: { name: 'Aarav', initial: 'A' },
  thesis: 'halfway through. one thing is open. rest is on track.',
  moment: 'midday',
  blocks: [
    {
      type: 'thesis',
      kicker: 'right now',
      sentence: 'halfway through. one thing is open. rest is on track.',
    },
    {
      type: 'tracker-grid',
      title: 'so far today',
      items: [
        { id: 'tr-cal',   title: 'Calories', value: '820',   unit: 'of 2,200',            sub: 'Idli at breakfast', progress: 0.37, icon: 'flame',  tone: 'amber', tint: 'amber' },
        { id: 'tr-water', title: 'Water',    value: '3',     unit: 'of 8 glasses',         sub: 'keep going',         progress: 0.37, icon: 'drop',   tone: 'moss',  tint: 'moss' },
        { id: 'tr-spend', title: 'Spend',    value: '₹ 280', unit: 'today',                sub: 'coffee · auto',      progress: 0.20, icon: 'rupee',  tone: 'ink',   tint: 'paper' },
      ],
    },
    {
      type: 'open-loops',
      title: 'still open',
      items: [
        { id: 'l1', title: 'Call Dad',  age: '6 days', commitment: "you said 'this week' on tuesday" },
      ],
    },
    { type: 'footer', text: 'tap to adjust · I am listening' },
  ],
};
