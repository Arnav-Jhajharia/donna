'use client';

import { useEffect, useState } from 'react';
import MumbaiLineArt from '../MumbaiLineArt';
import SingaporeLineArt from '../SingaporeLineArt';
import TapToTalk from '../TapToTalk';
import type { HeroBlock as HeroBlockSpec } from '@/lib/plan';

function formatLocal(d: Date): string {
  const day = d.toLocaleDateString('en-US', { weekday: 'long' });
  const dayNum = d.getDate();
  const month = d.toLocaleDateString('en-US', { month: 'long' });
  const hour = d.getHours();
  const min = d.getMinutes();
  const period = hour >= 12 ? 'pm' : 'am';
  const h12 = hour % 12 || 12;
  return `${day} · ${dayNum} ${month} · ${h12}:${min.toString().padStart(2, '0')} ${period}`;
}

export default function HeroBlock({ spec }: { spec: HeroBlockSpec }) {
  // SSR uses spec.date (the LLM-emitted compose-time string) so the first
  // paint matches between server and client. On mount the client switches
  // to a live ticker — the hero feels current, not frozen at compose time.
  const [now, setNow] = useState(spec.date);

  useEffect(() => {
    const tick = () => setNow(formatLocal(new Date()));
    tick();
    const id = setInterval(tick, 30_000);
    return () => clearInterval(id);
  }, []);

  return (
    <TapToTalk
      primer="what's on for me right now?"
      decoration="block"
      style={{
        margin: '0 16px',
        borderRadius: 14,
        overflow: 'hidden',
        background: 'var(--bg-inset)',
        border: '1px solid var(--border-hairline)',
      }}
    >
      <div style={{ padding: '22px 22px 10px' }}>
        <div
          suppressHydrationWarning
          style={{
            fontSize: 11,
            letterSpacing: '0.14em',
            textTransform: 'uppercase',
            color: 'var(--fg-placeholder)',
            fontWeight: 500,
          }}
        >
          {now}
        </div>
        <div
          style={{
            fontFamily: 'var(--font-serif)',
            fontWeight: 400,
            fontSize: 32,
            lineHeight: 1.08,
            letterSpacing: '-0.02em',
            color: 'var(--fg-primary)',
            marginTop: 8,
          }}
        >
          {spec.greeting}
        </div>
        <div style={{ fontSize: 13, color: 'var(--fg-muted)', marginTop: 10, letterSpacing: '-0.005em' }}>
          {spec.subtext}
        </div>
      </div>
      {spec.illustration !== 'none' && (
        <div style={{ marginTop: 8 }}>
          {spec.illustration === 'singapore' ? <SingaporeLineArt /> : <MumbaiLineArt />}
        </div>
      )}
    </TapToTalk>
  );
}
