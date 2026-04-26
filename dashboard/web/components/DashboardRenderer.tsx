'use client';

import { motion } from 'framer-motion';
import type { Block, DashboardPlan, Row } from '@/lib/plan';
import { validatePlan } from '@/lib/plan';
import { renderBlock } from '@/lib/registry';
import { Cell, RowGrid } from './RowGrid';
import { Intro } from './Intro';
import { ScreenRoot } from './ds';
import TopBar from './TopBar';
import MumbaiLineArt from './MumbaiLineArt';
import CalendarShapeBlock from './blocks/CalendarShapeBlock';
import CelebrationBlock from './blocks/CelebrationBlock';
import ConfrontationBlock from './blocks/ConfrontationBlock';
import FooterBlock from './blocks/FooterBlock';
import HeroBlock from './blocks/HeroBlock';
import NewsBriefBlock from './blocks/NewsBriefBlock';
import NudgeGridBlock from './blocks/NudgeGridBlock';
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

  // New path: row-based composition (visual contract §4).
  // Triggered when the plan ships rows[]. Existing legacy fixtures without
  // rows[] continue to flow through the linear blocks[] path below.
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
    case 'footer':          return <FooterBlock          spec={block} />;
    default: {
      const _exhaustive: never = block;
      return _exhaustive;
    }
  }
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
