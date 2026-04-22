import type { DashboardPlan } from '../plan';

/**
 * Evening. The day is mostly cooked. Donna shifts to reflective mode.
 * Register: reflection + witness. One gentle confrontation if warranted.
 * Thesis: a question, not a task.
 */
export const eveningReflectionPlan: DashboardPlan = {
  id: 'plan:aarav:2026-04-22:evening',
  generatedAt: '2026-04-22T21:15:00+05:30',
  user: { name: 'Aarav', initial: 'A' },
  thesis: 'what was today, actually?',
  moment: 'evening',
  blocks: [
    {
      type: 'thesis',
      kicker: 'this evening',
      sentence: 'what was today, actually?',
    },
    {
      type: 'weather-of-you',
      mood: 'scattered',
      energy: 0.42,
      basis: 'you checked in with me seven times. most were mid-meeting. the calls ran long.',
    },
    {
      type: 'witness',
      observation: "you called dad at 6:12pm. twenty-two minutes. you told me it 'wasn't as bad' as you thought. that was the thesis of the day landing.",
      source: 'tonight',
    },
    {
      type: 'reflection',
      title: 'three to sit with',
      prompts: [
        'what felt right about today, even briefly?',
        'where did you lose yourself to other people\'s pace?',
        'what are you carrying into tomorrow that wants to stay here?',
      ],
    },
    {
      type: 'confrontation',
      title: 'you skipped lunch again.',
      body: 'three of the last five days. the pattern is too clean to be accidental. you eat when the day is over, not when your body needs it.',
      ask: "want me to hold a 1:15pm block tomorrow that isn't negotiable?",
    },
    { type: 'footer', text: "I'm here if you want to talk before bed" },
  ],
};
