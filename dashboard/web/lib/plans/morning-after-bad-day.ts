import type { DashboardPlan } from '../plan';

/**
 * Morning after a rough day. Donna is quieter, not-louder.
 * Thesis is about recovery, not productivity.
 * Register: witness + permission + one gentle nudge. No confrontation.
 */
export const morningAfterBadDayPlan: DashboardPlan = {
  id: 'plan:aarav:2026-04-22:morning-after-bad-day',
  generatedAt: '2026-04-22T08:20:00+05:30',
  user: { name: 'Aarav', initial: 'A' },
  thesis: "yesterday was hard. today doesn't have to be big.",
  moment: 'morning',
  blocks: [
    {
      type: 'hero',
      date: 'Wednesday · 22 April',
      greeting: 'Hey.',
      subtext: 'Mumbai · 28° · overcast',
      illustration: 'none',
    },
    {
      type: 'thesis',
      kicker: 'today',
      sentence: "yesterday was hard. today doesn't have to be big.",
    },
    {
      type: 'weather-of-you',
      mood: 'tender',
      energy: 0.28,
      basis: 'you slept four hours. you were quiet in chat after nine.',
    },
    {
      type: 'permission',
      title: 'one thing is enough today.',
      body: "you don't owe anyone a productive day. pick one small thing. let the rest slide. we can pick the pace back up tomorrow.",
    },
    {
      type: 'witness',
      observation: "you told priya you'd send the deck on friday. that's still friday. it's not today's problem.",
      source: 'tuesday email',
    },
    {
      type: 'nudge-grid',
      title: 'if you feel like it',
      items: [
        { id: 'n1', title: 'Glass of water', meta: 'start small',                 cta: 'Log one',       icon: 'drop',  variant: 'moss' },
        { id: 'n2', title: 'Step outside',   meta: 'ten minutes, no phone',       cta: 'Set a timer',   icon: 'leaf',  variant: 'neutral' },
      ],
    },
    { type: 'footer', text: "I'm here when you want me" },
  ],
};
