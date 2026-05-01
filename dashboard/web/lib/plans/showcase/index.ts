/**
 * Showcase — 18 dashboard plans, 100% catalogue lego.
 *
 * Every body block uses an archetype ported from the design specimen:
 *   #02 note  · #03 footer · #04 tracker · #05 watch · #06 brief
 *   #07 prep  · #08 schedule · #09 streak · #10 person · #11 reminder
 *   #12 quick-log · #13 pick · #14 offer · #15 draft · #16 decision
 *   #17 confrontation · #18 reflection · #19 open-loop · #20 permission · #21 read
 *
 * Composition rules (from the catalogue):
 *   • exactly 3–5 blocks per plan (intro + 1–3 mid + footer)
 *   • one rust per screen, max
 *   • moss reserved for streak / quiet wins
 *   • oxblood reserved for confrontation, max one per plan
 *   • celebration and confrontation never co-occur
 */

import type { DashboardPlan } from '../../plan';

const userAarav = { name: 'Aarav', initial: 'A' };

// ─── 01 · morning · clear ─────────────────────────────────────────────────
export const sc01: DashboardPlan = {
  id: 'sc:01-morning-clear',
  generatedAt: '2026-04-22T07:10:00+05:30',
  user: userAarav,
  thesis: 'one lead. nothing else.',
  moment: 'morning',
  blocks: [
    { type: 'hero', date: 'Wednesday · 22 April', greeting: 'Morning, Aarav.', subtext: 'Mumbai · 28° · haze lifting by ten', illustration: 'mumbai' },
    { type: 'note', kind: 'editorial', body: "call dad before it gets weirder. you told him 'this week' on tuesday — it's been six days.", actions: { primary: 'noted', secondary: 'remind me at six', tertiary: 'skip' } },
    { type: 'footer', kind: 'italic', text: 'the day is yours.' },
  ],
};

// ─── 02 · morning · the canonical pair ────────────────────────────────────
export const sc02: DashboardPlan = {
  id: 'sc:02-morning-pair',
  generatedAt: '2026-04-23T07:10:00+05:30',
  user: userAarav,
  thesis: 'a steady morning. body and money on a glance.',
  moment: 'morning',
  blocks: [
    { type: 'hero', date: 'Friday · 24 April', greeting: 'Morning, Aarav.', subtext: 'Mumbai · 24° · clear', illustration: 'mumbai' },
    {
      type: 'c-tracker', variant: 'pair', title: 'your body, your money',
      items: [
        { label: 'Calories', value: '1,240', unit: 'of 2,200 today', detail: 'Chicken bowl at lunch', progress: 0.56, icon: 'flame', tint: 'amber' },
        { label: 'Spend', value: '₹ 420', unit: 'today · ₹ 8.2k this week', detail: 'Uber, coffee, Zomato', progress: 0.30, icon: 'rupee', tint: 'paper' },
      ],
    },
    { type: 'footer', kind: 'mark', text: '' },
  ],
};

// ─── 03 · morning · trackers borderless ───────────────────────────────────
export const sc03: DashboardPlan = {
  id: 'sc:03-morning-borderless',
  generatedAt: '2026-04-24T07:10:00+05:30',
  user: userAarav,
  thesis: 'three numbers, no chrome.',
  moment: 'morning',
  blocks: [
    { type: 'hero', date: 'Friday · 24 April', greeting: 'Morning, Aarav.', subtext: 'Mumbai · 25° · breeze from the sea', illustration: 'mumbai' },
    {
      type: 'c-tracker', variant: 'borderless', title: "what i'm tracking",
      items: [
        { label: 'Hydration', value: '2', unit: 'of 8 glasses · steady', progress: 0.25, icon: 'drop', tint: 'rust' },
        { label: 'Calories', value: '1,240', unit: 'of 2,200 today', progress: 0.56, icon: 'flame', tint: 'amber' },
        { label: 'Spend', value: '₹420', unit: 'today · ₹8.2k this week', progress: 0.30, icon: 'rupee', tint: 'paper' },
      ],
    },
    { type: 'footer', kind: 'caps', text: 'tap to talk' },
  ],
};

