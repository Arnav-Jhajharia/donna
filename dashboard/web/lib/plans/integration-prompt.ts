import type { DashboardPlan } from '../plan';

/**
 * The "integration-prompt" fixture — Donna has noticed enough that she
 * thinks connecting Gmail would unlock a real upgrade. Surfaced as a
 * permission-style card with a tracker-starter and a single CTA. This is
 * what onboarding looks like AFTER the user has been around a few days.
 */
export const integrationPromptPlan: DashboardPlan = {
  id: 'plan:aarav:2026-04-26:integration-prompt',
  generatedAt: '2026-04-26T10:00:00+05:30',
  user: { name: 'Aarav', initial: 'A' },
  thesis: 'connect gmail and I can stop guessing about your week.',
  moment: 'midday',
  blocks: [
    {
      type: 'hero',
      date: 'Saturday · 26 April',
      greeting: 'Quick one, Aarav.',
      subtext: 'Mumbai · 30° · light winds',
      illustration: 'mumbai',
    },
    {
      type: 'witness',
      observation: "you've forwarded me three threads this week. let me just read mail.",
      source: 'last 7 days',
    },
    {
      type: 'permission',
      title: 'connect gmail.',
      body: 'i only read what mentions you, and only the parts about you. you can disconnect anytime.',
      action: { v: 'connect_integration', provider: 'gmail' },
    },
    {
      type: 'nudge-grid',
      title: 'or skip and tell me directly',
      items: [
        {
          id: 'n1',
          title: 'Tell me about Priya',
          meta: 'who is she to you?',
          cta: 'Quick note',
          icon: 'pencil',
          variant: 'neutral',
          action: { v: 'reply_chip', intent: 'who is priya' },
        },
        {
          id: 'n2',
          title: 'What are you tracking?',
          meta: '3 trackers active',
          cta: 'Show me',
          icon: 'eye',
          variant: 'moss',
          action: { v: 'open_tracker', tracker: 'all' },
        },
        {
          id: 'n3',
          title: 'Add a person',
          meta: "I'll start watching them",
          cta: 'Add',
          icon: 'sparkles',
          variant: 'amber',
          action: { v: 'reply_chip', intent: 'add a person to my graph' },
        },
        {
          id: 'n4',
          title: 'Show me what you know',
          meta: 'living profile',
          cta: 'Open',
          icon: 'sparkles',
          variant: 'featured',
          action: { v: 'reply_chip', intent: 'show me my living profile' },
        },
      ],
    },
    { type: 'footer', text: "I'm patient. only when you're ready." },
  ],
};
