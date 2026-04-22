// Donna — Mobile Dashboard (v2)
// Editorial, line-art illustrations · sentence-case subheads · italics reserved
// Uses the full brown + paper scale for tonal variety

const D = {
  // Paper scale
  paper50:  '#FDFAF8',
  paper100: '#FBF7F5', // bg
  paper200: '#F5EFEA', // rust tint — also accent-tint
  paper300: '#F0EAE4', // surface
  paper400: '#E7DFD7', // surface-2
  paper500: '#D6CAC0',
  // Rust scale
  rust900: '#4A2F23',
  rust700: '#7B5544', // accent
  rust500: '#A07562',
  rust300: '#C9A796',
  rust100: '#EBDCD2',
  // Ink scale
  ink900:  '#1E1A18',
  ink700:  '#3A3331',
  ink500:  '#6B615C',
  ink400:  '#8F837C',
  ink300:  '#B5A89F',
  ink200:  '#D9CEC5',
  // Signals
  moss:    '#5C6B4A',
  mossTint:'#EEF1E7',
  amber:   '#A8804A',
  amberTint:'#F5EBD9',
  oxblood: '#8B3A2E',

  border:       'rgba(30,26,24,0.08)',
  borderStrong: 'rgba(30,26,24,0.14)',
  borderAccent: 'rgba(123,85,68,0.28)',

  serif: "'EB Garamond', Georgia, serif",
  sans:  "'Red Hat Text', -apple-system, sans-serif",
};

// ── Line-art Gateway of India — matches index.html vignette language ───────
// Outlined, opacity-dimmed, paper-filled shapes, a single hairline stroke.
function MumbaiLineArt({ stroke = D.rust700, opacity = 0.7, paper = D.paper100 }) {
  return (
    <svg viewBox="0 0 400 140" width="100%" height="140" preserveAspectRatio="xMidYMax meet" style={{ display: 'block' }}>
      {/* horizon / sea line */}
      <path d="M6 122 Q 120 118, 240 121 T 394 123"
            stroke={stroke} strokeWidth="0.7" fill="none" opacity={opacity * 0.5}/>
      {/* distant buildings, left */}
      <g stroke={stroke} strokeWidth="0.9" fill={paper} opacity={opacity}>
        <path d="M24 122 L24 98 L38 98 L38 86 L50 86 L50 122 Z" strokeLinejoin="round"/>
        <path d="M54 122 L54 92 L66 92 L66 122 Z"/>
        <path d="M70 122 L70 100 L82 100 L82 122 Z"/>
        <path d="M86 122 L86 88 L96 88 L96 78 L106 78 L106 122 Z" strokeLinejoin="round"/>
        <path d="M112 122 L112 94 L124 94 L124 122 Z"/>
      </g>
      {/* Taj dome silhouette — inline left of gateway */}
      <g stroke={stroke} strokeWidth="0.9" fill={paper} opacity={opacity}>
        <path d="M138 122 L138 84 L170 84 L170 122 Z"/>
        <path d="M142 84 Q 154 64, 166 84" strokeLinejoin="round" fill="none"/>
        <path d="M142 84 Q 154 64, 166 84 L 166 84 L 142 84 Z" strokeLinejoin="round"/>
        <line x1="154" y1="54" x2="154" y2="64"/>
        <circle cx="154" cy="52" r="1.4" fill={stroke}/>
      </g>
      {/* mid buildings */}
      <g stroke={stroke} strokeWidth="0.9" fill={paper} opacity={opacity}>
        <path d="M178 122 L178 96 L196 96 L196 122 Z"/>
        <path d="M202 122 L202 86 L214 86 L214 122 Z"/>
      </g>
      {/* Gateway of India — hero element, slightly deeper stroke */}
      <g stroke={stroke} strokeWidth="1.1" fill={paper} opacity={opacity}>
        {/* base plinths */}
        <rect x="232" y="104" width="8" height="18"/>
        <rect x="332" y="104" width="8" height="18"/>
        {/* flanking towers */}
        <rect x="240" y="72" width="16" height="50"/>
        <rect x="316" y="72" width="16" height="50"/>
        {/* tower caps (stepped) */}
        <rect x="240" y="66" width="16" height="6"/>
        <rect x="316" y="66" width="16" height="6"/>
        <rect x="244" y="58" width="8" height="8"/>
        <rect x="320" y="58" width="8" height="8"/>
        {/* main arch block */}
        <path d="M256 122 L256 62 L316 62 L316 122"/>
        {/* arch curve */}
        <path d="M256 62 Q 286 34, 316 62" strokeLinejoin="round" fill="none"/>
        <path d="M256 62 Q 286 34, 316 62 L316 62 L256 62 Z" strokeLinejoin="round"/>
        {/* dome */}
        <path d="M262 34 Q 286 8, 310 34" strokeLinejoin="round"/>
        <line x1="286" y1="4" x2="286" y2="14" strokeWidth="0.8"/>
        <circle cx="286" cy="3" r="1.5" fill={stroke}/>
        {/* carved arch opening */}
        <path d="M268 122 L268 82 Q 286 68, 304 82 L 304 122"
              strokeLinejoin="round" fill={D.paper200}/>
      </g>
      {/* far right buildings */}
      <g stroke={stroke} strokeWidth="0.9" fill={paper} opacity={opacity}>
        <path d="M348 122 L348 96 L362 96 L362 122 Z"/>
        <path d="M366 122 L366 102 L378 102 L378 122 Z"/>
        <path d="M380 122 L380 92 L392 92 L392 122 Z"/>
      </g>
      {/* a small gull */}
      <path d="M72 50 q 4 -4 8 0 q 4 -4 8 0" stroke={stroke} strokeWidth="0.7" fill="none" opacity={opacity * 0.8}/>
      <path d="M290 22 q 3 -3 6 0 q 3 -3 6 0" stroke={stroke} strokeWidth="0.7" fill="none" opacity={opacity * 0.7}/>
    </svg>
  );
}

