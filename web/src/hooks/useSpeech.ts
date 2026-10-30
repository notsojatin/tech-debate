import { useMemo } from 'react';
import { normWords, splitIntoSentences, wordsOf } from '../lib/text';
import type { DebateDetail, SrtCue } from '../types';
import type { AudioPlayer } from './useAudioPlayer';

/** Where the voice is inside a turn: which sentence, and how far through it (0..1). */
export interface SpeechPos {
  turnIdx: number;
  sentIdx: number;
  progress: number;
}

export type Speaker = 'pro' | 'con' | 'judge' | 'narrator';
export type StageMode = 'speaking' | 'drafting' | 'idle';

export interface StageState {
  speaker: Speaker | null;
  mode: StageMode;
  caption: string | null; // the sentence being spoken
}

const matches = (cueText: string, sentence: string) => {
  const s = normWords(sentence).slice(0, 18);
  return !!s && normWords(cueText).includes(s);
};

/** Map each turn sentence to its cue in the full recording, so a click seeks and playback highlights. */
export function useCueMap(detail: DebateDetail | null) {
  return useMemo(() => {
    const byKey = new Map<string, SrtCue>();
    const keyByCue = new Map<number, string>();
    if (!detail || !detail.srt_cues.length) return { byKey, keyByCue };
    const cues = detail.srt_cues;
    let cursor = 0;
    detail.state.turns.forEach((turn, turnIdx) => {
      splitIntoSentences(turn.text).forEach((sent, sentIdx) => {
        for (let i = cursor; i < cues.length; i++) {
          if (cues[i].speaker === turn.side && matches(cues[i].text, sent)) {
            const key = `${turnIdx}:${sentIdx}`;
            byKey.set(key, cues[i]);
            keyByCue.set(cues[i].index, key);
            cursor = i + 1;
            break;
          }
        }
      });
    });
    return { byKey, keyByCue };
  }, [detail?.state.turns, detail?.srt_cues]);
}

/** Spread a 0..1 progress through a whole turn across its sentences by word count. */
function posFromTurnProgress(text: string, turnIdx: number, p: number): SpeechPos {
  const sentences = splitIntoSentences(text);
  const counts = sentences.map((s) => wordsOf(s).length);
  const total = counts.reduce((a, b) => a + b, 0) || 1;
  let target = Math.max(0, Math.min(1, p)) * total;
  for (let i = 0; i < counts.length; i++) {
    if (target <= counts[i] || i === counts.length - 1) {
      return { turnIdx, sentIdx: i, progress: counts[i] ? Math.min(1, target / counts[i]) : 1 };
    }
    target -= counts[i];
  }
  return { turnIdx, sentIdx: 0, progress: 0 };
}

export function useSpeech(
  detail: DebateDetail | null,
  player: AudioPlayer,
  cueMap: ReturnType<typeof useCueMap>,
): { pos: SpeechPos | null; activeCue: SrtCue | null; stage: StageState } {
  const { mode, isPlaying, timeMs, segmentIdx } = player;

  return useMemo(() => {
    let pos: SpeechPos | null = null;
    let activeCue: SrtCue | null = null;
    let speaker: Speaker | null = null;
    let caption: string | null = null;

    if (detail) {
      if (mode === 'master' && detail.srt_cues.length) {
        activeCue = detail.srt_cues.find((c) => timeMs >= c.start_ms && timeMs <= c.end_ms) || null;
        if (activeCue) {
          speaker = activeCue.speaker;
          caption = activeCue.text;
          const key = cueMap.keyByCue.get(activeCue.index);
          if (key) {
            const [t, s] = key.split(':').map(Number);
            const span = Math.max(1, activeCue.end_ms - activeCue.start_ms);
            pos = { turnIdx: t, sentIdx: s, progress: (timeMs - activeCue.start_ms) / span };
          }
        }
      } else if (mode === 'live') {
        const seg = detail.segments[segmentIdx];
        if (seg && (isPlaying || timeMs > 0)) {
          speaker = seg.speaker;
          const turn = seg.turn_index !== null ? detail.state.turns[seg.turn_index] : undefined;
          const cue = seg.cues?.find((c) => timeMs >= c.start_ms && timeMs <= c.end_ms);
          caption = cue?.text ?? null;
          if (turn && seg.turn_index !== null) {
            const sentences = splitIntoSentences(turn.text);
            const sentIdx = cue ? sentences.findIndex((s) => matches(cue.text, s)) : -1;
            if (cue && sentIdx !== -1) {
              const span = Math.max(1, cue.end_ms - cue.start_ms);
              pos = { turnIdx: seg.turn_index, sentIdx, progress: (timeMs - cue.start_ms) / span };
            } else {
              const dur = (seg.duration_s ?? 0) * 1000 || player.durationMs;
              pos = posFromTurnProgress(turn.text, seg.turn_index, dur ? timeMs / dur : 0);
            }
          }
        }
      }
    }

    if (pos) pos.progress = Math.max(0, Math.min(1, pos.progress));

    let stageMode: StageMode = isPlaying && speaker ? 'speaking' : 'idle';
    if (!isPlaying) speaker = null;

    // While nothing is being heard, show who the pipeline is waiting on.
    const running = detail?.status === 'running' || detail?.status === 'cancelling';
    if (stageMode === 'idle' && running && detail?.current_step) {
      const step = detail.current_step;
      if (step.type === 'turn_attempt' && step.status === 'stance_check') {
        speaker = 'judge';
        stageMode = 'drafting';
      } else if ((step.type === 'turn_attempt' || step.type === 'research_status') && step.side) {
        speaker = step.side;
        stageMode = 'drafting';
      } else if (step.type === 'judge_start' || (step.type === 'phase_start' && step.phase === 'judge')) {
        speaker = 'judge';
        stageMode = 'drafting';
      }
    }

    return { pos, activeCue, stage: { speaker, mode: stageMode, caption: stageMode === 'speaking' ? caption : null } };
  }, [detail, mode, isPlaying, timeMs, segmentIdx, cueMap, player.durationMs]);
}
