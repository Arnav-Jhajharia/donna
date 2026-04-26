'use client';

/**
 * RowGrid — renders a Row of cells through the 12-column layout grid.
 *
 * The brain composes seven canonical row shapes (see system.html §4):
 *   [full] · [half, half] · [two-thirds, third] · [three-quarters, quarter]
 *   [third, third, third] · [half, quarter, quarter]
 *   [quarter, quarter, quarter, quarter]
 *
 * RowGrid is component-agnostic. It knows how to size cells. What goes
 * inside a cell is the registry's problem.
 *
 * At ≤480px every cell becomes full-width; order preserved. The CSS in
 * globals.css enforces the collapse — RowGrid does no JS-side responsive
 * logic.
 */

import type { ReactNode } from 'react';

export type SlotSize =
  | 'full'
  | 'three-quarters'
  | 'two-thirds'
  | 'half'
  | 'third'
  | 'quarter';

export interface CellProps {
  size: SlotSize;
  children: ReactNode;
}

export function Cell({ size, children }: CellProps) {
  return <div className={`cell--${size}`}>{children}</div>;
}

export interface RowGridProps {
  children: ReactNode;
  /** Marks the last row in a sequence — drops bottom margin. */
  last?: boolean;
}

export function RowGrid({ children, last = false }: RowGridProps) {
  return <div className={last ? 'row row--last' : 'row'}>{children}</div>;
}