// ── Small line-art icons (outlined, match index vignette) ──────────────────
const LI = {
  drop: ({ size = 18, c = D.ink700 }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <path d="M12 3c-4 5-6 8-6 11a6 6 0 0012 0c0-3-2-6-6-11z" stroke={c} strokeWidth="1.4" strokeLinejoin="round"/>
    </svg>
  ),
  flame: ({ size = 18, c = D.ink700 }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <path d="M12 3c1 3 4 4 4 8a4 4 0 01-8 0c0-2 1-3 2-4-1 0-2-1-2-2 0 0 3 0 4-2z" stroke={c} strokeWidth="1.4" strokeLinejoin="round"/>
    </svg>
  ),
  rupee: ({ size = 18, c = D.ink700 }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <path d="M7 5h10M7 9h10M9 5c3 0 5 2 5 4s-2 4-5 4H7l7 6" stroke={c} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  phone: ({ size = 16, c = D.ink700 }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <path d="M5 4h3l2 5-2 1c1 3 3 5 6 6l1-2 5 2v3c0 1-1 2-2 2C10 21 3 14 3 6c0-1 1-2 2-2z" stroke={c} strokeWidth="1.4" strokeLinejoin="round"/>
    </svg>
  ),
  flower: ({ size = 16, c = D.ink700 }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="7" r="3" stroke={c} strokeWidth="1.1"/>
      <circle cx="7" cy="12" r="3" stroke={c} strokeWidth="1.1"/>
      <circle cx="17" cy="12" r="3" stroke={c} strokeWidth="1.1"/>
      <circle cx="12" cy="17" r="3" stroke={c} strokeWidth="1.1"/>
      <circle cx="12" cy="12" r="1" fill={c}/>
    </svg>
  ),
  bowl: ({ size = 16, c = D.ink700 }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <path d="M3 11h18a9 9 0 01-18 0z" stroke={c} strokeWidth="1.4" strokeLinejoin="round"/>
      <path d="M8 8c0-1 1-2 2-2m3 2c0-1 1-2 2-2" stroke={c} strokeWidth="1.4" strokeLinecap="round"/>
    </svg>
  ),
  chev: ({ size = 13, c = D.ink400 }) => (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <path d="M6 3l5 5-5 5" stroke={c} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  plus: ({ size = 14, c = D.ink900 }) => (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <path d="M8 3v10M3 8h10" stroke={c} strokeWidth="1.6" strokeLinecap="round"/>
    </svg>
  ),
  check: ({ size = 12, c = D.ink900 }) => (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <path d="M3 8l3 3 7-7" stroke={c} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
};

// ── Section header — sentence-case serif, no caps ──────────────────────────
function SectionHead({ title, right, tone = D.ink900 }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
      paddingBottom: 8, borderBottom: `1px solid ${D.border}`,
    }}>
      <h3 style={{
        margin: 0, fontFamily: D.serif, fontWeight: 500, fontSize: 18,
        letterSpacing: '-0.01em', color: tone,
      }}>{title}</h3>
      {right && (
        <span style={{
          fontFamily: D.sans, fontSize: 12, color: D.ink500, fontWeight: 400,
        }}>{right}</span>
      )}
    </div>
  );
}

