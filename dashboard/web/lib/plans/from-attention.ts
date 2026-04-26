/**
 * Attention-driven plan fixture.
 *
 * Demonstrates the full path: attention payloads → adapter → Block[] → plan.
 * Every block here was composed, not designed. This is what a future generator
 * run looks like when it reads live attentions instead of static fixtures.
 *
 * Scenario: Aarav on a Wednesday midday. Four attentions are live:
 *   1. attention "dad_call" — open_loop, urgent (claims rust this turn)
 *   2. attention "hydration" — tally, notify
 *   3. attention "series_a" — brief, notify
 *   4. attention "priya_1on1" — prep_doc, digest
 */

import { attentionToBlock, type AttentionCard, type RenderHints } from '../attention-adapter';
import type { Block, DashboardPlan } from '../plan';

interface AttentionTurn {
  key: string;
  attention: AttentionCard;
  hints: RenderHints;
}

const ATTENTIONS: AttentionTurn[] = [
  {
    key: 'dad_call',
    attention: {
      card: 'open_loop',
      payload: {
        loop_summary: 'call dad — committed "this week" on tuesday',
        last_activity_at: '2026-04-21T18:20:00+05:30',
        waiting_on: 'you, to pick up the phone',
        is_resolved: false,
      },
    },
    hints: { title: 'still open', surfaceLevel: 'urgent', domain: 'social', claimsRust: true },
  },
  {
    key: 'hydration',
    attention: {
      card: 'tally',
      payload: { count: 3, unit: 'glasses', window: 'so far today' },
    },
    hints: { title: 'water', surfaceLevel: 'notify', domain: 'health' },
  },
  {
    key: 'series_a',
    attention: {
      card: 'brief',
      payload: {
        headline: 'three investors pinged while you were out',
        bullets: [
          'sequoia · wants a revenue slide by friday',
          'accel · re-engaged on the thread after six days',
        ],
        sources: ['gmail · series-a thread'],
      },
    },
    hints: { title: 'fundraising', surfaceLevel: 'notify', domain: 'fundraising' },
  },
  {
    key: 'priya_1on1',
    attention: {
      card: 'prep_doc',
      payload: {
        for_event: '1:1 with priya',
        context: 'first week, onboarding questions',
        talking_points: [
          'where she\'s stuck on the billing refactor',
          'who she\'s met outside the team',
        ],
        open_questions: ['what would a good second week look like?'],
      },
    },
    hints: { title: 'prep', surfaceLevel: 'digest', domain: 'meeting' },
  },
];

function composeBlocks(): Block[] {
  const blocks: Block[] = [
    {
      type: 'thesis',
      kicker: 'right now',
      sentence: 'today is about calling dad before it gets weirder.',
    },
  ];
  for (const t of ATTENTIONS) {
    blocks.push(attentionToBlock(t.attention, t.hints));
  }
  blocks.push({ type: 'footer', text: "I'm listening · tap to talk" });
  return blocks;
}

export const fromAttentionPlan: DashboardPlan = {
  id: 'plan:aarav:2026-04-22:from-attention',
  generatedAt: '2026-04-22T12:40:00+05:30',
  user: { name: 'Aarav', initial: 'A' },
  thesis: 'today is about calling dad before it gets weirder.',
  moment: 'midday',
  blocks: composeBlocks(),
};
