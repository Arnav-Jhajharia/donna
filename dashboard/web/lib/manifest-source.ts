import type { DashboardPlan } from './plan';
import { busyPitchPlan } from './plans/busy-pitch';
import { drunkWaterPlan } from './plans/drunk-water';
import { eveningReflectionPlan } from './plans/evening-reflection';
import { integrationPromptPlan } from './plans/integration-prompt';
import { lowEnergyPlan } from './plans/low-energy';
import { middayCheckPlan } from './plans/midday-check';
import { morningAaravPlan } from './plans/morning-aarav';

/**
 * The phase-1 manifest source. The brain doesn't compose plans yet, so we
 * rotate through canonical fixtures by minute. The shape and the seam are
 * the same as what the brain will eventually write — meaning the page
 * code never needs to change when phase 2 lands.
 */

const FIXTURES: Record<string, DashboardPlan> = {
  morning: morningAaravPlan,
  midday: middayCheckPlan,
  evening: eveningReflectionPlan,
  'low-energy': lowEnergyPlan,
  'busy-pitch': busyPitchPlan,
  'drunk-water': drunkWaterPlan,
  'integration-prompt': integrationPromptPlan,
};

const ROTATION = [
  'morning',
  'busy-pitch',
  'midday',
  'low-energy',
  'drunk-water',
  'integration-prompt',
  'evening',
] as const;

export interface SelectFixtureArgs {
  userId: string;
  fixtureName?: string;
  now: Date;
}

export function selectFixture({ fixtureName, now }: SelectFixtureArgs): DashboardPlan {
  if (fixtureName && FIXTURES[fixtureName]) {
    return FIXTURES[fixtureName];
  }
  // Rotate every 30 seconds so a polling client visibly sees plans change.
  const slot = Math.floor(now.getTime() / 30_000) % ROTATION.length;
  return FIXTURES[ROTATION[slot]];
}

export function listFixtures(): { name: string; thesis: string }[] {
  return Object.entries(FIXTURES).map(([name, plan]) => ({ name, thesis: plan.thesis }));
}
