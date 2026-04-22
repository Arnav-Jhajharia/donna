import type { DashboardPlan } from '../plan';

export const morningAaravPlan: DashboardPlan = {
  id: 'plan:aarav:2026-04-18:morning',
  generatedAt: '2026-04-18T07:30:00+05:30',
  user: { name: 'Aarav', initial: 'A' },
  thesis: 'today is about calling dad before it gets weirder.',
  moment: 'morning',
  blocks: [
    {
      type: 'hero',
      date: 'Friday · 18 April',
      greeting: 'Good morning, Aarav.',
      subtext: 'Mumbai · 29° · slight haze, cooler by the sea',
      illustration: 'mumbai',
    },
    {
      type: 'todo-list',
      title: 'Three I picked for you',
      items: [
        { id: 't1', label: 'Call your Dad back', meta: 'You told him "this week" on Tuesday', source: 'messages' },
        { id: 't2', label: 'Send Priya the onboarding deck', meta: 'You promised Friday', source: 'mail', done: true },
        { id: 't3', label: "Pick up the frame at Oscar's", meta: 'Ready since yesterday', source: 'calendar' },
      ],
    },
    {
      type: 'tracker-grid',
      title: 'Your body, your money',
      items: [
        { id: 'tr-cal',   title: 'Calories', value: '1,240', unit: 'of 2,200 today', sub: 'Chicken bowl at lunch', progress: 0.56, icon: 'flame', tone: 'amber', tint: 'amber' },
        { id: 'tr-spend', title: 'Spend',    value: '₹ 420', unit: 'today · ₹ 8.2k this week', sub: 'Uber, coffee, Zomato', progress: 0.30, icon: 'rupee', tone: 'ink',   tint: 'paper' },
      ],
    },
    {
      type: 'nudge-grid',
      title: 'A few small things',
      items: [
        { id: 'n1', title: 'Call Dad',         meta: "It's been six days",         cta: 'Remind me at six', icon: 'phone',  variant: 'neutral' },
        { id: 'n2', title: 'Drink a glass',    meta: '2 of 8 so far today',         cta: 'Log one',          icon: 'drop',   variant: 'moss', progress: 0.25 },
        { id: 'n3', title: 'Log lunch',        meta: 'You usually eat by 1:30',     cta: 'Quick log',        icon: 'bowl',   variant: 'amber' },
        { id: 'n4', title: 'Send the peonies', meta: "Maya's sister lands at 4:10", cta: 'Yes, order',       icon: 'flower', variant: 'featured' },
      ],
    },
    { type: 'footer', text: "I'm listening · tap to talk" },
  ],
};
