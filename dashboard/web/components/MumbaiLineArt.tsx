interface Props {
  stroke?: string;
  paper?: string;
  opacity?: number;
}

export default function MumbaiLineArt({
  stroke = 'var(--rust-700)',
  paper = 'var(--paper-50)',
  opacity = 0.75,
}: Props) {
  return (
    <svg
      viewBox="0 0 400 140"
      width="100%"
      height={140}
      preserveAspectRatio="xMidYMax meet"
      style={{ display: 'block' }}
      aria-hidden
    >
      <path d="M6 122 Q 120 118, 240 121 T 394 123" stroke={stroke} strokeWidth="0.7" fill="none" opacity={opacity * 0.5} />
      <g stroke={stroke} strokeWidth="0.9" fill={paper} opacity={opacity}>
        <path d="M24 122 L24 98 L38 98 L38 86 L50 86 L50 122 Z" strokeLinejoin="round" />
        <path d="M54 122 L54 92 L66 92 L66 122 Z" />
        <path d="M70 122 L70 100 L82 100 L82 122 Z" />
        <path d="M86 122 L86 88 L96 88 L96 78 L106 78 L106 122 Z" strokeLinejoin="round" />
        <path d="M112 122 L112 94 L124 94 L124 122 Z" />
      </g>
      <g stroke={stroke} strokeWidth="0.9" fill={paper} opacity={opacity}>
        <path d="M138 122 L138 84 L170 84 L170 122 Z" />
        <path d="M142 84 Q 154 64, 166 84 L 166 84 L 142 84 Z" strokeLinejoin="round" />
        <line x1="154" y1="54" x2="154" y2="64" />
        <circle cx="154" cy="52" r="1.4" fill={stroke} />
      </g>
      <g stroke={stroke} strokeWidth="0.9" fill={paper} opacity={opacity}>
        <path d="M178 122 L178 96 L196 96 L196 122 Z" />
        <path d="M202 122 L202 86 L214 86 L214 122 Z" />
      </g>
      <g stroke={stroke} strokeWidth="1.1" fill={paper} opacity={opacity}>
        <rect x="232" y="104" width="8" height="18" />
        <rect x="332" y="104" width="8" height="18" />
        <rect x="240" y="72" width="16" height="50" />
        <rect x="316" y="72" width="16" height="50" />
        <rect x="240" y="66" width="16" height="6" />
        <rect x="316" y="66" width="16" height="6" />
        <rect x="244" y="58" width="8" height="8" />
        <rect x="320" y="58" width="8" height="8" />
        <path d="M256 122 L256 62 L316 62 L316 122" />
        <path d="M256 62 Q 286 34, 316 62 L316 62 L256 62 Z" strokeLinejoin="round" />
        <path d="M262 34 Q 286 8, 310 34" strokeLinejoin="round" />
        <line x1="286" y1="4" x2="286" y2="14" strokeWidth="0.8" />
        <circle cx="286" cy="3" r="1.5" fill={stroke} />
        <path d="M268 122 L268 82 Q 286 68, 304 82 L 304 122" strokeLinejoin="round" fill="var(--paper-200)" />
      </g>
      <g stroke={stroke} strokeWidth="0.9" fill={paper} opacity={opacity}>
        <path d="M348 122 L348 96 L362 96 L362 122 Z" />
        <path d="M366 122 L366 102 L378 102 L378 122 Z" />
        <path d="M380 122 L380 92 L392 92 L392 122 Z" />
      </g>
      <path d="M72 50 q 4 -4 8 0 q 4 -4 8 0" stroke={stroke} strokeWidth="0.7" fill="none" opacity={opacity * 0.8} />
      <path d="M290 22 q 3 -3 6 0 q 3 -3 6 0" stroke={stroke} strokeWidth="0.7" fill="none" opacity={opacity * 0.7} />
    </svg>
  );
}
