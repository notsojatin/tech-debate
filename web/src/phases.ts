import type { CurrentStep } from './types';

const FIXED_LABELS: Record<string, string> = {
  research: 'Research',
  openings: 'Openings',
  closings: 'Closings',
  judge: 'Verdict',
  render: 'Audio',
  done: 'Done',
};

const FIXED_HEADINGS: Record<string, string> = {
  openings: 'Opening Statements',
  closings: 'Closing Lines',
};

export function rebuttalRound(phase: string): number | null {
  const m = /^rebuttal_(\d+)$/.exec(phase);
  return m ? Number(m[1]) : null;
}

/** Short label for timelines and status lines: "Openings", "Rebuttal 7". */
export function formatPhaseLabel(phase: string): string {
  const n = rebuttalRound(phase);
  if (n !== null) return `Rebuttal ${n}`;
  return FIXED_LABELS[phase] ?? phase;
}

/** Section heading in the transcript: "Opening Statements", "Rebuttals — Round 7". */
export function formatPhaseHeading(phase: string): string {
  const n = rebuttalRound(phase);
  if (n !== null) return `Rebuttals — Round ${n}`;
  return FIXED_HEADINGS[phase] ?? formatPhaseLabel(phase);
}

/** Phases in which the debaters speak, in plan order. */
export function speakingPhases(plan: string[]): string[] {
  return plan.filter((p) => p === 'openings' || p === 'closings' || rebuttalRound(p) !== null);
}

export function sideName(side?: string): string {
  return side === 'pro' ? 'Pro' : side === 'con' ? 'Con' : 'Judge';
}

export function describeStep(step: CurrentStep | null): string {
  if (!step) return 'Ready';
  switch (step.type) {
    case 'starting':
    case 'service_status':
    case 'service_log':
    case 'topic_gate':
    case 'debate_cancelling':
      return step.message || 'Preparing the debate…';
    case 'phase_start':
      return `Starting ${formatPhaseLabel(step.phase || '').toLowerCase()}`;
    case 'counter_claim':
      return 'Wrote the opposing claim used to check each side stays on its stance';
    case 'research_status':
      return step.status === 'generating_queries'
        ? `${sideName(step.side)} is writing search queries`
        : `Searching the web for ${sideName(step.side)} evidence`;
    case 'research_queries':
      return `${sideName(step.side)} search queries ready`;
    case 'turn_attempt': {
      const who = sideName(step.side);
      const phase = formatPhaseLabel(step.phase || '').toLowerCase();
      const att = step.attempt && step.max_attempts ? ` · attempt ${step.attempt}/${step.max_attempts}` : '';
      if (step.status === 'generating') return `${who} is drafting ${phase}${att}`;
      if (step.status === 'stance_check') return `Judge is checking ${who} stayed on side${att}`;
      if (step.status === 'rejected') {
        return `${who}'s draft was sent back (${step.errors?.[0] || 'validation failed'})${att}`;
      }
      return `${who} is on the floor`;
    }
    case 'turn_complete':
      return `${sideName(step.side)} finished; recording the voice`;
    case 'judge_start':
      return 'The judge is reading the full transcript (twice, sides swapped)';
    case 'judge_complete':
      return 'Verdict reached; preparing the final audio';
    case 'render_status':
      return 'Stitching the full recording and captions';
    case 'render_complete':
    case 'debate_done':
      return 'Debate complete';
    default:
      return step.message || 'Working…';
  }
}