// ── Hero ───────────────────────────────────────────────────────────────────
// Paper-50 tonal difference, line-art skyline. Single italic pull only on wordmark & her kept name.
function Hero({ density = 'balanced' }) {
  const pad = density === 'airy' ? 26 : density === 'rich' ? 18 : 22;
  return (
    <div style={{
      margin: '0 16px', borderRadius: 14, overflow: 'hidden',
      background: D.paper50,
      border: `1px solid ${D.border}`,
      position: 'relative',
    }}>
      <div style={{ padding: `${pad}px ${pad}px 10px` }}>
        <div style={{
          fontFamily: D.sans, fontSize: 11, letterSpacing: '0.14em',
          textTransform: 'uppercase', color: D.ink400, fontWeight: 500,
        }}>Friday · 18 April</div>
        <div style={{
          fontFamily: D.serif, fontWeight: 400,
          fontSize: density === 'rich' ? 28 : 32, lineHeight: 1.08,
          letterSpacing: '-0.02em', color: D.ink900, marginTop: 8,
        }}>
          Good morning, Aarav.
        </div>
        <div style={{
          fontFamily: D.sans, fontSize: 13, color: D.ink500,
          marginTop: 10, letterSpacing: '-0.005em',
        }}>Mumbai · 29° · slight haze, cooler by the sea</div>
      </div>
      <div style={{ marginTop: density === 'airy' ? 14 : 8 }}>
        <MumbaiLineArt stroke={D.rust700} opacity={0.75} paper={D.paper50}/>
      </div>
    </div>
  );
}

// ── Todos ──────────────────────────────────────────────────────────────────
// Donna speaks as "I". Three items I picked. No italics except Aarav's name pull.
const TODOS = [
  { key: 't1', label: 'Call your Dad back',          meta: 'You told him "this week" on Tuesday',  source: 'messages' },
  { key: 't2', label: 'Send Priya the onboarding deck', meta: 'You promised Friday',                source: 'mail',     done: true },
  { key: 't3', label: "Pick up the frame at Oscar's",   meta: 'Ready since yesterday',               source: 'calendar' },
];

function TodoSection({ style = 'checkbox', density = 'balanced' }) {
  const gap = density === 'airy' ? 12 : density === 'rich' ? 6 : 10;
  const titleSize = density === 'rich' ? 14 : 15;
  const done = TODOS.filter(t => t.done).length;

  return (
    <section style={{ margin: '26px 16px 0' }}>
      <SectionHead
        title="Three I picked for you"
        right={`${done} of ${TODOS.length} kept`}
      />
      <div style={{
        marginTop: 12,
        display: style === 'card' ? 'grid' : 'flex',
        flexDirection: style === 'card' ? undefined : 'column',
        gap: style === 'card' ? 8 : gap,
      }}>
        {TODOS.map(t => <TodoItem key={t.key} {...t} style={style} titleSize={titleSize}/>)}
      </div>
    </section>
  );
}

