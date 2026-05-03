'use client';

import { useState } from 'react';
import { motion } from 'framer-motion';
import type { Block, DashboardPage, DashboardPlan, Row } from '@/lib/plan';
import { validatePlan } from '@/lib/plan';
import { renderBlock } from '@/lib/registry';
import { PlaceholderFrame } from './Frame';
import { Cell, RowGrid } from './RowGrid';
import { Intro } from './Intro';
import { ScreenRoot } from './ds';
import TopBar from './TopBar';
import MumbaiLineArt from './MumbaiLineArt';
import { DomainRail, ALL_DOMAINS } from './DomainRail';
import CalendarShapeBlock from './blocks/CalendarShapeBlock';
import CelebrationBlock from './blocks/CelebrationBlock';
import ConfrontationBlock from './blocks/ConfrontationBlock';
import FooterBlock from './blocks/FooterBlock';
import HeroBlock from './blocks/HeroBlock';
import NewsBriefBlock from './blocks/NewsBriefBlock';
import NoteBlock from './blocks/NoteBlock';
import NudgeGridBlock from './blocks/NudgeGridBlock';
import CatTracker from './blocks/catalogue/CatTracker';
import CatCapability from './blocks/catalogue/CatCapability';
import {
  CatWatch,
  CatBrief,
  CatPrep,
  CatSchedule,
  CatStreak,
  CatPerson,
  CatReminder,
  CatQuickLog,
  CatPick,
  CatOffer,
  CatDraft,
  CatDecision,
  CatConfront,
  CatReflection,
  CatOpenLoop,
  CatPermission,
  CatRead,
} from './blocks/catalogue/CatBlocks';
import OpenLoopsBlock from './blocks/OpenLoopsBlock';
import PermissionBlock from './blocks/PermissionBlock';
import ReflectionBlock from './blocks/ReflectionBlock';
import RelationshipBlock from './blocks/RelationshipBlock';
import RemindersBlock from './blocks/RemindersBlock';
import ThesisBlock from './blocks/ThesisBlock';
import TodoListBlock from './blocks/TodoListBlock';
import TrackerGridBlock from './blocks/TrackerGridBlock';
import TrackerStarterBlock from './blocks/TrackerStarterBlock';
import WeatherOfYouBlock from './blocks/WeatherOfYouBlock';
import WhisperBlock from './blocks/WhisperBlock';
import WitnessBlock from './blocks/WitnessBlock';

const fadeUp = {
  hidden: { opacity: 0, y: 8 },
  visible: { opacity: 1, y: 0 },
};

export default function DashboardRenderer({ plan }: { plan: DashboardPlan }) {
  if (process.env.NODE_ENV !== 'production') {
    const issues = validatePlan(plan);
    for (const i of issues) {
      // eslint-disable-next-line no-console
      console.warn(`[plan ${i.severity}] ${i.rule}: ${i.message}`);
    }
  }

  // Catalogue v2: paged composition. Three pages — now / today / hold.
  // Renderer prefers `pages[]` when present; the flat `blocks[]` is then
  // legacy-only and ignored. Each page renders top to bottom; user swipes
  // (or scrolls horizontally on mobile) between them.
  if (plan.pages && plan.pages.length > 0) {
    return <PagedDashboard plan={plan} />;
  }

  // Legacy path A: row-based composition (visual contract §4).
  if (plan.rows && plan.rows.length > 0) {
    return (
      <ScreenRoot>
        <motion.div
          initial="hidden"
          animate="visible"
          transition={{ staggerChildren: 0.06, delayChildren: 0.04 }}
          style={{
            background: 'var(--bg-canvas)',
            paddingTop: 28,
            paddingBottom: 48,
            paddingLeft: 'var(--space-5)',
            paddingRight: 'var(--space-5)',
          }}
        >
          <motion.div variants={fadeUp} transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}>
            <TopBar initial={plan.user.initial} />
          </motion.div>

          {plan.intro && (
            <motion.div variants={fadeUp} transition={{ duration: 0.45, ease: [0.2, 0.8, 0.2, 1] }} style={{ marginTop: 16, marginBottom: 32 }}>
              <Intro
                kicker={plan.intro.kicker}
                greetingPrefix={plan.intro.greetingPrefix}
                accent={plan.intro.accent}
                greetingSuffix={plan.intro.greetingSuffix}
                greeting={plan.intro.greeting}
                place={plan.intro.place}
                illustration={plan.intro.illustrationId === 'mumbai' ? <MumbaiLineArt /> : null}
              />
            </motion.div>
          )}

          {plan.rows.map((row, idx) => (
            <RowSection key={`row-${idx}`} row={row} idx={idx} last={idx === plan.rows!.length - 1} />
          ))}
        </motion.div>
      </ScreenRoot>
    );
  }

  // Legacy path: linear blocks[]. Kept for fixtures not yet migrated.
  return (
    <ScreenRoot>
      <motion.div
        initial="hidden"
        animate="visible"
        transition={{ staggerChildren: 0.08, delayChildren: 0.05 }}
        style={{ background: 'var(--bg-canvas)', paddingTop: 28, paddingBottom: 48 }}
      >
        <motion.div variants={fadeUp} transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}>
          <TopBar initial={plan.user.initial} />
        </motion.div>
        {plan.blocks.map((block, idx) => (
          <motion.div
            key={blockKey(block, idx)}
            variants={fadeUp}
            transition={{ duration: 0.45, ease: [0.2, 0.8, 0.2, 1] }}
          >
            <BlockSwitch block={block} />
          </motion.div>
        ))}
      </motion.div>
    </ScreenRoot>
  );
}

