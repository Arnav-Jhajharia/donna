import type { DashboardPlan } from './plan';
import { morningAaravPlan } from './plans/morning-aarav';

/**
 * The seam where Donna's generator will eventually plug in.
 * Today: returns a static fixture.
 * Tomorrow: memory pipeline + LLM produces a plan per user per moment
 * (at which point this signature becomes async).
 */
export function getPlan(_userId: string, _now: Date): DashboardPlan {
  return morningAaravPlan;
}
