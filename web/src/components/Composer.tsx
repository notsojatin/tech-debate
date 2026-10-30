import { useEffect, useState, type FormEvent } from 'react';
import { Feather, LoaderCircle, Minus, Plus, Square } from 'lucide-react';
import { estimateMinutes } from '../lib/text';
import type { ModelsResponse, SpeechLength } from '../types';

export interface StartRequest {
  topic: string;
  models: { pro: string; con: string; judge: string };
  rebuttal_rounds: number;
  speech_length: SpeechLength;
}

interface Props {
  info: ModelsResponse | null;
  running: boolean;
  cancelling: boolean;
  onStart: (req: StartRequest) => Promise<string | null>; // resolves to an error message, or null
  onCancel: () => void;
}

const LENGTH_LABELS: Record<SpeechLength, string> = { short: 'Short', standard: 'Standard', long: 'Long' };

/** The motion card: what to debate, who argues, how many rounds and how long each speech is. */
export default function Composer({ info, running, cancelling, onStart, onCancel }: Props) {
  const [topic, setTopic] = useState('');
  const [models, setModels] = useState({ pro: '', con: '', judge: '' });
  const [rounds, setRounds] = useState(2);
  const [length, setLength] = useState<SpeechLength>('standard');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!info) return;
    setTopic(info.demo_topic);
    setModels(info.defaults);
    setRounds(info.debate_options.rebuttal_rounds.default);
    setLength(info.debate_options.default_speech_length);
  }, [info]);

  const opts = info?.debate_options;
  const minR = opts?.rebuttal_rounds.min ?? 1;
  const maxR = opts?.rebuttal_rounds.max ?? 10;
  const clamp = (n: number) => Math.max(minR, Math.min(maxR, n));
  const words = opts?.speech_lengths[length];
  const minutes = words ? estimateMinutes(rounds, words) : null;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!topic.trim()) return;
    setSubmitting(true);
    setError(null);
    const err = await onStart({ topic: topic.trim(), models, rebuttal_rounds: rounds, speech_length: length });
    setError(err);
    setSubmitting(false);
  };

  const field = 'bg-transparent border-b border-dashed border-edge focus:border-ink focus:outline-none';

  const modelPicker = (role: 'pro' | 'con' | 'judge', label: string, tone: string) => (
    <label className="flex items-baseline gap-2 min-w-0">
      <span className={`hand text-xl ${tone} shrink-0`}>{label}</span>
      <select
        value={models[role]}
        onChange={(e) => setModels((m) => ({ ...m, [role]: e.target.value }))}
        className={`${field} font-mono text-[13px] text-ink py-0.5 pr-1 min-w-0 w-full cursor-pointer`}
        aria-label={`${label} model`}
      >
        {info?.models.map((m) => (
          <option key={m.name} value={m.name} className="bg-card text-ink">
            {m.name}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <form onSubmit={submit} className="card px-4 sm:px-6 py-4 space-y-4">
      <div className="flex flex-col lg:flex-row lg:items-end gap-3">
        <label className="flex-1 min-w-0">
          <span className="hand text-xl text-ink-soft">The motion</span>
          <input
            type="text"
            value={topic}
            onChange={(e) => {
              setTopic(e.target.value);
              setError(null);
            }}
            maxLength={200}
            placeholder="e.g. Rust is better than Go for command-line tools"
            className={`${field} block w-full text-xl sm:text-2xl text-ink placeholder:text-pencil py-1`}
          />
        </label>
        {info && info.preset_topics.length > 0 && (
          <select
            value={info.preset_topics.includes(topic) ? topic : ''}
            onChange={(e) => e.target.value && setTopic(e.target.value)}
            className={`${field} text-sm text-ink-soft py-1 lg:max-w-xs cursor-pointer`}
            aria-label="Pick a preset motion"
          >
            <option value="" disabled className="bg-card">
              …or pick a preset motion
            </option>
            {info.preset_topics.map((pt) => (
              <option key={pt} value={pt} className="bg-card text-ink">
                {pt}
              </option>
            ))}
          </select>
        )}
      </div>

      <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-x-5 gap-y-2 flex-1 min-w-[16rem]">
          {modelPicker('pro', 'For', 'text-pro')}
          {modelPicker('con', 'Against', 'text-con')}
          {modelPicker('judge', 'Judge', 'text-judge')}
        </div>

        <div role="group" aria-label="Rebuttal rounds" className="flex items-baseline gap-2">
          <span className="hand text-xl text-ink-soft">Rounds</span>
          <div className="flex items-center rounded-full border border-edge bg-paper">
            <button
              type="button"
              onClick={() => setRounds((r) => clamp(r - 1))}
              disabled={rounds <= minR}
              className="p-1.5 rounded-full hover:bg-desk disabled:opacity-30 cursor-pointer"
              aria-label="Fewer rebuttal rounds"
            >
              <Minus className="w-3.5 h-3.5" />
            </button>
            <output className="w-7 text-center font-mono text-sm tabular-nums" aria-live="polite">
              {rounds}
            </output>
            <button
              type="button"
              onClick={() => setRounds((r) => clamp(r + 1))}
              disabled={rounds >= maxR}
              className="p-1.5 rounded-full hover:bg-desk disabled:opacity-30 cursor-pointer"
              aria-label="More rebuttal rounds"
            >
              <Plus className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        <div role="radiogroup" aria-label="Speech length" className="flex items-baseline gap-2">
          <span className="hand text-xl text-ink-soft">Speeches</span>
          <div className="flex rounded-full border border-edge bg-paper p-0.5 text-sm">
            {(['short', 'standard', 'long'] as SpeechLength[]).map((l) => (
              <button
                key={l}
                type="button"
                role="radio"
                aria-checked={length === l}
                onClick={() => setLength(l)}
                aria-label={opts ? `${LENGTH_LABELS[l]}, ${opts.speech_lengths[l].rebuttal} words per rebuttal` : LENGTH_LABELS[l]}
                title={opts ? `${opts.speech_lengths[l].rebuttal} words per rebuttal` : undefined}
                className={`px-3 py-0.5 rounded-full cursor-pointer transition ${
                  length === l ? 'bg-ink text-paper' : 'text-ink-soft hover:text-ink'
                }`}
              >
                {LENGTH_LABELS[l]}
              </button>
            ))}
          </div>
        </div>

        {minutes !== null && (
          <span className="hand text-lg text-pencil" title="Estimated length of the spoken debate">
            ≈ {minutes} min of audio
          </span>
        )}

        <div className="ml-auto">
          {running ? (
            <button
              type="button"
              onClick={onCancel}
              disabled={cancelling}
              className="flex items-center gap-2 rounded-full border-2 border-con text-con px-5 py-2 font-semibold hover:bg-con hover:text-paper transition disabled:opacity-50 cursor-pointer"
            >
              <Square className="w-3.5 h-3.5 fill-current" />
              {cancelling ? 'Stopping…' : 'Stop debate'}
            </button>
          ) : (
            <button
              type="submit"
              disabled={submitting || !topic.trim() || !info}
              className="flex items-center gap-2 rounded-full bg-ink text-paper px-5 py-2 font-semibold hover:opacity-90 transition disabled:opacity-40 cursor-pointer"
            >
              {submitting ? <LoaderCircle className="w-4 h-4 animate-spin" /> : <Feather className="w-4 h-4" />}
              Start debate
            </button>
          )}
        </div>
      </div>

      {error && (
        <p role="alert" className="hand text-xl text-con">
          ✗ {error}
        </p>
      )}
    </form>
  );
}