function RowSection({ row, idx, last }: { row: Row; idx: number; last: boolean }) {
  return (
    <motion.div variants={fadeUp} transition={{ duration: 0.45, ease: [0.2, 0.8, 0.2, 1] }}>
      {row.title && (
        <div className="section-title">
          <h3 className="section-title__h">{row.title}</h3>
          {row.meta && <span className="section-title__meta">{row.meta}</span>}
        </div>
      )}
      <RowGrid last={last}>
        {row.cols.map((cell, cidx) => (
          <Cell key={`row-${idx}-cell-${cidx}`} size={cell.size}>
            {renderBlock(cell.block)}
          </Cell>
        ))}
      </RowGrid>
    </motion.div>
  );
}

function BlockSwitch({ block }: { block: Block }) {
  switch (block.type) {
    case 'thesis':          return <ThesisBlock          spec={block} />;
    case 'hero':            return <HeroBlock            spec={block} />;
    case 'whisper':         return <WhisperBlock         spec={block} />;
    case 'witness':         return <WitnessBlock         spec={block} />;
    case 'confrontation':   return <ConfrontationBlock   spec={block} />;
    case 'celebration':     return <CelebrationBlock     spec={block} />;
    case 'reflection':      return <ReflectionBlock      spec={block} />;
    case 'open-loops':      return <OpenLoopsBlock       spec={block} />;
    case 'weather-of-you':  return <WeatherOfYouBlock    spec={block} />;
    case 'calendar-shape':  return <CalendarShapeBlock   spec={block} />;
    case 'todo-list':       return <TodoListBlock        spec={block} />;
    case 'tracker-grid':    return <TrackerGridBlock     spec={block} />;
    case 'nudge-grid':      return <NudgeGridBlock       spec={block} />;
    case 'permission':      return <PermissionBlock      spec={block} />;
    case 'reminders':       return <RemindersBlock       spec={block} />;
    case 'tracker-starter': return <TrackerStarterBlock  spec={block} />;
    case 'relationship':    return <RelationshipBlock    spec={block} />;
    case 'news-brief':      return <NewsBriefBlock       spec={block} />;
    case 'note':            return <NoteBlock            spec={block} />;
    case 'footer':          return <FooterBlock          spec={block} />;
    // catalogue archetypes #04–#21
    case 'c-tracker':       return <CatTracker           spec={block} />;
    case 'c-watch':         return <CatWatch             spec={block} />;
    case 'c-brief':         return <CatBrief             spec={block} />;
    case 'c-prep':          return <CatPrep              spec={block} />;
    case 'c-schedule':      return <CatSchedule          spec={block} />;
    case 'c-streak':        return <CatStreak            spec={block} />;
    case 'c-person':        return <CatPerson            spec={block} />;
    case 'c-reminder':      return <CatReminder          spec={block} />;
    case 'c-quicklog':      return <CatQuickLog          spec={block} />;
    case 'c-pick':          return <CatPick              spec={block} />;
    case 'c-offer':         return <CatOffer             spec={block} />;
    case 'c-draft':         return <CatDraft             spec={block} />;
    case 'c-decision':      return <CatDecision          spec={block} />;
    case 'c-confront':      return <CatConfront          spec={block} />;
    case 'c-reflection':    return <CatReflection        spec={block} />;
    case 'c-openloop':      return <CatOpenLoop          spec={block} />;
    case 'c-permission':    return <CatPermission        spec={block} />;
    case 'c-read':          return <CatRead              spec={block} />;
    case 'c-capability':    return <CatCapability        spec={block} />;
    default: {
      // Forward-compat: if the backend emits a block type the deployed
      // frontend hasn't shipped yet, render a placeholder instead of
      // letting React try to render the raw spec (would fail with
      // error #31 — "objects are not valid as a React child"). The
      // ``never`` annotation keeps the compile-time exhaustive check.
      const unknown = block as { type?: string };
      void (block as never);
      return <PlaceholderFrame kind={String(unknown.type ?? 'unknown')} />;
    }
  }
}