// ─── 04 · morning · hero tracker ──────────────────────────────────────────
export const sc04: DashboardPlan = {
  id: 'sc:04-hero-tracker',
  generatedAt: '2026-04-22T08:00:00+05:30',
  user: userAarav,
  thesis: 'one number is the story today.',
  moment: 'morning',
  blocks: [
    { type: 'hero', date: 'Wednesday · 22 April', greeting: 'Morning, Aarav.', subtext: 'Mumbai · 28° · haze', illustration: 'mumbai' },
    {
      type: 'c-tracker', variant: 'hero', title: 'Hydration', right: 'today',
      items: [{ label: 'glasses', value: '2/8', unit: 'glasses', detail: 'one before nine, one on the walk', progress: 0.25, icon: 'drop', tint: 'rust' }],
      history: [4, 6, 7, 5, 3, 8, 2],
      todayIndex: 6,
      weekLabels: ['s', 'm', 't', 'w', 't', 'f', 's'],
    },
    { type: 'footer', kind: 'italic', text: 'the day is yours.' },
  ],
};

// ─── 05 · watching · the wire ─────────────────────────────────────────────
export const sc05: DashboardPlan = {
  id: 'sc:05-watch-wire',
  generatedAt: '2026-04-23T09:42:00+05:30',
  user: userAarav,
  thesis: 'three things i have eyes on for you.',
  moment: 'morning',
  blocks: [
    { type: 'hero', date: 'Thursday · 23 April', greeting: 'Morning, Aarav.', subtext: 'Mumbai · 27° · still', illustration: 'mumbai' },
    {
      type: 'c-watch', variant: 'rows', title: "what i've got eyes on",
      items: [
        { subject: 'Adobe (ADBE)', signal: 'up 2.4% on AI partnership rumour', delta: '↑ 2.4%', up: true, at: '9:42am' },
        { subject: 'Poke launch', signal: "andrew posted the demo, 14k likes in three hours", at: '11:08' },
        { subject: 'Figma config invites', signal: 'caps confirmed, 2 of yours pending', at: 'yesterday' },
      ],
    },
    { type: 'footer', kind: 'caps', text: 'tap to talk' },
  ],
};

// ─── 06 · friday brief ────────────────────────────────────────────────────
export const sc06: DashboardPlan = {
  id: 'sc:06-friday-brief',
  generatedAt: '2026-04-24T09:00:00+05:30',
  user: userAarav,
  thesis: 'the weekly is in.',
  moment: 'morning',
  blocks: [
    { type: 'hero', date: 'Friday · 24 April', greeting: 'Morning, Aarav.', subtext: 'Mumbai · 26° · clear', illustration: 'mumbai' },
    {
      type: 'c-brief', variant: 'newsstand',
      cadenceLabel: 'brief · weekly', fireWindow: 'fires fri 9am',
      title: 'Design sector, week of', highlight: '15 April',
      teaser: "figma's enterprise rev grew 40%. canva launched dev tools. pitch raised again.",
      chips: ['figma', 'canva', 'pitch', 'linear'],
    },
    { type: 'footer', kind: 'italic', text: 'go.' },
  ],
};

// ─── 07 · pre-meeting prep ────────────────────────────────────────────────
export const sc07: DashboardPlan = {
  id: 'sc:07-prep-meeting',
  generatedAt: '2026-04-22T13:00:00+05:30',
  user: userAarav,
  thesis: 'the principal call. four things, two ready.',
  moment: 'midday',
  blocks: [
    { type: 'hero', date: 'Wednesday · 22 April', greeting: 'Afternoon, Aarav.', subtext: 'Mumbai · 30° · humid', illustration: 'mumbai' },
    {
      type: 'c-prep', variant: 'inline', eyebrow: 'prep · tomorrow 14:00',
      title: 'the principal call',
      items: [
        { label: 'the deck — last revision, you opened it tuesday', done: true },
        { label: "the question about runway — you don't have one yet", done: false },
        { label: 'two anecdotes from the priya call', done: false },
        { label: 'a glass of water before you join', done: false },
      ],
    },
    { type: 'footer', kind: 'caps', text: 'tap to talk' },
  ],
};

// ─── 08 · today's shape ───────────────────────────────────────────────────
export const sc08: DashboardPlan = {
  id: 'sc:08-shape-day',
  generatedAt: '2026-04-21T07:00:00+05:30',
  user: userAarav,
  thesis: 'four blocks. an hour clear at four.',
  moment: 'morning',
  blocks: [
    { type: 'hero', date: 'Tuesday · 21 April', greeting: 'Morning, Aarav.', subtext: 'Mumbai · 28° · clear', illustration: 'mumbai' },
    {
      type: 'c-schedule', variant: 'column', title: "today's shape", right: '4 blocks',
      slots: [
        { at: '10:30', label: 'standup',         duration: '30m',  kind: 'meeting' },
        { at: '12:00', label: 'focus · pricing', duration: '90m',  kind: 'focus' },
        { at: '15:00', label: 'coffee · sajith', duration: '45m',  kind: 'meeting' },
        { at: '19:30', label: 'run · marine drive', duration: '40m', kind: 'personal' },
      ],
    },
    { type: 'footer', kind: 'italic', text: 'go.' },
  ],
};

