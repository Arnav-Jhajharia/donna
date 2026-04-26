'use client';

/**
 * Frame — the canonical card wrapper from the Donna visual contract.
 *
 * Every slot the brain emits is rendered through Frame. Identical chrome at
 * every width: paper-200 background, hairline ink-08 border, radius lg,
 * padding 24 (16 mobile), no shadow. Width changes; nothing else does.
 *
 * Block components are content-only: they render kicker / title / body and
 * any inline primitives, but never their own border, radius, padding, or
 * background. Frame owns chrome.
 *
 * Class names mirror the visual contract verbatim — see
 * donna-design-system/system.html and dashboard/web/app/globals.css.
 */

import type { ReactNode } from 'react';
import type { ActionVerb } from '@/lib/plan';

export type FrameVariant = 'default' | 'tappable' | 'done' | 'placeholder' | 'disabled';

export interface FrameProps {
  /** Optional eyebrow above the title — uppercase tracking label. */
  kicker?: string;
  /** Optional internal title — h4 sans 600. */
  title?: ReactNode;
  /** Body content rendered inside the Frame. */
  children?: ReactNode;
  /** When set, renders tappable affordances (hover, focus ring, active). */
  variant?: FrameVariant;
  /** Optional click handler — implies tappable variant unless overridden. */
  onClick?: () => void;
  /** Optional ActionVerb dispatched on tap. Renderer wires this. */
  action?: ActionVerb;
  /** Test/debug hook. */
  'data-kind'?: string;
}

export function Frame({
  kicker,
  title,
  children,
  variant = 'default',
  onClick,
  action: _action,
  ...rest
}: FrameProps) {
  const isInteractive = variant === 'tappable' || onClick !== undefined;
  const classNames = ['frame'];
  if (isInteractive) classNames.push('frame--tappable');
  if (variant === 'done') classNames.push('frame--done');
  if (variant === 'placeholder') classNames.push('frame--placeholder');
  if (variant === 'disabled') classNames.push('frame--disabled');

  const role = isInteractive ? 'button' : undefined;
  const tabIndex = isInteractive ? 0 : undefined;

  return (
    <div
      className={classNames.join(' ')}
      role={role}
      tabIndex={tabIndex}
      onClick={onClick}
      onKeyDown={
        isInteractive
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onClick?.();
              }
            }
          : undefined
      }
      {...rest}
    >
      {kicker && <p className="frame__kicker">{kicker}</p>}
      {title && <h4 className="frame__title">{title}</h4>}
      {children}
    </div>
  );
}

/** Placeholder Frame — shown when the registry has no component for a kind. */
export function PlaceholderFrame({ kind }: { kind: string }) {
  return (
    <Frame variant="placeholder" data-kind={kind}>
      <span className="frame__ph">no component for &lsquo;{kind}&rsquo;</span>
    </Frame>
  );
}