// ── Paged dashboard (catalogue v2) ────────────────────────────────────────
//
// Three pages, swipeable. The first page (`now`) carries the hero block;
// later pages have their own kicker + thesis. A small dot indicator at
// the bottom shows which page you're on.

function PagedDashboard({ plan }: { plan: DashboardPlan }) {
  const pages = plan.pages ?? [];
  const [active, setActive] = useState(0);
  return (
    <ScreenRoot>
      <div
        style={{
          background: 'var(--bg-canvas)',
          paddingTop: 28,
          paddingBottom: 12,
        }}
      >
        <TopBar initial={plan.user.initial} />
      </div>
      <div
        style={{
          background: 'var(--bg-canvas)',
          display: 'flex',
          overflowX: 'auto',
          scrollSnapType: 'x mandatory',
          scrollBehavior: 'smooth',
          paddingBottom: 24,
        }}
        onScroll={(e) => {
          const el = e.currentTarget;
          const w = el.clientWidth || 1;
          const idx = Math.round(el.scrollLeft / w);
          if (idx !== active) setActive(idx);
        }}
      >
        {pages.map((page, idx) => (
          <PageColumn key={page.id ?? idx} page={page} index={idx} />
        ))}
      </div>
      <PageDots count={pages.length} active={active} labels={pages.map((p) => p.id ?? '')} />
    </ScreenRoot>
  );
}

