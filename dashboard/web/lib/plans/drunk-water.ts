import type { DashboardPlan } from '../plan';

/**
 * The "drunk-water" fixture — Aarav had a heavy night yesterday and Donna
 * leads today with a tracker-starter (water), reminders to drink + nap,
 * and a relationship card to ping Luca about being late. This is the
 * worked example from the spec: internal observation -> tracker spawn ->
 * dashboard composes a coherent recovery day.
 */
export const drunkWaterPlan: DashboardPlan = {
  id: 'plan:aarav:2026-04-26:drunk-water',
  generatedAt: '2026-04-26T08:15:00+05:30',
  user: { name: 'Aarav', initial: 'A' },
  thesis: 'rough night. water first. push the rest by a day.',
  moment: 'morning',
  blocks: [
    {
      type: 'hero',
      date: 'Saturday · 26 April',
      greeting: 'Take it easy, Aarav.',
      subtext: 'Mumbai · 28° · soft light, slow start',
      illustration: 'mumbai',
    },
    {
      type: 'witness',
      observation: 'last night was heavy. you texted me at 23:42.',
      source: "yesterday's chat",
    },
    {
      type: 'tracker-starter',
      title: 'today, just one thing',
      rationale: '"bro had way too much tonight. losing it." — you said this last night.',
      trackerName: 'water',
      cta: 'start',
      icon: 'drop',
      action: { v: 'start_tracker', name: 'water' },
    },
    {
      type: 'reminders',
      title: 'today, paced',
      items: [
        {
          id: 'r1',
          at: 'now',
          label: 'electrolytes + a glass of water',
          meta: 'before coffee',
          action: { v: 'mark_reminder_done', reminderId: 'r1' },
        },
        {
          id: 'r2',
          at: '11:00 am',
          label: 'second glass + paracetamol if you need it',
          action: { v: 'mark_reminder_done', reminderId: 'r2' },
        },
        {
          id: 'r3',
          at: '2:00 pm',
          label: 'a 30-min nap, blinds down',
          action: { v: 'mark_reminder_done', reminderId: 'r3' },
        },
      ],
    },
    {
      type: 'nudge-grid',
      title: 'easy wins',
      items: [
        {
          id: 'n1',
          title: 'Log a glass',
          meta: '0 of 8 today',
          cta: 'Log one',
          icon: 'drop',
          variant: 'moss',
          progress: 0,
          action: { v: 'quick_log', kind: 'water', payload: { glasses: 1 } },
        },
        {
          id: 'n2',
          title: 'Skip the gym',
          meta: 'I moved your 6pm slot',
          cta: 'Confirm',
          icon: 'leaf',
          variant: 'amber',
          action: { v: 'mark_reminder_done', reminderId: 'gym-skip' },
        },
        {
          id: 'n3',
          title: 'Push pitch prep',
          meta: 'Tomorrow morning has space',
          cta: 'Move it',
          icon: 'hourglass',
          variant: 'neutral',
          action: { v: 'reply_chip', intent: 'reschedule pitch prep to tomorrow' },
        },
        {
          id: 'n4',
          title: 'Tell Luca',
          meta: "He's expecting you at 10",
          cta: 'Yes, draft',
          icon: 'phone',
          variant: 'featured',
          action: { v: 'reply_chip', intent: 'tell luca i will be late' },
        },
      ],
    },
    {
      type: 'relationship',
      title: 'people on your mind',
      items: [
        {
          id: 'rel-luca',
          name: 'Luca',
          role: 'cofounder',
          lastTouch: 'expecting you at 10',
          nudge: 'tell him you slept in',
          initial: 'L',
          action: { v: 'open_relationship', personId: 'rel-luca' },
        },
      ],
    },
    {
      type: 'permission',
      title: 'rest is work today.',
      body: "you don't owe anyone a productive saturday. recover. tomorrow has space.",
    },
    { type: 'footer', text: "I'm here. tap to talk." },
  ],
  // Row-based composition (visual contract §4). Renderer walks rows when present.
  intro: {
    kicker: 'saturday · 26 april',
    greetingPrefix: 'take it easy, ',
    accent: 'aarav',
    greetingSuffix: '.',
    place: 'mumbai · 28° · soft light, slow start',
    illustrationId: 'mumbai',
  },
  rows: [
    {
      cols: [
        {
          size: 'two-thirds',
          block: {
            type: 'witness',
            observation: 'last night was heavy. you texted me at 23:42.',
            source: "yesterday's chat",
          },
        },
        {
          size: 'third',
          block: {
            type: 'tracker-starter',
            title: 'today, just one thing',
            rationale: '"bro had way too much tonight. losing it." — you said this last night.',
            trackerName: 'water',
            cta: 'start',
            icon: 'drop',
            action: { v: 'start_tracker', name: 'water' },
          },
        },
      ],
    },
    {
      title: 'today, paced',
      cols: [
        {
          size: 'full',
          block: {
            type: 'reminders',
            title: 'today, paced',
            items: [
              { id: 'r1', at: 'now', label: 'electrolytes + a glass of water', meta: 'before coffee', action: { v: 'mark_reminder_done', reminderId: 'r1' } },
              { id: 'r2', at: '11:00 am', label: 'second glass + paracetamol if you need it', action: { v: 'mark_reminder_done', reminderId: 'r2' } },
              { id: 'r3', at: '2:00 pm', label: 'a 30-min nap, blinds down', action: { v: 'mark_reminder_done', reminderId: 'r3' } },
            ],
          },
        },
      ],
    },
    {
      cols: [
        {
          size: 'half',
          block: {
            type: 'nudge-grid',
            title: 'easy wins',
            items: [
              { id: 'n1', title: 'Log a glass', meta: '0 of 8 today', cta: 'Log one', icon: 'drop', variant: 'moss', progress: 0, action: { v: 'quick_log', kind: 'water', payload: { glasses: 1 } } },
              { id: 'n2', title: 'Skip the gym', meta: 'I moved your 6pm slot', cta: 'Confirm', icon: 'leaf', variant: 'amber', action: { v: 'mark_reminder_done', reminderId: 'gym-skip' } },
              { id: 'n3', title: 'Push pitch prep', meta: 'Tomorrow morning has space', cta: 'Move it', icon: 'hourglass', variant: 'neutral', action: { v: 'reply_chip', intent: 'reschedule pitch prep to tomorrow' } },
              { id: 'n4', title: 'Tell Luca', meta: "He's expecting you at 10", cta: 'Yes, draft', icon: 'phone', variant: 'featured', action: { v: 'reply_chip', intent: 'tell luca i will be late' } },
            ],
          },
        },
        {
          size: 'half',
          block: {
            type: 'relationship',
            title: 'people on your mind',
            items: [
              { id: 'rel-luca', name: 'Luca', role: 'cofounder', lastTouch: 'expecting you at 10', nudge: 'tell him you slept in', initial: 'L', action: { v: 'open_relationship', personId: 'rel-luca' } },
            ],
          },
        },
      ],
    },
    {
      cols: [
        {
          size: 'full',
          block: {
            type: 'permission',
            title: 'rest is work today.',
            body: "you don't owe anyone a productive saturday. recover. tomorrow has space.",
          },
        },
      ],
    },
  ],
};
