import { Pause, Play } from 'lucide-react';
import type { AudioPlayer } from '../hooks/useAudioPlayer';
import { formatMs } from '../lib/text';
import type { DebateDetail } from '../types';

interface Props {
  detail: DebateDetail;
  player: AudioPlayer;
}

const RATES = [0.75, 1, 1.25, 1.5, 2];

/** Playback for the full recording or the live per-speech clips. */
export default function AudioBar({ detail, player }: Props) {
  const { mode, isPlaying, timeMs, durationMs } = player;
  const seg = mode === 'live' ? detail.segments[player.segmentIdx] : null;
  const total = Number.isFinite(durationMs) ? durationMs : 0;

  return (
    <div className="fixed bottom-0 inset-x-0 z-40 px-3 pb-3 pointer-events-none">
      <div className="card max-w-4xl mx-auto px-3 sm:px-4 py-2 flex flex-wrap items-center gap-x-4 gap-y-2 pointer-events-auto">
        <button
          onClick={player.toggle}
          className="w-10 h-10 shrink-0 rounded-full bg-ink text-paper grid place-items-center hover:opacity-90 cursor-pointer"
          aria-label={isPlaying ? 'Pause' : 'Play'}
        >
          {isPlaying ? <Pause className="w-4 h-4 fill-current" /> : <Play className="w-4 h-4 fill-current ml-0.5" />}
        </button>

        <div role="radiogroup" aria-label="What to play" className="flex rounded-full border border-edge p-0.5 text-sm shrink-0">
          {detail.audio_url && (
            <button
              role="radio"
              aria-checked={mode === 'master'}
              onClick={() => player.switchMode('master')}
              className={`px-3 py-0.5 rounded-full cursor-pointer ${mode === 'master' ? 'bg-ink text-paper' : 'text-ink-soft'}`}
            >
              Full recording
            </button>
          )}
          {detail.segments.length > 0 && (
            <button
              role="radio"
              aria-checked={mode === 'live'}
              onClick={() => player.switchMode('live')}
              className={`px-3 py-0.5 rounded-full cursor-pointer ${mode === 'live' ? 'bg-ink text-paper' : 'text-ink-soft'}`}
            >
              Speech by speech · {detail.segments.length}
            </button>
          )}
        </div>

        <div className="flex items-center gap-2 flex-1 min-w-[10rem]">
          <span className="font-mono text-[11px] text-pencil tabular-nums">{formatMs(timeMs)}</span>
          <input
            type="range"
            min={0}
            max={Math.max(total, 1)}
            value={Math.min(timeMs, total)}
            onChange={(e) => player.seekMs(Number(e.target.value))}
            className="flex-1 accent-[var(--ink)] cursor-pointer"
            aria-label="Seek"
          />
          <span className="font-mono text-[11px] text-pencil tabular-nums">{formatMs(total)}</span>
        </div>

        {mode === 'live' && (
          <label className="flex items-center gap-1.5 text-sm text-ink-soft cursor-pointer shrink-0">
            <input
              type="checkbox"
              checked={player.liveAutoPlay}
              onChange={(e) => player.setLiveAutoPlay(e.target.checked)}
              className="accent-[var(--ink)]"
            />
            follow live
          </label>
        )}

        <select
          value={player.rate}
          onChange={(e) => player.setRate(Number(e.target.value))}
          className="bg-transparent text-sm font-mono text-ink-soft border-b border-dashed border-edge focus:outline-none cursor-pointer shrink-0"
          aria-label="Playback speed"
        >
          {RATES.map((r) => (
            <option key={r} value={r} className="bg-card">
              {r}×
            </option>
          ))}
        </select>

        {seg && (
          <span className="hand text-lg text-pencil truncate basis-full sm:basis-auto">
            {seg.speaker === 'narrator' ? 'narrator' : seg.speaker === 'pro' ? 'Pro speaking' : 'Con speaking'}
          </span>
        )}
      </div>
    </div>
  );
}
