'use client';

import { motion } from 'framer-motion';
import type { Block, DashboardPlan } from '@/lib/plan';
import { validatePlan } from '@/lib/plan';
import TopBar from './TopBar';
import CalendarShapeBlock from './blocks/CalendarShapeBlock';
import CelebrationBlock from './blocks/CelebrationBlock';
import ConfrontationBlock from './blocks/ConfrontationBlock';
import FooterBlock from './blocks/FooterBlock';
import HeroBlock from './blocks/HeroBlock';
import NudgeGridBlock from './blocks/NudgeGridBlock';
import OpenLoopsBlock from './blocks/OpenLoopsBlock';
import PermissionBlock from './blocks/PermissionBlock';
import ReflectionBlock from './blocks/ReflectionBlock';
import ThesisBlock from './blocks/ThesisBlock';
import TodoListBlock from './blocks/TodoListBlock';
import TrackerGridBlock from './blocks/TrackerGridBlock';
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

  return (
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
      return `${block.type}:${block.title}:${idx}`;
    default:
      return `${block.type}:${idx}`;
  }
}
