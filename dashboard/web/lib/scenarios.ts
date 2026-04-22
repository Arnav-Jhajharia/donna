import type { MomentContext } from './generator';

/**
 * Fixtures that simulate what the memory layer would return in different
 * user states. Used by the generator demo to show live composition.
 */

const user = { name: 'Aarav', initial: 'A' };

const standardTrackers = [
  { id: 'tr-cal',   title: 'Calories', value: '820',   unit: 'of 2,200',     sub: 'Idli at breakfast', progress: 0.37, icon: 'flame'  as const, tone: 'amber' as const, tint: 'amber'  as const },
  { id: 'tr-water', title: 'Water',    value: '3',     unit: 'of 8 glasses', sub: 'keep going',         progress: 0.37, icon: 'drop'   as const, tone: 'moss'  as const, tint: 'moss'   as const },
  { id: 'tr-spend', title: 'Spend',    value: '₹ 280', unit: 'today',        sub: 'coffee · auto',      progress: 0.20, icon: 'rupee'  as const, tone: 'ink'   as const, tint: 'paper'  as const },
];

const standardCalendar = [
  { id: 's1', at: '09:30', label: 'standup',            duration: 30,  kind: 'meeting'  as const },
  { id: 's2', at: '10:00', label: 'deep work',          duration: 120, kind: 'focus'    as const },
  { id: 's3', at: '12:00', label: 'lunch',              duration: 60,  kind: 'break'    as const },
  { id: 's4', at: '14:00', label: 'priya onboarding',   duration: 45,  kind: 'meeting'  as const },
  { id: 's5', at: '15:00', label: 'design review',      duration: 60,  kind: 'meeting'  as const },
  { id: 's6', at: '18:00', label: 'call dad',           duration: 30,  kind: 'personal' as const },
];

const dadLoop = { id: 'l1', title: 'Call Dad',  age: '6 days', commitment: "you said 'this week' on tuesday" };
const frameLoop = { id: 'l2', title: 'Pick up frame', age: '2 days', commitment: "ready at Oscar's since tuesday" };
const deckLoop = { id: 'l3', title: 'Send deck to Priya', age: 'by friday', commitment: 'promised friday EOD' };

export interface Scenario {
  id: string;
  label: string;
  description: string;
  ctx: MomentContext;
}

export const SCENARIOS: Scenario[] = [
  {
    id: 'morning-crisp',
    label: 'morning · crisp',
    description: 'Slept well, calendar is reasonable, one aging loop',
    ctx: {
      user,
      now: new Date('2026-04-22T07:10:00+05:30'),
      energy: 0.72,
      mood: 'steady',
      moodBasis: 'you slept seven hours. you started the day without checking slack.',
      yesterdayWasHard: false,
      openLoops: [dadLoop, frameLoop],
      trackers: standardTrackers,
      calendarSlots: standardCalendar,
      isSpiralling: false,
    },
  },
  {
    id: 'morning-recovery',
    label: 'morning · recovery',
    description: 'Rough yesterday, low energy, no confrontation today',
    ctx: {
      user,
      now: new Date('2026-04-22T08:20:00+05:30'),
      energy: 0.28,
      mood: 'tender',
      moodBasis: 'you slept four hours. you were quiet in chat after nine.',
      yesterdayWasHard: true,
      openLoops: [deckLoop],
      trackers: [],
      calendarSlots: [],
      isSpiralling: false,
    },
  },
  {
    id: 'midday',
    label: 'midday · check-in',
    description: 'Short, functional, trackers + open loops',
    ctx: {
      user,
      now: new Date('2026-04-22T13:05:00+05:30'),
      energy: 0.58,
      mood: 'steady',
      moodBasis: 'you ate something. you answered priya.',
      yesterdayWasHard: false,
      openLoops: [dadLoop],
      trackers: standardTrackers,
      calendarSlots: standardCalendar.slice(3),
      isSpiralling: false,
    },
  },
  {
    id: 'evening',
    label: 'evening · reflection',
    description: 'Day is cooked, Donna shifts to reflective mode, one pattern to flag',
    ctx: {
      user,
      now: new Date('2026-04-22T21:15:00+05:30'),
      energy: 0.42,
      mood: 'scattered',
      moodBasis: 'you checked in with me seven times. most were mid-meeting.',
      yesterdayWasHard: false,
      openLoops: [dadLoop],
      trackers: [],
      calendarSlots: [],
      isSpiralling: false,
      patternToConfront: {
        title: 'you skipped lunch again.',
        body: 'three of the last five days. the pattern is too clean to be accidental.',
        ask: "want me to hold a 1:15pm block tomorrow that isn't negotiable?",
      },
    },
  },
  {
    id: 'celebration',
    label: 'celebration',
    description: 'Dad call just happened. Lead with the landing.',
    ctx: {
      user,
      now: new Date('2026-04-22T19:42:00+05:30'),
      energy: 0.64,
      mood: 'bright',
      moodBasis: 'you sounded lighter after the call.',
      yesterdayWasHard: false,
      openLoops: [],
      trackers: [],
      calendarSlots: [],
      isSpiralling: false,
      recentWin: {
        title: 'the dad call',
        body: "you'd been carrying this since tuesday. you told me four times you'd do it and didn't. tonight you did.",
        badge: '6-day loop · closed',
      },
    },
  },
  {
    id: 'late-spiral',
    label: 'late · spiralling',
    description: 'Past midnight, user keeps reopening the dashboard',
    ctx: {
      user,
      now: new Date('2026-04-23T00:48:00+05:30'),
      energy: 0.18,
      mood: 'restless',
      moodBasis: 'fourth open in the last hour.',
      yesterdayWasHard: false,
      openLoops: [dadLoop, frameLoop],
      trackers: [],
      calendarSlots: [],
      isSpiralling: true,
    },
  },
];