function TodoItem({ label, meta, source, done, style, titleSize }) {
  const sourceTag = source;

  if (style === 'card') {
    return (
      <div style={{
        background: done ? D.paper200 : D.paper100,
        border: `1px solid ${D.border}`,
        borderLeft: `3px solid ${done ? D.moss : D.rust300}`,
        borderRadius: 8, padding: '12px 14px',
        display: 'flex', flexDirection: 'column', gap: 3,
      }}>
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 10,
        }}>
          <div style={{
            fontFamily: D.sans, fontSize: titleSize, color: done ? D.ink500 : D.ink900,
            textDecoration: done ? 'line-through' : 'none', textDecorationColor: D.ink300,
            fontWeight: 500, letterSpacing: '-0.005em',
          }}>{label}</div>
          {done && <span style={{ fontSize: 11, color: D.moss, fontWeight: 500 }}>kept</span>}
        </div>
        <div style={{ fontFamily: D.sans, fontSize: 12.5, color: D.ink500, lineHeight: 1.4 }}>
          {meta} <span style={{ color: D.ink400 }}>· from {sourceTag}</span>
        </div>
      </div>
    );
  }

  if (style === 'bullet') {
    return (
      <div style={{
        display: 'grid', gridTemplateColumns: '14px 1fr auto', gap: 12,
        padding: '9px 0', alignItems: 'baseline',
        borderBottom: `1px solid ${D.border}`,
      }}>
        <span style={{
          width: 5, height: 5, borderRadius: 999,
          background: done ? D.moss : D.rust700,
          display: 'inline-block', marginTop: 7,
        }}/>
        <div>
          <div style={{
            fontFamily: D.sans, fontSize: titleSize,
            color: done ? D.ink500 : D.ink900, fontWeight: 500,
            textDecoration: done ? 'line-through' : 'none', textDecorationColor: D.ink300,
            letterSpacing: '-0.005em',
          }}>{label}</div>
          <div style={{ fontFamily: D.sans, fontSize: 12.5, color: D.ink500, marginTop: 2 }}>
            {meta}
          </div>
        </div>
        <span style={{ fontFamily: D.sans, fontSize: 11, color: D.ink400 }}>{sourceTag}</span>
      </div>
    );
  }

  // checkbox
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '22px 1fr auto', gap: 12,
      padding: '10px 0', alignItems: 'flex-start',
      borderBottom: `1px solid ${D.border}`,
    }}>
      <div style={{
        width: 18, height: 18, borderRadius: 4,
        border: `1.25px solid ${done ? D.moss : D.borderStrong}`,
        background: done ? D.moss : 'transparent',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        marginTop: 2,
      }}>
        {done && <LI.check size={10} c={D.paper100}/>}
      </div>
      <div>
        <div style={{
          fontFamily: D.sans, fontSize: titleSize,
          color: done ? D.ink500 : D.ink900, fontWeight: 500,
          textDecoration: done ? 'line-through' : 'none', textDecorationColor: D.ink300,
          letterSpacing: '-0.005em',
        }}>{label}</div>
        <div style={{ fontFamily: D.sans, fontSize: 12.5, color: D.ink500, marginTop: 2 }}>
          {meta} <span style={{ color: D.ink400 }}>· from {sourceTag}</span>
        </div>
      </div>
      <span style={{ fontFamily: D.sans, fontSize: 11, color: done ? D.moss : D.ink400, marginTop: 3, fontWeight: done ? 500 : 400 }}>
        {done ? 'kept' : ''}
      </span>
    </div>
  );
}

// ── Tracker pair — distinct tones (amber-tinted for body, paper-400 for money) ─
function TrackerPair() {
  return (
    <section style={{ margin: '26px 16px 0' }}>
      <SectionHead title="Your body, your money" />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 12 }}>
        <TrackerCard
          title="Calories"
          value="1,240"
          unit="of 2,200 today"
          sub="Chicken bowl at lunch"
          progress={0.56}
          icon={<LI.flame c={D.amber}/>}
          tone={D.amber}
          bg={D.amberTint}
        />
        <TrackerCard
          title="Spend"
          value="₹ 420"
          unit="today · ₹ 8.2k this week"
          sub="Uber, coffee, Zomato"
          progress={0.3}
          icon={<LI.rupee c={D.ink700}/>}
          tone={D.ink700}
          bg={D.paper400}
        />
      </div>
    </section>
  );
}

