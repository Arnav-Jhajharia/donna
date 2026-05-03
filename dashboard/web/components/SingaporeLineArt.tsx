interface Props {
  stroke?: string;
  paper?: string;
  opacity?: number;
}

/**
 * Singapore skyline. Anchored on Marina Bay Sands (three towers with the
 * SkyPark boat across the top — the city's most readable silhouette),
 * with the ArtScience Museum (lotus), a Supertree, the CBD cluster, and
 * a Merlion at the waterline. Same hairline / paper-fill treatment as
 * MumbaiLineArt so the two illustrations live in the same visual key.
 */
export default function SingaporeLineArt({
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
      {/* waterline + ground line */}
      <path d="M6 122 Q 120 118, 240 121 T 394 123" stroke={stroke} strokeWidth="0.7" fill="none" opacity={opacity * 0.5} />
      <path d="M6 128 Q 200 130, 394 128" stroke={stroke} strokeWidth="0.4" fill="none" opacity={opacity * 0.3} />

      {/* CBD cluster on the far left — Raffles Place towers */}
      <g stroke={stroke} strokeWidth="0.9" fill={paper} opacity={opacity}>
        <path d="M16 122 L16 96 L28 96 L28 122 Z" />
        <path d="M30 122 L30 84 L42 84 L42 78 L48 78 L48 122 Z" strokeLinejoin="round" />
        <path d="M52 122 L52 90 L60 90 L60 86 L68 86 L68 122 Z" strokeLinejoin="round" />
        <path d="M72 122 L72 70 L80 70 L80 64 L88 64 L88 122 Z" strokeLinejoin="round" />
        <path d="M92 122 L92 80 L102 80 L102 122 Z" />
        <path d="M106 122 L106 92 L116 92 L116 122 Z" />
      </g>

      {/* Merlion — small fountain head on the waterfront */}
      <g stroke={stroke} strokeWidth="0.9" fill={paper} opacity={opacity}>
        {/* plinth */}
        <path d="M128 122 L128 116 L142 116 L142 122 Z" />
        {/* body + head */}
        <path d="M130 116 Q 132 108, 136 108 L 138 108 Q 142 108, 142 114 L 142 116 Z" strokeLinejoin="round" />
        {/* head */}
        <circle cx="136" cy="106" r="2.2" />
        {/* water arc */}
        <path d="M134 106 Q 124 96, 118 102" stroke={stroke} strokeWidth="0.6" fill="none" opacity={opacity * 0.7} />
        <path d="M134 106 Q 122 98, 114 106" stroke={stroke} strokeWidth="0.5" fill="none" opacity={opacity * 0.5} />
      </g>

      {/* ArtScience Museum — the lotus shape near the bay */}
      <g stroke={stroke} strokeWidth="0.9" fill={paper} opacity={opacity}>
        <path
          d="M154 122 Q 150 116, 154 110 Q 152 102, 158 100 Q 156 92, 164 94 Q 166 88, 172 96 Q 178 90, 178 100 Q 184 102, 180 110 Q 184 116, 178 122 Z"
          strokeLinejoin="round"
        />
      </g>

      {/* Marina Bay Sands — the centerpiece */}
      <g stroke={stroke} strokeWidth="1.1" fill={paper} opacity={opacity}>
        {/* tower 1 (slight inward lean) */}
        <path d="M196 122 L 200 60 L 218 60 L 222 122 Z" strokeLinejoin="round" />
        {/* tower 2 — tallest, centred */}
        <path d="M236 122 L 240 56 L 258 56 L 262 122 Z" strokeLinejoin="round" />
        {/* tower 3 */}
        <path d="M276 122 L 280 60 L 298 60 L 302 122 Z" strokeLinejoin="round" />
        {/* SkyPark — the iconic "boat" deck connecting all three tower tops */}
        <path
          d="M188 56 Q 180 50, 188 46 L 308 42 Q 318 44, 312 52 L 308 56 Z"
          strokeLinejoin="round"
          fill="var(--paper-200)"
        />
        {/* a few palm-tree marks on the SkyPark to suggest the infinity-pool deck */}
        <line x1="210" y1="46" x2="210" y2="42" strokeWidth="0.6" />
        <line x1="250" y1="44" x2="250" y2="40" strokeWidth="0.6" />
        <line x1="290" y1="46" x2="290" y2="42" strokeWidth="0.6" />
      </g>

      {/* Supertree Grove — one supertree on the right */}
      <g stroke={stroke} strokeWidth="0.9" fill={paper} opacity={opacity}>
        {/* trunk */}
        <path d="M328 122 L 326 80 L 332 78 L 332 122 Z" strokeLinejoin="round" />
        {/* canopy spokes */}
        <path d="M330 78 Q 314 70, 308 80" stroke={stroke} strokeWidth="0.7" fill="none" />
        <path d="M330 78 Q 322 64, 318 76" stroke={stroke} strokeWidth="0.7" fill="none" />
        <path d="M330 78 Q 330 60, 336 70" stroke={stroke} strokeWidth="0.7" fill="none" />
        <path d="M330 78 Q 342 64, 346 76" stroke={stroke} strokeWidth="0.7" fill="none" />
        <path d="M330 78 Q 352 70, 356 80" stroke={stroke} strokeWidth="0.7" fill="none" />
      </g>

      {/* far-right skyline taper */}
      <g stroke={stroke} strokeWidth="0.9" fill={paper} opacity={opacity}>
        <path d="M364 122 L364 100 L374 100 L374 122 Z" />
        <path d="M378 122 L378 88 L388 88 L388 122 Z" />
        <path d="M392 122 L392 106 L398 106 L398 122 Z" />
      </g>

      {/* faint cloud strokes — reuse Mumbai's atmospheric language */}
      <path d="M60 32 q 4 -4 8 0 q 4 -4 8 0" stroke={stroke} strokeWidth="0.7" fill="none" opacity={opacity * 0.8} />
      <path d="M340 24 q 3 -3 6 0 q 3 -3 6 0" stroke={stroke} strokeWidth="0.7" fill="none" opacity={opacity * 0.7} />
    </svg>
  );
}
