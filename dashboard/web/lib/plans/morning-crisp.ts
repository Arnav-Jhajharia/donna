import type { DashboardPlan } from '../plan';

/**
 * Morning, user woke well, calendar is reasonable.
 * Thesis: the day has a clear lead. Point at it. Don't stack.
 */
export const morningCrispPlan: DashboardPlan = {
  id: 'plan:aarav:2026-04-22:morning-crisp',
  generatedAt: '2026-04-22T07:10:00+05:30',
  user: { name: 'Aarav', initial: 'A' },
  thesis: 'today is about calling dad before it gets weirder.',
  moment: 'morning',
  blocks: [
    // #01 intro — locked. mumbai illustration, "morning, aarav.", weather.
    {
      type: 'hero',
      date: 'Wednesday · 22 April',
      greeting: 'Morning, Aarav.',
      subtext: 'Mumbai · 28° · haze lifting by ten',
      illustration: 'mumbai',
    },
    // #02 note · editorial — donna's voice on the lead. one breath.
    {
      type: 'note',
      kind: 'editorial',
      body: "call dad before it gets weirder. you told him 'this week' on tuesday — it's been six days.",
      actions: { primary: 'noted', secondary: 'remind me at six', tertiary: 'skip' },
    },
    // #03 footer · italic — warm sign-off, not a status line.
    {
      type: 'footer',
      kind: 'italic',
      text: "the day is yours.",
    },
  ],
};
