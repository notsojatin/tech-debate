import { useMemo, useRef } from 'react';
import type { SpeechPos } from '../hooks/useSpeech';
import { formatPhaseHeading, sideName, speakingPhases } from '../phases';
import type { DebateDetail, EvidenceItem, SrtCue } from '../types';
import TurnEntry from './TurnEntry';

interface Props {
  detail: DebateDetail;
  evidenceById: Record<string, EvidenceItem>;
  speech: SpeechPos | null;
  cueByKey: Map<string, SrtCue>;
  drafting: { phase: string; side: 'pro' | 'con'; status: string } | null;
  onSentence: (turnIdx: number, sentIdx: number) => void;
  onPlayTurn: (turnIdx: number) => void;
  onOpenNotes: (citeId: string) => void;
}

const NO_SENTENCES = new Set<number>();

/** The debate written out on one ruled sheet, phase by phase. */
export default function Transcript({ detail, evidenceById, speech, cueByKey, drafting, onSentence, onPlayTurn, onOpenNotes }: Props) {
  const { state } = detail;
  const running = detail.status === 'running' || detail.status === 'cancelling';

  // Turns present at first render are history; later ones were written live and get inked in.
  const initialCount = useRef<{ id: string; n: number } | null>(null);
  if (!initialCount.current || initialCount.current.id !== detail.id) {
    initialCount.current = { id: detail.id, n: state.turns.length };
  }

  const seekableByTurn = useMemo(() => {
    const map = new Map<number, Set<number>>();
    cueByKey.forEach((_cue, key) => {
      const [t, s] = key.split(':').map(Number);
      if (!map.has(t)) map.set(t, new Set());
      map.get(t)!.add(s);
    });
    return map;
  }, [cueByKey]);

  const segmentTurns = useMemo(
    () => new Set(detail.segments.map((s) => s.turn_index).filter((t): t is number => t !== null)),
    [detail.segments],
  );

  const phases = speakingPhases(detail.phases_plan);
  const shown = phases.filter(
    (p) => state.turns.some((t) => t.phase === p) || (running && drafting?.phase === p),
  );

  return (
    <section className="sheet ruled py-8" aria-label="Transcript">
      {shown.length === 0 && (
        <p className="pl-16 pr-6 hand text-2xl leading-8 text-pencil">
          {running
            ? 'The speeches will be written here once the research is done…'
            : 'Nothing was said in this debate yet.'}
        </p>
      )}

      {shown.map((phase) => {
        const turns = state.turns.map((t, i) => ({ t, i })).filter(({ t }) => t.phase === phase);
        const draftingHere = running && drafting?.phase === phase && !turns.some(({ t }) => t.side === drafting.side);
        return (
          <div key={phase} id={`phase-${phase}`} className="scroll-mt-48">
            <h3 className="pl-16 pr-6 hand text-3xl font-bold leading-[4rem] text-ink">{formatPhaseHeading(phase)}</h3>
            {turns.map(({ t, i }) => (
              <TurnEntry
                key={i}
                turn={t}
                index={i}
                evidenceById={evidenceById}
                speech={speech?.turnIdx === i ? speech : null}
                seekable={seekableByTurn.get(i) ?? NO_SENTENCES}
                fresh={i >= initialCount.current!.n}
                canPlay={segmentTurns.has(i)}
                onSentence={onSentence}
                onPlay={onPlayTurn}
                onOpenNotes={onOpenNotes}
              />
            ))}
            {draftingHere && drafting && (
              <div id="turn-drafting" className="relative pl-16 pr-6 py-8 scroll-mt-48">
                <span
                  className={`absolute left-0 w-12 text-center hand text-2xl leading-8 font-bold ${
                    drafting.side === 'pro' ? 'text-pro' : 'text-con'
                  }`}
                >
                  {sideName(drafting.side)}
                </span>
                <div className="flex items-center gap-3 leading-8 text-pencil">
                  <svg viewBox="0 0 60 16" className="scribble w-14 h-4" aria-hidden="true">
                    <path
                      d="M2 10 q5 -9 10 0 t10 0 t10 0 t10 0 t10 0"
                      fill="none"
                      stroke={drafting.side === 'pro' ? 'var(--pro)' : 'var(--con)'}
                      strokeWidth="2"
                      strokeLinecap="round"
                    />
                  </svg>
                  <span className="hand text-xl">{drafting.status}</span>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}