function TrackerCard({ title, value, unit, sub, progress, icon, tone, bg }) {
  return (
    <div style={{
      background: bg,
      border: `1px solid ${D.border}`,
      borderRadius: 12, padding: '14px 14px 12px',
      display: 'flex', flexDirection: 'column', gap: 8,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{
          fontFamily: D.sans, fontSize: 11.5, letterSpacing: '-0.005em',
          color: D.ink700, fontWeight: 500,
        }}>{title}</div>
        {icon}
      </div>
      <div>
        <div style={{
          fontFamily: D.serif, fontWeight: 500, fontSize: 28, lineHeight: 1,
          letterSpacing: '-0.02em', color: D.ink900,
          fontVariantNumeric: 'tabular-nums',
        }}>{value}</div>
        <div style={{ fontFamily: D.sans, fontSize: 11.5, color: D.ink500, marginTop: 4 }}>{unit}</div>
      </div>
      <div style={{ height: 3, background: 'rgba(30,26,24,0.08)', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${progress * 100}%`, background: tone }}/>
      </div>
      <div style={{ fontFamily: D.sans, fontSize: 12, color: D.ink700, lineHeight: 1.4 }}>{sub}</div>
    </div>
  );
}

// ── Nudge grid — four cards, tonally distinct, line-art icons ──────────────
// Uses moss-tint, amber-tint, rust-100, and rust-700 (the one featured card)
const NUDGES = [
  {
    key: 'n1', title: 'Call Dad',           meta: "It's been six days", cta: 'Remind me at six',
    icon: LI.phone, bg: D.paper300, iconBg: D.paper400, tone: D.ink900,
  },
  {
    key: 'n2', title: 'Drink a glass',      meta: '2 of 8 so far today', cta: 'Log one',
    icon: LI.drop, bg: D.mossTint, iconBg: D.paper100, tone: D.moss, progress: 0.25,
  },
  {
    key: 'n3', title: 'Log lunch',          meta: 'You usually eat by 1:30', cta: 'Quick log',
    icon: LI.bowl, bg: D.amberTint, iconBg: D.paper100, tone: D.amber,
  },
  {
    key: 'n4', title: 'Send the peonies',   meta: "Maya's sister lands at 4:10", cta: 'Yes, order',
    icon: LI.flower, featured: true,
  },
];

function NudgeGrid() {
  return (
    <section style={{ margin: '26px 16px 24px' }}>
      <SectionHead
        title="A few small things"
        right="4"
      />
      <div style={{
        marginTop: 12,
        display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8,
      }}>
        {NUDGES.map(n => <NudgeTile key={n.key} {...n}/>)}
      </div>
    </section>
  );
}

function NudgeTile({ title, meta, icon: IconCmp, cta, progress, featured, bg, iconBg, tone }) {
  if (featured) {
    return (
      <div style={{
        background: D.rust700, color: D.paper100,
        border: `1px solid ${D.rust900}`,
        borderRadius: 10, padding: '12px 12px 10px',
        minHeight: 124, display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
      }}>
        <div>
          <div style={{
            width: 28, height: 28, borderRadius: 6,
            background: 'rgba(251,247,245,0.14)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <IconCmp c={D.paper100}/>
          </div>
          <div style={{
            fontFamily: D.serif, fontSize: 17, fontWeight: 500,
            letterSpacing: '-0.01em', marginTop: 10, lineHeight: 1.15, color: D.paper100,
          }}>{title}</div>
          <div style={{
            fontFamily: D.sans, fontSize: 12, marginTop: 3,
            color: 'rgba(251,247,245,0.75)', lineHeight: 1.4,
          }}>{meta}</div>
        </div>
        <div style={{
          fontFamily: D.sans, fontSize: 12, fontWeight: 500,
          color: D.paper100, display: 'flex', alignItems: 'center', gap: 4, marginTop: 8,
          letterSpacing: '-0.005em',
        }}>{cta} <LI.chev size={11} c={D.paper100}/></div>
      </div>
    );
  }

  return (
    <div style={{
      background: bg, border: `1px solid ${D.border}`,
      borderRadius: 10, padding: '12px 12px 10px', minHeight: 124,
      display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
    }}>
      <div>
        <div style={{
          width: 28, height: 28, borderRadius: 6, background: iconBg,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <IconCmp c={tone}/>
        </div>
        <div style={{
          fontFamily: D.serif, fontSize: 17, fontWeight: 500,
          letterSpacing: '-0.01em', marginTop: 10, lineHeight: 1.15, color: D.ink900,
        }}>{title}</div>
        <div style={{
          fontFamily: D.sans, fontSize: 12, marginTop: 3,
          color: D.ink500, lineHeight: 1.4,
        }}>{meta}</div>
      </div>
      {progress !== undefined && (
        <div style={{
          height: 3, background: 'rgba(30,26,24,0.08)',
          borderRadius: 2, overflow: 'hidden', marginTop: 8,
        }}>
          <div style={{ height: '100%', width: `${progress * 100}%`, background: tone }}/>
        </div>
      )}
      <div style={{
        fontFamily: D.sans, fontSize: 12, fontWeight: 500, color: tone,
        display: 'flex', alignItems: 'center', gap: 4, marginTop: 8,
        letterSpacing: '-0.005em',
      }}>{cta} <LI.chev size={11} c={tone}/></div>
    </div>
  );
}

// ── Donna's voice — speaks as "I", sparing italics (only a kept name) ──────
function DonnaWhisper({ level = 'subtle' }) {
  if (level === 'minimal') return null;
  const body =
    level === 'loud'
      ? "Before you scroll — the peonies need to leave the florist by eleven so they beat the plane. I drafted the note to go with them. Want to read it?"
      : "The peonies need to leave the florist by eleven.";
  return (
    <div style={{
      margin: '16px 16px 0',
      padding: level === 'loud' ? '14px 16px' : '10px 14px',
      background: D.rust100,
      borderLeft: `2px solid ${D.rust700}`,
      borderRadius: 2,
    }}>
      <div style={{
        fontFamily: D.sans, fontSize: 10, letterSpacing: '0.14em',
        textTransform: 'uppercase', color: D.rust700, fontWeight: 500, marginBottom: 4,
      }}>A note from me</div>
      <div style={{
        fontFamily: D.sans,
        fontSize: level === 'loud' ? 14 : 13.5,
        lineHeight: 1.5, color: D.ink900, letterSpacing: '-0.005em',
      }}>{body}</div>
    </div>
  );
}

// ── Dashboard composition ──────────────────────────────────────────────────
function DashboardContent({ density = 'balanced', todoStyle = 'checkbox', voice = 'minimal' }) {
  return (
    <div style={{
      background: D.paper100, minHeight: '100%',
      paddingTop: 58, paddingBottom: 48,
    }}>
      {/* chrome — only the wordmark is italic, per brand */}
      <div style={{
        padding: '8px 22px 14px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <span style={{
          fontFamily: D.serif, fontStyle: 'italic', fontWeight: 500,
          fontSize: 22, letterSpacing: '-0.015em', color: D.ink900,
          display: 'inline-flex', alignItems: 'baseline', gap: 2,
        }}>
          donna
          <span style={{
            width: 5, height: 5, borderRadius: 999, background: D.rust700,
            display: 'inline-block', marginLeft: 2, transform: 'translateY(-1px)',
          }}/>
        </span>
        <div style={{
          width: 30, height: 30, borderRadius: 999,
          background: D.paper300, color: D.ink700,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontFamily: D.sans, fontSize: 13, fontWeight: 500,
          border: `1px solid ${D.border}`,
        }}>A</div>
      </div>

      <Hero density={density}/>
      <DonnaWhisper level={voice}/>
      <TodoSection style={todoStyle} density={density}/>
      <TrackerPair/>
      <NudgeGrid/>

      <div style={{
        textAlign: 'center',
        fontFamily: D.sans, fontSize: 11, letterSpacing: '0.14em',
        textTransform: 'uppercase', color: D.ink400, fontWeight: 500,
        padding: '8px 0',
      }}>I'm listening · tap to talk</div>
    </div>
  );
}

// ── Tracker sheets ─────────────────────────────────────────────────────────
function SheetShell({ title, subtitle, right, children, accent = D.rust700 }) {
  return (
    <div style={{ background: D.paper100, minHeight: '100%', paddingTop: 54, paddingBottom: 48 }}>
      <div style={{ display: 'flex', justifyContent: 'center', paddingBottom: 14 }}>
        <div style={{ width: 40, height: 4, borderRadius: 3, background: D.borderStrong }}/>
      </div>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
        padding: '0 20px 14px', borderBottom: `1px solid ${D.border}`,
      }}>
        <div>
          <div style={{
            fontFamily: D.serif, fontSize: 26, lineHeight: 1.1,
            letterSpacing: '-0.02em', color: D.ink900, fontWeight: 500,
          }}>{title}</div>
          <div style={{ fontFamily: D.sans, fontSize: 13, color: D.ink500, marginTop: 4 }}>{subtitle}</div>
        </div>
        <span style={{
          fontFamily: D.sans, fontSize: 11, color: D.ink400, fontWeight: 500, marginTop: 8,
        }}>{right}</span>
      </div>
      <div style={{ paddingTop: 18 }}>{children}</div>
    </div>
  );
}

function SheetSection({ title, children, tone = D.ink900 }) {
  return (
    <div style={{ margin: '22px 20px 0' }}>
      <div style={{ paddingBottom: 8, borderBottom: `1px solid ${D.border}` }}>
        <h3 style={{
          margin: 0, fontFamily: D.serif, fontWeight: 500, fontSize: 17,
          letterSpacing: '-0.01em', color: tone,
        }}>{title}</h3>
      </div>
      <div style={{ marginTop: 10 }}>{children}</div>
    </div>
  );
}

function HistoryRow({ t, l, m }) {
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '44px 1fr', gap: 14,
      padding: '9px 0', borderBottom: `1px solid ${D.border}`,
      alignItems: 'baseline',
    }}>
      <span style={{
        fontFamily: D.sans, fontSize: 12, color: D.ink500,
        fontVariantNumeric: 'tabular-nums',
      }}>{t}</span>
      <div>
        <div style={{ fontFamily: D.sans, fontSize: 14, fontWeight: 500, color: D.ink900 }}>{l}</div>
        <div style={{ fontFamily: D.sans, fontSize: 12.5, color: D.ink500, marginTop: 2 }}>{m}</div>
      </div>
    </div>
  );
}

function Note({ body }) {
  return (
    <div style={{
      padding: '10px 12px', background: D.paper200,
      borderLeft: `2px solid ${D.rust700}`, borderRadius: 2,
      fontFamily: D.sans, fontSize: 13.5, lineHeight: 1.5, color: D.ink900,
      marginBottom: 8,
    }}>{body}</div>
  );
}

function Bars({ data, max, labels, highlight, accent = D.rust700, dim = D.paper400 }) {
  return (
    <div>
      <div style={{
        display: 'grid', gridTemplateColumns: `repeat(${data.length}, 1fr)`,
        gap: 8, alignItems: 'end', height: 92,
        paddingBottom: 6, borderBottom: `1px solid ${D.border}`,
      }}>
        {data.map((v, i) => (
          <div key={i} style={{
            height: `${(v / max) * 100}%`,
            minHeight: v === 0 ? 0 : 4,
            background: i === highlight ? accent : dim,
            borderRadius: 2,
          }}/>
        ))}
      </div>
      <div style={{
        display: 'grid', gridTemplateColumns: `repeat(${data.length}, 1fr)`,
        gap: 8, marginTop: 8,
      }}>
        {labels.map((l, i) => (
          <div key={i} style={{
            fontFamily: D.sans, fontSize: 11, textAlign: 'center', fontWeight: 500,
            color: i === highlight ? accent : D.ink400,
          }}>{l}</div>
        ))}
      </div>
    </div>
  );
}

function Ring({ value, color, size = 92 }) {
  const r = size / 2 - 6;
  const c = 2 * Math.PI * r;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <circle cx={size/2} cy={size/2} r={r} stroke={D.paper400} strokeWidth="5" fill="none"/>
      <circle cx={size/2} cy={size/2} r={r}
        stroke={color} strokeWidth="5" fill="none" strokeLinecap="round"
        strokeDasharray={`${value * c} ${c}`}
        transform={`rotate(-90 ${size/2} ${size/2})`}/>
      <text x={size/2} y={size/2 + 4}
        textAnchor="middle" fontFamily={D.serif}
        fontSize={18} fontWeight={500} fill={color}>
        {Math.round(value * 100)}%
      </text>
    </svg>
  );
}

function LogCTA({ label, bg = D.ink900, fg = D.paper100 }) {
  return (
    <div style={{
      margin: '18px 16px 0', padding: '13px 16px', borderRadius: 10,
      background: bg, color: fg,
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      fontFamily: D.sans, fontSize: 14.5, fontWeight: 500, letterSpacing: '-0.005em',
    }}>
      <span>{label}</span>
      <LI.plus size={14} c={fg}/>
    </div>
  );
}

function HydrationSheet() {
  const GOAL = 8, CURRENT = 2;
  return (
    <SheetShell title="Hydration" subtitle="2 of 8 glasses" right="Today">
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(8, 1fr)', gap: 6, margin: '0 16px' }}>
        {Array.from({ length: GOAL }).map((_, i) => {
          const filled = i < CURRENT;
          return (
            <div key={i} style={{
              aspectRatio: '1/1.35', borderRadius: 3,
              border: `1.25px solid ${filled ? D.rust700 : D.borderStrong}`,
              background: filled ? `linear-gradient(180deg, transparent 30%, ${D.rust700} 30%)` : 'transparent',
              display: 'flex', alignItems: 'flex-end', justifyContent: 'center',
              fontFamily: D.sans, fontSize: 10, fontWeight: 500,
              color: filled ? D.paper100 : D.ink400, paddingBottom: 3,
            }}>{i + 1}</div>
          );
        })}
      </div>
      <LogCTA label="Log a glass" bg={D.rust700}/>
      <SheetSection title="Last seven days">
        <Bars data={[5, 7, 8, 4, 6, 8, 2]} max={8} labels={['S','M','T','W','T','F','S']} highlight={6}/>
      </SheetSection>
      <SheetSection title="Today">
        <HistoryRow t="9:45"  l="First glass"  m="After your coffee"/>
        <HistoryRow t="11:20" l="Second glass" m="On your walk down Marine Drive"/>
      </SheetSection>
      <SheetSection title="What I've noticed">
        <Note body="You're steadier on days you walk before ten. Tuesday was a good day."/>
        <Note body="You almost never drink water after seven. That's alright."/>
      </SheetSection>
    </SheetShell>
  );
}

function CalorieSheet() {
  return (
    <SheetShell title="Calories" subtitle="1,240 of 2,200" right="Today" accent={D.amber}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 18, margin: '0 16px' }}>
        <Ring value={0.56} color={D.amber}/>
        <div>
          <div style={{
            fontFamily: D.serif, fontWeight: 500, fontSize: 32,
            lineHeight: 1, letterSpacing: '-0.02em', color: D.ink900,
            fontVariantNumeric: 'tabular-nums',
          }}>1,240</div>
          <div style={{ fontFamily: D.sans, fontSize: 12, color: D.ink500, marginTop: 6 }}>
            960 left · P 68g · C 140g · F 40g
          </div>
        </div>
      </div>
      <LogCTA label="Log a meal" bg={D.amber}/>
      <SheetSection title="Today" tone={D.ink900}>
        <HistoryRow t="8:10" l="Poha with masala chai" m="320 kcal · breakfast"/>
        <HistoryRow t="1:40" l="Chicken bowl"          m="620 kcal · lunch, the usual spot"/>
        <HistoryRow t="4:05" l="Cutting chai, biscuit" m="300 kcal · desk snack"/>
      </SheetSection>
      <SheetSection title="Last seven days">
        <Bars data={[2100, 2300, 1900, 2200, 1800, 1240, 0]} max={2600} labels={['S','M','T','W','T','F','S']} highlight={5} accent={D.amber}/>
      </SheetSection>
      <SheetSection title="What I've noticed">
        <Note body="Your weekday lunches are the same. I'll log chicken bowl for you unless you say otherwise."/>
        <Note body="You skip dinner on Fridays. Worth a snack around seven?"/>
      </SheetSection>
    </SheetShell>
  );
}

function ExpenseSheet() {
  return (
    <SheetShell title="Spend" subtitle="₹ 420 today · ₹ 8,200 this week" right="Apr 14 – 20">
      <div style={{ display: 'flex', alignItems: 'center', gap: 18, margin: '0 16px' }}>
        <Ring value={0.62} color={D.rust700}/>
        <div>
          <div style={{
            fontFamily: D.serif, fontWeight: 500, fontSize: 32,
            lineHeight: 1, letterSpacing: '-0.02em', color: D.ink900,
            fontVariantNumeric: 'tabular-nums',
          }}>₹ 8,200</div>
          <div style={{ fontFamily: D.sans, fontSize: 12, color: D.ink500, marginTop: 6 }}>
            Food 52% · Transit 21% · Coffee 14% · Other 13%
          </div>
        </div>
      </div>
      <LogCTA label="Add an expense" bg={D.ink900}/>
      <SheetSection title="Today">
        <HistoryRow t="8:22"  l="Uber · Bandra to office" m="₹ 180 · transit"/>
        <HistoryRow t="11:05" l="Blue Tokai flat white"   m="₹ 240 · coffee"/>
        <HistoryRow t="—"     l="Zomato, pending"         m="~ ₹ 350 · food"/>
      </SheetSection>
      <SheetSection title="Last seven days">
        <Bars data={[1400, 900, 1600, 1100, 1300, 420, 0]} max={1800} labels={['S','M','T','W','T','F','S']} highlight={5}/>
      </SheetSection>
      <SheetSection title="What I've noticed">
        <Note body="Coffee is ₹ 240 a day, five days a week. That's ₹ 4,800 a month. Just so you know."/>
        <Note body="Your Fridays are usually your lightest spend days."/>
      </SheetSection>
    </SheetShell>
  );
}

Object.assign(window, {
  DashboardContent, HydrationSheet, CalorieSheet, ExpenseSheet,
});