// ─── 09 · day at a glance (strip) ─────────────────────────────────────────
export const sc09: DashboardPlan = {
  id: 'sc:09-day-strip',
  generatedAt: '2026-04-23T08:00:00+05:30',
  user: userAarav,
  thesis: 'deep focus 12–13:30.',
  moment: 'morning',
  blocks: [
    { type: 'hero', date: 'Thursday · 23 April', greeting: 'Morning, Aarav.', subtext: 'Mumbai · 27° · partly cloudy', illustration: 'mumbai' },
    {
      type: 'c-schedule', variant: 'strip', range: '9 → 21',
      blocks: [
        { x: 18, w: 7, kind: 'focus' },
        { x: 30, w: 5, kind: 'meeting' },
        { x: 43, w: 14, kind: 'focus' },
        { x: 62, w: 8, kind: 'meeting' },
        { x: 78, w: 6, kind: 'personal' },
      ],
      ticks: ['9', '12', '15', '18', '21'],
      glance: 'deep focus 12–13:30, then sajith. you have an hour clear at 16.',
    },
    { type: 'footer', kind: 'caps', text: 'tap to talk' },
  ],
};

// ─── 10 · streak (badge) ──────────────────────────────────────────────────
export const sc10: DashboardPlan = {
  id: 'sc:10-streak-badge',
  generatedAt: '2026-04-25T08:00:00+05:30',
  user: userAarav,
  thesis: 'a clean week. you sleep better when you walk.',
  moment: 'morning',
  blocks: [
    { type: 'hero', date: 'Saturday · 25 April', greeting: 'Morning, Aarav.', subtext: 'Mumbai · 26° · sun', illustration: 'mumbai' },
    {
      type: 'c-streak', variant: 'badge', count: 7,
      eyebrow: 'days · walking',
      body: 'a clean week. you sleep better when you walk.',
    },
    {
      type: 'c-person', variant: 'list', title: "people i've been thinking of",
      items: [
        { name: 'Kabir Mehta', role: 'college, in town one night', ago: '4 mo', nudge: 'he lands at 6, dinner free?' },
        { name: 'Priya Shah', role: 'co-founder', ago: 'today', nudge: "she's waiting on the deck" },
      ],
    },
    { type: 'footer', kind: 'mark', text: '' },
  ],
};

// ─── 11 · person hero (kabir's in town) ───────────────────────────────────
export const sc11: DashboardPlan = {
  id: 'sc:11-person-hero',
  generatedAt: '2026-04-22T17:00:00+05:30',
  user: userAarav,
  thesis: "kabir lands at six.",
  moment: 'evening',
  blocks: [
    { type: 'hero', date: 'Wednesday · 22 April', greeting: 'Evening, Aarav.', subtext: 'Mumbai · 27° · cooler', illustration: 'mumbai' },
    {
      type: 'c-person', variant: 'hero',
      heroName: 'Kabir Mehta',
      heroEyebrow: 'college · in town tonight',
      heroBody: "he lands at six. you haven't seen him in four months. the table at trishna takes three hours' notice.",
      ctaPrimary: 'draft a thought',
      ctaSecondary: 'open thread',
    },
    { type: 'footer', kind: 'italic', text: 'go.' },
  ],
};

// ─── 12 · reminder · single pill ──────────────────────────────────────────
export const sc12: DashboardPlan = {
  id: 'sc:12-reminder-pill',
  generatedAt: '2026-04-23T11:30:00+05:30',
  user: userAarav,
  thesis: 'one ping. that is it.',
  moment: 'midday',
  blocks: [
    { type: 'hero', date: 'Thursday · 23 April', greeting: 'Late morning, Aarav.', subtext: 'Mumbai · 29° · sun', illustration: 'mumbai' },
    {
      type: 'c-reminder', variant: 'pill',
      items: [{ label: 'drink a glass', at: 'now' }],
    },
    {
      type: 'c-quicklog', variant: 'chips',
      chips: [
        { label: 'had a coffee', icon: 'coffee' },
        { label: 'logged a glass', icon: 'drop' },
        { label: 'paid lunch', icon: 'rupee' },
      ],
    },
    { type: 'footer', kind: 'caps', text: 'tap to talk' },
  ],
};