function PageColumn({ page, index }: { page: DashboardPage; index: number }) {
  const isTodayPage = page.id === 'today';
  // Page 1 ("now") is a single-screen surface — the editorial cover. It
  // must FIT in the viewport without scrolling. Page 2 ("today") is the
  // operational view (rails of content) and stays scrollable. The
  // outer page container handles horizontal swipe; vertical overflow
  // is per-page.
  return (
    <motion.section
      initial="hidden"
      animate="visible"
      transition={{ staggerChildren: 0.06, delayChildren: 0.04 }}
      style={{
        flex: '0 0 100%',
        minWidth: '100%',
        scrollSnapAlign: 'start',
        // 100dvh on mobile collapses with the URL bar so we don't get a
        // nasty bottom-of-screen jump. Falls back to 100vh on browsers
        // that don't support dvh.
        height: isTodayPage ? 'auto' : '100dvh',
        overflowY: isTodayPage ? 'visible' : 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Page kicker + thesis (above blocks). The hero block carries its own
          date+greeting+place, so we only render the kicker/thesis when the
          page actually supplies them — and never duplicate them on the now
          page when a hero is the first block. */}
      {(page.kicker || page.thesis) && !pageStartsWithHero(page) && (
        <motion.div
          variants={fadeUp}
          transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
          style={{ padding: '4px 22px 16px' }}
        >
          {page.kicker && (
            <div
              style={{
                fontSize: 11,
                letterSpacing: '0.18em',
                textTransform: 'uppercase',
                color: 'var(--fg-placeholder)',
                fontWeight: 500,
              }}
            >
              {page.kicker}
            </div>
          )}
          {page.thesis && (
            <div
              style={{
                fontFamily: 'var(--font-serif)',
                fontWeight: 400,
                fontSize: 22,
                lineHeight: 1.2,
                letterSpacing: '-0.015em',
                color: 'var(--fg-primary)',
                marginTop: 6,
              }}
            >
              {page.thesis}
            </div>
          )}
        </motion.div>
      )}
      {isTodayPage ? (
        <DomainRailedPage page={page} />
      ) : (
        page.blocks.map((block, bidx) => (
          <motion.div
            key={`${page.id}-${blockKey(block, bidx)}`}
            variants={fadeUp}
            transition={{ duration: 0.45, ease: [0.2, 0.8, 0.2, 1] }}
          >
            <BlockSwitch block={block} />
          </motion.div>
        ))
      )}
    </motion.section>
  );
}

// Page 2 ("today") groups blocks by their `domain` tag into rails. Blocks
// without a domain fall into a residual "today" rail at the top so they
// don't disappear when the composer hasn't tagged them yet.
function DomainRailedPage({ page }: { page: DashboardPage }) {
  const grouped = groupByDomain(page.blocks);
  return (
    <div>
      {ALL_DOMAINS.map((domain) => {
        const blocks = grouped[domain] || [];
        return (
          <DomainRail
            key={domain}
            domain={domain}
            hasContent={blocks.length > 0}
          >
            {blocks.map((block, bidx) => (
              <motion.div
                key={`${page.id}-${domain}-${blockKey(block, bidx)}`}
                variants={fadeUp}
                transition={{ duration: 0.45, ease: [0.2, 0.8, 0.2, 1] }}
              >
                <BlockSwitch block={block} />
              </motion.div>
            ))}
          </DomainRail>
        );
      })}
    </div>
  );
}

function groupByDomain(
  blocks: Block[],
): Partial<Record<import('@/lib/plan').Domain, Block[]>> {
  const out: Partial<Record<import('@/lib/plan').Domain, Block[]>> = {};
  for (const b of blocks) {
    const d = (b as { domain?: import('@/lib/plan').Domain }).domain;
    const key: import('@/lib/plan').Domain =
      d && (ALL_DOMAINS as readonly string[]).includes(d) ? d : inferDomainFromBlock(b);
    if (!out[key]) out[key] = [];
    out[key]!.push(b);
  }
  return out;
}

// Best-effort domain inference for blocks whose composer didn't tag them.
// Only used as a fallback so rails don't ghost-empty during the prompt
// rollout. Once the composer reliably emits ``domain``, this is dead.
function inferDomainFromBlock(b: Block): import('@/lib/plan').Domain {
  const t = b.type;
  if (t === 'c-tracker' || t === 'c-streak') return 'body';
  if (t === 'c-person' || t === 'relationship') return 'people';
  if (
    t === 'c-openloop' ||
    t === 'c-prep' ||
    t === 'c-draft' ||
    t === 'c-decision' ||
    t === 'c-permission' ||
    t === 'c-capability' ||
    t === 'c-confront' ||
    t === 'c-watch'
  )
    return 'work';
  if (t === 'c-reflection' || t === 'c-pick' || t === 'c-read' || t === 'c-quicklog' || t === 'c-brief') return 'mind';
  if (t === 'c-schedule' || t === 'c-reminder' || t === 'reminders') return 'day';
  return 'work';
}

function pageStartsWithHero(page: DashboardPage): boolean {
  return Boolean(page.blocks[0] && page.blocks[0].type === 'hero');
}

function PageDots({ count, active, labels }: { count: number; active: number; labels: string[] }) {
  if (count <= 1) return null;
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'center',
        gap: 8,
        padding: '8px 0 28px',
      }}
    >
      {Array.from({ length: count }).map((_, i) => {
        const isActive = i === active;
        return (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span
              aria-hidden
              style={{
                width: isActive ? 18 : 6,
                height: 6,
                borderRadius: 999,
                background: isActive ? 'var(--rust-700)' : 'var(--paper-400)',
                transition: 'width 200ms ease, background 200ms ease',
              }}
            />
            {isActive && labels[i] && (
              <span
                style={{
                  fontSize: 10,
                  letterSpacing: '0.14em',
                  textTransform: 'uppercase',
                  color: 'var(--rust-700)',
                  fontWeight: 600,
                }}
              >
                {labels[i]}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

function blockKey(block: Block, idx: number): string {
  switch (block.type) {
    case 'todo-list':
    case 'tracker-grid':
    case 'nudge-grid':
    case 'open-loops':
    case 'reflection':
    case 'calendar-shape':
    case 'reminders':
    case 'relationship':
    case 'news-brief':
      return `${block.type}:${block.title}:${idx}`;
    case 'tracker-starter':
      return `${block.type}:${block.trackerName}:${idx}`;
    default:
      return `${block.type}:${idx}`;
  }
}
