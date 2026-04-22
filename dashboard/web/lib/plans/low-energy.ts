import type { DashboardPlan } from '../plan';

/**
 * Late night. User is spiralling, restless, can't sleep.
 * Donna gets small. One sentence. One permission. Nothing else.
 * A plan with four blocks. No trackers, no calendars, no nudges.
 * This is what it looks like when Donna chooses restraint over surface area.
 */
export const lowEnergyPlan: DashboardPlan = {
  id: 'plan:aarav:2026-04-22:late',
  generatedAt: '2026-04-22T23:48:00+05:30',
  user: { name: 'Aarav', initial: 'A' },
  thesis: 'go to bed, aarav. nothing here needs you right now.',
  moment: 'late',
  blocks: [
    {
      type: 'thesis',
      kicker: 'right now',
      sentence: 'go to bed, aarav. nothing here needs you right now.',
    },
    {
      type: 'permission',
      title: 'the list will still be here in the morning.',
      body: "you check your phone when you're spiralling. the dashboard doesn't have anything that earns your 11:48pm attention. close it. drink water. lie down.",
    },
    {
      type: 'witness',
      observation: "you opened this dashboard four times in the last hour. you're looking for a reason. there isn't one tonight.",
    },
    { type: 'footer', text: "I'll be here tomorrow. rest." },
  ],
};