// ─── 13 · reminders editorial + tray ──────────────────────────────────────
export const sc13: DashboardPlan = {
  id: 'sc:13-reminder-tray',
  generatedAt: '2026-04-22T11:00:00+05:30',
  user: userAarav,
  thesis: 'three small pings, two left.',
  moment: 'midday',
  blocks: [
    { type: 'hero', date: 'Wednesday · 22 April', greeting: 'Late morning, Aarav.', subtext: 'Mumbai · 30° · close', illustration: 'mumbai' },
    {
      type: 'c-reminder', variant: 'editorial', title: 'three small pings', right: '2 left',
      items: [
        { label: 'drink a glass', at: 'now' },
        { label: 'leave for the eye doctor', at: 'in 25 min' },
        { label: 'send the peonies confirmation', at: '11:00', done: true },
      ],
    },
    {
      type: 'c-quicklog', variant: 'tray',
      chips: [
        { label: 'coffee', icon: 'coffee', tint: 'amber' },
        { label: 'glass', icon: 'drop', tint: 'rust' },
        { label: 'lunch', icon: 'bowl', tint: 'moss' },
      ],
    },
    { type: 'footer', kind: 'caps', text: 'tap to talk' },
  ],
};

// ─── 14 · pick (read) ─────────────────────────────────────────────────────
export const sc14: DashboardPlan = {
  id: 'sc:14-pick-read',
  generatedAt: '2026-04-26T09:30:00+05:30',
  user: userAarav,
  thesis: "i found a book.",
  moment: 'morning',
  blocks: [
    { type: 'hero', date: 'Sunday · 26 April', greeting: 'Morning, Aarav.', subtext: 'Mumbai · 25° · soft sun', illustration: 'mumbai' },
    {
      type: 'c-pick', variant: 'editorial', kind: 'read',
      title: 'Finite and Infinite Games',
      body: "james carse. you'll like part two — it's about the game you don't end.",
    },
    {
      type: 'c-read', variant: 'index',
      items: [
        { headline: 'the new indian middle class is online before it eats', source: 'The Ken', tag: 'essay' },
        { headline: 'why nobody can finish a long paragraph anymore', source: 'The Atlantic', tag: 'culture' },
        { headline: 'a new chip from a small company in chennai', source: 'The Hindu', tag: 'tech' },
      ],
    },
    { type: 'footer', kind: 'italic', text: 'rest.' },
  ],
};

// ─── 15 · the offer (rust hero) ───────────────────────────────────────────
export const sc15: DashboardPlan = {
  id: 'sc:15-offer-hero',
  generatedAt: '2026-04-25T08:00:00+05:30',
  user: userAarav,
  thesis: 'let me track your sleep.',
  moment: 'morning',
  blocks: [
    { type: 'hero', date: 'Saturday · 25 April', greeting: 'Morning, Aarav.', subtext: 'Mumbai · 24° · cool', illustration: 'mumbai' },
    {
      type: 'c-offer', variant: 'hero',
      eyebrow: 'offer',
      title: 'let me track your sleep',
      rationale: 'your week ran on six hours. i can run it light — phone-only, no wearable.',
      ctaAccept: 'start tracking',
      ctaDismiss: 'not now',
    },
    { type: 'footer', kind: 'caps', text: 'tap to talk' },
  ],
};

// ─── 16 · the draft (letter) ──────────────────────────────────────────────
export const sc16: DashboardPlan = {
  id: 'sc:16-draft-letter',
  generatedAt: '2026-04-24T16:00:00+05:30',
  user: userAarav,
  thesis: "ready when you are.",
  moment: 'evening',
  blocks: [
    { type: 'hero', date: 'Friday · 24 April', greeting: 'Afternoon, Aarav.', subtext: 'Mumbai · 28° · clear', illustration: 'mumbai' },
    {
      type: 'c-draft', variant: 'letter',
      recipient: 'luca', subject: 're: the offer',
      preview: 'thanks for sending this through. i want to sit with it over the weekend and reply monday morning.',
    },
    {
      type: 'c-decision', variant: 'tiles',
      question: "tomorrow's lunch?",
      options: [
        { label: 'Britannia', hint: 'usual' },
        { label: 'Bombay Canteen', hint: 'closer' },
        { label: 'home', hint: 'rest' },
      ],
    },
    { type: 'footer', kind: 'italic', text: 'sleep well.' },
  ],
};

