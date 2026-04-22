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
    {
      type: 'hero',
      date: 'Wednesday · 22 April',
      greeting: 'Morning, Aarav.',
      subtext: 'Mumbai · 28° · haze lifting by ten',
      illustration: 'mumbai',
    },
    {
      type: 'thesis',
      kicker: 'today',
      sentence: 'call dad before it gets weirder.',
    },
    {
      type: 'witness',
      observation: "you told him 'this week' on tuesday. it's been six days. you've mentioned it in three chats since.",
      source: "tuesday's thread",
    },
    {
      type: 'calendar-shape',
      title: "today's shape",
      shapeRead: 'light morning, dense 2–5pm, free after',
      slots: [
        { id: 's1', at: '09:30', label: 'standup',                duration: 30, kind: 'meeting' },
        { id: 's2', at: '10:00', label: 'deep work',              duration: 120, kind: 'focus' },
        { id: 's3', at: '12:00', label: 'lunch',                  duration: 60, kind: 'break' },
        { id: 's4', at: '14:00', label: 'priya — onboarding',     duration: 45, kind: 'meeting' },
        { id: 's5', at: '15:00', label: 'design review',          duration: 60, kind: 'meeting' },
        { id: 's6', at: '16:00', label: 'investor follow-up',     duration: 30, kind: 'meeting' },
        { id: 's7', at: '18:00', label: 'call dad',               duration: 30, kind: 'personal' },
      ],
    },
    {
      type: 'nudge-grid',
      title: 'a few small things',
      items: [
        { id: 'n1', title: 'Call Dad',         meta: "It's been six days",         cta: 'Remind me at six', icon: 'phone',  variant: 'featured' },
        { id: 'n2', title: 'Drink a glass',    meta: '0 of 8 so far today',         cta: 'Log one',          icon: 'drop',   variant: 'moss', progress: 0 },
        { id: 'n3', title: 'Log lunch',        meta: 'You usually eat by 1:30',     cta: 'Quick log',        icon: 'bowl',   variant: 'amber' },
        { id: 'n4', title: 'Pick up frame',    meta: "Ready at Oscar's since tuesday", cta: 'Add to the 6pm walk', icon: 'flower', variant: 'neutral' },
      ],
    },
    { type: 'footer', text: "I'm listening · tap to talk" },
  ],
};
