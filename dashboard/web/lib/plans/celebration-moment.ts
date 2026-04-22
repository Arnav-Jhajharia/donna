import type { DashboardPlan } from '../plan';

/**
 * Something landed. The deck shipped, the call happened, the streak hit.
 * One celebration + one witness + a quiet forward-look.
 * Thesis names what landed. Plan is short and proud.
 */
export const celebrationMomentPlan: DashboardPlan = {
  id: 'plan:aarav:2026-04-22:celebration',
  generatedAt: '2026-04-22T19:42:00+05:30',
  user: { name: 'Aarav', initial: 'A' },
  thesis: 'you did the dad call. that was the whole week\'s weight.',
  moment: 'evening',
  blocks: [
    {
      type: 'thesis',
      kicker: 'tonight',
      sentence: 'you did the dad call. that was the whole week\'s weight.',
    },
    {
      type: 'celebration',
      title: 'twenty-two minutes with dad.',
      body: "you'd been carrying this since tuesday. you told me four times you'd do it and didn't. tonight you did. he asked about priya. you told him about the deck. that counts.",
      badge: '6-day loop · closed',
    },
    {
      type: 'witness',
      observation: "you sounded lighter afterward. 'not as bad as i thought.' that's the sentence worth remembering the next time.",
    },
    {
      type: 'whisper',
      kicker: 'for the record',
      body: "i'll note this in your profile. the 'this week' promise to dad has a pattern. knowing it's survivable changes the next one.",
      level: 'subtle',
    },
    { type: 'footer', text: "rest easy. I'll see you tomorrow." },
  ],
};
