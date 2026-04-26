import type { DashboardPlan } from '../plan';

/**
 * The "busy-pitch" fixture — Antler demo day in 16 hours. Donna leads with
 * a confrontation thesis (the deck still feels flat) and surfaces curated
 * news + relationship context. High signal, low noise.
 */
export const busyPitchPlan: DashboardPlan = {
  id: 'plan:aarav:2026-04-26:busy-pitch',
  generatedAt: '2026-04-26T09:05:00+05:30',
  user: { name: 'Aarav', initial: 'A' },
  thesis: 'antler is in 16 hours. the deck still feels flat.',
  moment: 'morning',
  blocks: [
    {
      type: 'hero',
      date: 'Saturday · 26 April',
      greeting: 'Good morning, Aarav.',
      subtext: 'Mumbai · 30° · clear, dry',
      illustration: 'mumbai',
    },
    {
      type: 'thesis',
      sentence: 'antler is in 16 hours. the deck still feels flat. fix the hook first.',
      kicker: 'right now',
    },
    {
      type: 'reminders',
      title: 'between now and 1 am',
      items: [
        {
          id: 'r1',
          at: '10:30 am',
          label: 'lock the hook slide with Luca',
          meta: '20 min, in person',
          action: { v: 'mark_reminder_done', reminderId: 'r1' },
        },
        {
          id: 'r2',
          at: '2:00 pm',
          label: 'rehearse cold opens — three takes',
          action: { v: 'mark_reminder_done', reminderId: 'r2' },
        },
        {
          id: 'r3',
          at: '6:00 pm',
          label: 'one last pass on numbers slide',
          action: { v: 'mark_reminder_done', reminderId: 'r3' },
        },
        {
          id: 'r4',
          at: '11:00 pm',
          label: 'phone away. eight hours of sleep is the move.',
          action: { v: 'mark_reminder_done', reminderId: 'r4' },
        },
      ],
    },
    {
      type: 'todo-list',
      title: 'three I picked for you',
      items: [
        {
          id: 't1',
          label: 'rewrite the first 30 seconds',
          meta: 'you said the hook felt flat last night',
          source: 'chat',
          action: { v: 'complete_pick', pickId: 't1' },
        },
        {
          id: 't2',
          label: 'send Luca your slide order',
          meta: 'you promised by 10 am',
          source: 'mail',
          action: { v: 'complete_pick', pickId: 't2' },
        },
        {
          id: 't3',
          label: 'eat actual lunch',
          meta: 'you skipped twice this week',
          source: 'tracker',
          action: { v: 'complete_pick', pickId: 't3' },
        },
      ],
    },
    {
      type: 'news-brief',
      title: 'three things while you work',
      items: [
        {
          id: 'nb1',
          headline: 'antler nyc q1 batch — three demo decks that actually opened with a story.',
          source: 'antler.co',
          tag: 'reference',
          url: 'https://antler.co',
          action: { v: 'open_news', newsId: 'nb1' },
        },
        {
          id: 'nb2',
          headline: 'the cold open template founders keep reusing — it works because the founder is in frame.',
          source: 'open vc',
          tag: 'today',
          action: { v: 'open_news', newsId: 'nb2' },
        },
      ],
    },
    {
      type: 'relationship',
      title: 'people in this loop',
      items: [
        {
          id: 'rel-luca',
          name: 'Luca',
          role: 'cofounder',
          lastTouch: 'lunch yesterday · waiting on slide order',
          nudge: 'send him slides by 10',
          initial: 'L',
          action: { v: 'open_relationship', personId: 'rel-luca' },
        },
        {
          id: 'rel-priya',
          name: 'Priya',
          role: 'investor intro',
          lastTouch: 'asked for a follow-up after antler',
          nudge: "don't ghost. one line tomorrow.",
          initial: 'P',
          action: { v: 'open_relationship', personId: 'rel-priya' },
        },
      ],
    },
    {
      type: 'tracker-grid',
      title: 'body & money — light read',
      items: [
        {
          id: 'tr-cal',
          title: 'Calories',
          value: '420',
          unit: 'of 2,200 today',
          sub: 'just coffee · eat lunch',
          progress: 0.19,
          icon: 'flame',
          tone: 'amber',
          tint: 'amber',
          action: { v: 'open_tracker', tracker: 'calories' },
        },
        {
          id: 'tr-sleep',
          title: 'Sleep',
          value: '5h 40m',
          unit: 'last night · target 7h',
          sub: 'short. tonight matters.',
          progress: 0.81,
          icon: 'moon',
          tone: 'rust',
          tint: 'rust',
          action: { v: 'open_tracker', tracker: 'sleep' },
        },
      ],
    },
    {
      type: 'whisper',
      kicker: 'a note from me',
      body: 'the deck is closer than it feels. the hook is the only thing left. fix that, the rest holds.',
      level: 'subtle',
    },
    { type: 'footer', text: "I'm here. tap to talk." },
  ],
};
