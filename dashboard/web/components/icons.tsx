interface IconProps {
  size?: number;
  color?: string;
}

export function DropIcon({ size = 18, color = 'var(--fg-tertiary)' }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M12 3c-4 5-6 8-6 11a6 6 0 0012 0c0-3-2-6-6-11z" stroke={color} strokeWidth="1.4" strokeLinejoin="round" />
    </svg>
  );
}

export function FlameIcon({ size = 18, color = 'var(--fg-tertiary)' }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M12 3c1 3 4 4 4 8a4 4 0 01-8 0c0-2 1-3 2-4-1 0-2-1-2-2 0 0 3 0 4-2z" stroke={color} strokeWidth="1.4" strokeLinejoin="round" />
    </svg>
  );
}

export function RupeeIcon({ size = 18, color = 'var(--fg-tertiary)' }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M7 5h10M7 9h10M9 5c3 0 5 2 5 4s-2 4-5 4H7l7 6" stroke={color} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function PhoneIcon({ size = 16, color = 'var(--fg-tertiary)' }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M5 4h3l2 5-2 1c1 3 3 5 6 6l1-2 5 2v3c0 1-1 2-2 2C10 21 3 14 3 6c0-1 1-2 2-2z" stroke={color} strokeWidth="1.4" strokeLinejoin="round" />
    </svg>
  );
}

export function FlowerIcon({ size = 16, color = 'var(--fg-tertiary)' }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="7" r="3" stroke={color} strokeWidth="1.1" />
      <circle cx="7" cy="12" r="3" stroke={color} strokeWidth="1.1" />
      <circle cx="17" cy="12" r="3" stroke={color} strokeWidth="1.1" />
      <circle cx="12" cy="17" r="3" stroke={color} strokeWidth="1.1" />
      <circle cx="12" cy="12" r="1" fill={color} />
    </svg>
  );
}

export function BowlIcon({ size = 16, color = 'var(--fg-tertiary)' }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M3 11h18a9 9 0 01-18 0z" stroke={color} strokeWidth="1.4" strokeLinejoin="round" />
      <path d="M8 8c0-1 1-2 2-2m3 2c0-1 1-2 2-2" stroke={color} strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

export function ChevIcon({ size = 13, color = 'var(--fg-placeholder)' }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" aria-hidden>
      <path d="M6 3l5 5-5 5" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function CheckIcon({ size = 12, color = 'var(--paper-100, #FBF7F5)' }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" aria-hidden>
      <path d="M3 8l3 3 7-7" stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function MoonIcon({ size = 16, color = 'var(--fg-tertiary)' }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M20 14a8 8 0 11-10-10 6 6 0 0010 10z" stroke={color} strokeWidth="1.4" strokeLinejoin="round" />
    </svg>
  );
}

export function SunIcon({ size = 16, color = 'var(--fg-tertiary)' }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="4" stroke={color} strokeWidth="1.4" />
      <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4L7 17M17 7l1.4-1.4" stroke={color} strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

export function HeartIcon({ size = 16, color = 'var(--fg-tertiary)' }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M12 20s-7-4.5-7-10a4 4 0 017-2.6A4 4 0 0119 10c0 5.5-7 10-7 10z" stroke={color} strokeWidth="1.4" strokeLinejoin="round" />
    </svg>
  );
}

export function LeafIcon({ size = 16, color = 'var(--fg-tertiary)' }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M5 19c0-8 6-14 14-14 0 8-6 14-14 14z" stroke={color} strokeWidth="1.4" strokeLinejoin="round" />
      <path d="M5 19c4-4 8-6 14-14" stroke={color} strokeWidth="1.1" strokeLinecap="round" />
    </svg>
  );
}

export function EyeIcon({ size = 16, color = 'var(--fg-tertiary)' }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z" stroke={color} strokeWidth="1.4" strokeLinejoin="round" />
      <circle cx="12" cy="12" r="2.5" stroke={color} strokeWidth="1.4" />
    </svg>
  );
}

export function HourglassIcon({ size = 16, color = 'var(--fg-tertiary)' }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M7 3h10M7 21h10M8 3c0 4 8 5 8 9s-8 5-8 9" stroke={color} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

import type { IconName } from '@/lib/plan';

export const ICONS: Record<IconName, (p: IconProps) => React.ReactElement> = {
  phone: PhoneIcon,
  drop: DropIcon,
  bowl: BowlIcon,
  flower: FlowerIcon,
  flame: FlameIcon,
  rupee: RupeeIcon,
  moon: MoonIcon,
  sun: SunIcon,
  heart: HeartIcon,
  leaf: LeafIcon,
  eye: EyeIcon,
  hourglass: HourglassIcon,
};
