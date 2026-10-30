import { memo, useState } from 'react';
import { ExternalLink, Play, TriangleAlert } from 'lucide-react';
import type { SpeechPos } from '../hooks/useSpeech';
import { splitIntoSentences, wordsOf } from '../lib/text';
import type { EvidenceItem, TurnItem } from '../types';

interface Props {
  turn: TurnItem;
  index: number;
  evidenceById: Record<string, EvidenceItem>;
  speech: SpeechPos | null; // set only on the turn being spoken
  seekable: Set<number>; // sentence indexes that have a cue in the full recording
  fresh: boolean; // just written during a live run: ink it in
  canPlay: boolean;
  onSentence: (turnIdx: number, sentIdx: number) => void;
  onPlay: (turnIdx: number) => void;
  onOpenNotes: (citeId: string) => void;
}

const ORDINAL = ['', '1st', '2nd', '3rd'];

function SpokenSentence({ text, progress }: { text: string; progress: number }) {
  const words = wordsOf(text);
  const k = Math.min(words.length, Math.floor(progress * words.length + 0.5));
  return (
    <span className="marker">
      {words.map((w, i) => (
        <span key={i} className={`${i < k ? 'text-ink' : 'text-pencil'} ${i === k - 1 ? 'caret' : ''}`}>
          {w}
          {i < words.length - 1 ? ' ' : ''}
        </span>
      ))}
    </span>
  );
}

function TurnEntry({ turn, index, evidenceById, speech, seekable, fresh, canPlay, onSentence, onPlay, onOpenNotes }: Props) {
  const [openCite, setOpenCite] = useState<string | null>(null);
  const isPro = turn.side === 'pro';
  const tone = isPro ? 'text-pro' : 'text-con';
  const sentences = splitIntoSentences(turn.text);

  return (
    <article
      id={`turn-${index}`}
      className={`relative grid lg:grid-cols-[minmax(0,1fr)_14rem] gap-x-8 pl-16 pr-4 sm:pr-8 py-8 scroll-mt-48 ${
        fresh ? 'ink-in' : ''
      }`}
      aria-label={`${isPro ? 'Pro' : 'Con'} speech`}
    >
      {/* the speaker, written in the margin */}
      <span className={`absolute left-0 w-12 text-center hand text-2xl leading-8 font-bold ${tone}`}>
        {isPro ? 'Pro' : 'Con'}
      </span>

      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-3 leading-8 text-sm">
          <span className="font-mono text-[12px] text-pencil">{turn.model}</span>
          {turn.attempts > 1 && (
            <span className="hand text-base text-judge" title="Drafts rejected by validation before this one">
              {ORDINAL[turn.attempts] ?? `${turn.attempts}th`} draft
            </span>
          )}
          {canPlay && (
            <button
              onClick={() => onPlay(index)}
              className={`inline-flex items-center gap-1 hand text-lg ${tone} hover:underline cursor-pointer`}
              title="Hear this speech"
            >
              <Play className="w-3 h-3 fill-current" /> hear it
            </button>
          )}
        </div>

        {turn.quote && (
          <figure className="card relative my-[calc(1rem-1px)] px-4 -rotate-[0.4deg] max-w-2xl">
            <span aria-hidden="true" className="absolute -top-2 left-8 w-16 h-4 rotate-[-3deg] opacity-70" style={{ background: 'var(--marker)' }} />
            <figcaption className="hand text-base leading-8 text-pencil">
              quoting the other side · {turn.quote_matched ? '✓ word for word' : '~ paraphrased'}
            </figcaption>
            <blockquote className="italic leading-8 text-ink-soft">“{turn.quote}”</blockquote>
          </figure>
        )}

        <p className="text-[1.08rem] leading-8 text-ink">
          {sentences.map((s, si) => {
            const spokenHere = speech?.sentIdx === si;
            const tone =
              speech === null ? '' : si < speech.sentIdx ? 'text-ink' : spokenHere ? '' : 'text-pencil';
            const clickable = seekable.has(si);
            return (
              <span
                key={si}
                onClick={clickable ? () => onSentence(index, si) : undefined}
                className={`${tone} ${clickable ? 'cursor-pointer hover:underline decoration-dotted decoration-pencil underline-offset-4' : ''}`}
                title={clickable ? 'Play from here' : undefined}
              >
                {spokenHere ? <SpokenSentence text={s} progress={speech!.progress} /> : s}
                {si < sentences.length - 1 ? ' ' : ''}
              </span>
            );
          })}
          {turn.cites.length > 0 && (
            <sup className="font-mono text-[11px] text-pencil ml-1">[{turn.cites.join(', ')}]</sup>
          )}
        </p>

        {turn.warnings.length > 0 && (
          <ul className="mt-1">
            {turn.warnings.map((w, i) => (
              <li key={i} className="flex items-start gap-1.5 hand text-base leading-8 text-judge">
                <TriangleAlert className="w-3.5 h-3.5 mt-2.5 shrink-0" /> {w}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* margin notes: the main point and the sources behind it */}
      <aside className="hand text-lg leading-8 text-ink-soft mt-2 lg:mt-0 min-w-0">
        {turn.new_point && (
          <p className="leading-6 pb-2">
            <span className={tone}>↳</span> {turn.new_point}
          </p>
        )}
        {turn.cites.map((id) => {
          const ev = evidenceById[id];
          const open = openCite === id;
          return (
            <div key={id} className="relative">
              <button
                onClick={() => setOpenCite(open ? null : id)}
                aria-expanded={open}
                className={`text-left w-full truncate hover:text-ink cursor-pointer ${open ? 'text-ink' : ''}`}
              >
                <span className="font-mono text-[12px] text-pencil mr-1">{id}</span>
                {ev?.domain || 'source'}
              </button>
              {open && ev && (
                <div className="card absolute z-20 right-0 lg:right-auto lg:left-0 top-8 w-80 max-w-[80vw] p-3 font-serif text-sm leading-relaxed text-ink">
                  <a href={ev.url} target="_blank" rel="noreferrer" className="ink-link font-semibold flex gap-1">
                    <span className="line-clamp-2">{ev.title || ev.url}</span>
                    <ExternalLink className="w-3 h-3 mt-1 shrink-0" />
                  </a>
                  <p className="mt-1.5 text-ink-soft line-clamp-5">{ev.snippet}</p>
                  <button onClick={() => onOpenNotes(id)} className="mt-2 hand text-lg text-pro hover:underline cursor-pointer">
                    see it in the research notes →
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </aside>
    </article>
  );
}

export default memo(TurnEntry);