// ─── 17 · confront + reflection (the hard truth) ─────────────────────────
export const sc17: DashboardPlan = {
  id: 'sc:17-confront-night',
  generatedAt: '2026-04-25T21:41:00+05:30',
  user: userAarav,
  thesis: "you're not avoiding him. you're avoiding the conversation.",
  moment: 'evening',
  blocks: [
    { type: 'hero', date: 'Saturday · 9:41 pm', greeting: 'Evening, Aarav.', subtext: 'Mumbai · 24° · clear', illustration: 'mumbai' },
    {
      type: 'c-confront', variant: 'quiet',
      eyebrow: "i won't soften this",
      title: 'nine days without calling him.',
      body: "you said 'this week' on tuesday. it's saturday. he won't ask, but he's noticed.",
    },
    {
      type: 'c-reflection', variant: 'prompt',
      eyebrow: 'a reflection · for tonight',
      prompt: 'what were you actually avoiding this week?',
    },
    { type: 'footer', kind: 'italic', text: "i'll be here in the morning." },
  ],
};

// ─── 18 · open loops + permission (sunday review) ────────────────────────
export const sc18: DashboardPlan = {
  id: 'sc:18-loops-permission',
  generatedAt: '2026-04-26T20:00:00+05:30',
  user: userAarav,
  thesis: "three loops, one ask.",
  moment: 'evening',
  blocks: [
    { type: 'hero', date: 'Sunday · 26 April', greeting: 'Evening, Aarav.', subtext: 'Mumbai · 25° · cool', illustration: 'mumbai' },
    {
      type: 'c-openloop', variant: 'quote', title: "things you said you'd do", right: '3 open',
      items: [
        { commitment: 'reply to priya about the deck', ago: '3 d', overdue: true, due: 'overdue' },
        { commitment: "pick up the frame at oscar's", ago: '2 d', due: 'today' },
        { commitment: 'call kabir back', ago: '5 d', due: 'this week' },
      ],
    },
    {
      type: 'c-permission', variant: 'editorial',
      provider: 'google',
      body: 'let me read your calendar.',
      ctaConnect: 'connect',
      ctaDismiss: 'not yet',
    },
    { type: 'footer', kind: 'italic', text: "tomorrow's a new page." },
  ],
};

// ─── manifest ─────────────────────────────────────────────────────────────
export interface ShowcaseEntry {
  plan: DashboardPlan;
  label: string;
  subtitle: string;
}

export const SHOWCASE: ShowcaseEntry[] = [
  { plan: sc01, label: '01 · note',                   subtitle: 'editorial · one lead, no body' },
  { plan: sc02, label: '02 · tracker pair',           subtitle: 'canonical morning · body + money' },
  { plan: sc03, label: '03 · tracker borderless',     subtitle: 'three numbers, no chrome' },
  { plan: sc04, label: '04 · tracker hero',           subtitle: 'one number is the story today' },
  { plan: sc05, label: '05 · watch · the wire',       subtitle: "things i've got eyes on" },
  { plan: sc06, label: '06 · brief · weekly',         subtitle: 'newsstand layout · sector read' },
  { plan: sc07, label: '07 · prep · inline checklist', subtitle: 'the principal call · 4 items' },
  { plan: sc08, label: '08 · schedule · time column', subtitle: "the day's shape, enumerated" },
  { plan: sc09, label: '09 · schedule · day strip',   subtitle: 'proportional · visual at-a-glance' },
  { plan: sc10, label: '10 · streak + person list',   subtitle: 'celebration · moss tints' },
  { plan: sc11, label: '11 · person hero',            subtitle: 'one person, full card' },
  { plan: sc12, label: '12 · reminder pill + chips',  subtitle: 'one ping · zero-tap log' },
  { plan: sc13, label: '13 · reminders + tray',       subtitle: 'editorial list · iconographic chips' },
  { plan: sc14, label: '14 · picks + reads',          subtitle: 'a book + three articles' },
  { plan: sc15, label: '15 · offer · rust hero',      subtitle: 'the loud one · one rust per screen' },
  { plan: sc16, label: '16 · draft + decision',       subtitle: 'a letter to luca · pick a lunch' },
  { plan: sc17, label: '17 · confrontation + reflect', subtitle: 'late stakes · oxblood + italic' },
  { plan: sc18, label: '18 · open loops + permission', subtitle: 'sunday review · three quoted, one ask' },
];
