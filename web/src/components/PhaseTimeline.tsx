import { Check } from 'lucide-react';
import { formatPhaseLabel } from '../phases';

interface Props {
  plan: string[];
  done: string[];
  current: string | null;
  timings: Record<string, number>;
  onJump: (phase: string) => void;
}

/** Research · Openings · R1…Rn · Closings · Verdict, as a hand-ticked checklist you can jump through. */
export default function PhaseTimeline({ plan, done, current, timings, onJump }: Props) {
  const phases = plan.filter((p) => p !== 'render');
  return (
    <ol className="flex items-center gap-1 overflow-x-auto pb-1 -mx-1 px-1" aria-label="Debate progress">
      {phases.map((phase, i) => {
        const isDone = done.includes(phase);
        const isCurrent = phase === current;
        const label = formatPhaseLabel(phase).replace(/^Rebuttal (\d+)$/, 'R$1');
        return (
          <li key={phase} className="flex items-center gap-1 shrink-0">
            {i > 0 && <span className={`w-3 sm:w-5 border-t border-dashed ${isDone ? 'border-ink-soft' : 'border-edge'}`} />}
            <button
              onClick={() => onJump(phase)}
              title={`${formatPhaseLabel(phase)}${timings[phase] !== undefined ? ` · ${timings[phase]}s` : ''}`}
              aria-current={isCurrent ? 'step' : undefined}
              className={`flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-sm transition cursor-pointer border ${
                isCurrent
                  ? 'border-ink text-ink bg-card shadow-sm'
                  : isDone
                  ? 'border-transparent text-ink hover:bg-card'
                  : 'border-transparent text-pencil hover:text-ink-soft'
              }`}
            >
              <span
                className={`grid place-items-center w-4 h-4 rounded-full border ${
                  isDone ? 'border-ink bg-ink text-paper' : isCurrent ? 'border-ink' : 'border-pencil border-dashed'
                }`}
              >
                {isDone && <Check className="w-3 h-3" strokeWidth={3} />}
                {isCurrent && <span className="w-1.5 h-1.5 rounded-full bg-ink animate-pulse" />}
              </span>
              <span className={isCurrent ? 'font-semibold' : ''}>{label}</span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
