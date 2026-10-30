import { useCallback, useEffect, useRef, useState, type SyntheticEvent } from 'react';
import type { DebateDetail, SrtCue } from '../types';

export type AudioMode = 'master' | 'live';

/**
 * Owns the single <audio> element: the full recording ("master") or the per-turn clips ("live"), the live
 * auto-play queue, and a playback clock fine enough to ink words in as they are spoken.
 */
export function useAudioPlayer(detail: DebateDetail | null, selectedId: string | null) {
  const [el, setEl] = useState<HTMLAudioElement | null>(null);
  const elRef = useRef<HTMLAudioElement | null>(null);
  const audioRef = useCallback((node: HTMLAudioElement | null) => {
    elRef.current = node;
    setEl(node);
  }, []);

  const [mode, setMode] = useState<AudioMode>('master');
  const [liveAutoPlay, setLiveAutoPlay] = useState(true);
  const [segmentIdx, setSegmentIdx] = useState(0);
  const played = useRef<Set<string>>(new Set());
  const [isPlaying, setIsPlaying] = useState(false);
  const [timeMs, setTimeMs] = useState(0);
  const [durationMs, setDurationMs] = useState(0);
  const [rate, setRateState] = useState(1);

  // New debate selected: stop and forget the old queue.
  useEffect(() => {
    played.current.clear();
    setSegmentIdx(0);
    setIsPlaying(false);
    setTimeMs(0);
    elRef.current?.pause();
  }, [selectedId]);

  // ~12 Hz clock while playing; `timeupdate` alone fires only ~4 times a second.
  useEffect(() => {
    if (!isPlaying || !el) return;
    let raf = 0;
    let last = 0;
    const tick = (now: number) => {
      if (now - last > 80) {
        last = now;
        setTimeMs(el.currentTime * 1000);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [isPlaying, el]);

  const start = (src: string, atSec?: number) => {
    const audio = elRef.current;
    if (!audio) return;
    if (!audio.src.endsWith(src)) audio.src = src;
    if (atSec !== undefined) audio.currentTime = atSec;
    audio.playbackRate = rate;
    audio.play().catch(() => {});
  };

  const playSegmentAt = (idx: number) => {
    const seg = detail?.segments[idx];
    if (!seg) return;
    setMode('live');
    setSegmentIdx(idx);
    played.current.add(seg.segment_id);
    start(seg.url, 0);
  };

  const playTurn = (turnIdx: number) => {
    const idx = detail?.segments.findIndex((s) => s.turn_index === turnIdx) ?? -1;
    if (idx !== -1) playSegmentAt(idx);
  };

  const seekToCue = (cue: SrtCue) => {
    if (!detail?.audio_url) return;
    setMode('master');
    start(detail.audio_url, cue.start_ms / 1000);
  };

  const seekMs = (ms: number) => {
    const audio = elRef.current;
    if (!audio) return;
    audio.currentTime = ms / 1000;
    setTimeMs(ms);
  };

  const toggle = () => {
    const audio = elRef.current;
    if (!audio || !detail) return;
    if (!audio.paused) {
      audio.pause();
      return;
    }
    if (mode === 'master' && detail.audio_url) {
      start(detail.audio_url);
    } else if (detail.segments.length > 0) {
      const seg = detail.segments[segmentIdx] || detail.segments[0];
      start(seg.url);
    }
  };

  const switchMode = (next: AudioMode) => {
    elRef.current?.pause();
    setMode(next);
    setTimeMs(0);
  };

  const setRate = (r: number) => {
    setRateState(r);
    if (elRef.current) elRef.current.playbackRate = r;
  };

  /** Mark clips that already exist so live auto-play only picks up new ones. */
  const markAllPlayed = (snap: DebateDetail) => {
    snap.segments.forEach((s) => played.current.add(s.segment_id));
  };

  // Live auto-play: when idle, play the next clip that has not been heard yet.
  useEffect(() => {
    if (!detail || mode !== 'live' || !liveAutoPlay) return;
    if (detail.status !== 'running' && detail.status !== 'cancelling') return;
    const audio = elRef.current;
    if (!audio || !audio.paused) return;
    const nextIdx = detail.segments.findIndex((s) => !played.current.has(s.segment_id));
    if (nextIdx !== -1) playSegmentAt(nextIdx);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail?.segments, mode, liveAutoPlay, detail?.status, isPlaying]);

  const audioProps = {
    ref: audioRef,
    onPlay: () => setIsPlaying(true),
    onPause: () => setIsPlaying(false),
    onSeeked: (e: SyntheticEvent<HTMLAudioElement>) => setTimeMs(e.currentTarget.currentTime * 1000),
    onTimeUpdate: (e: SyntheticEvent<HTMLAudioElement>) => {
      if (e.currentTarget.paused) setTimeMs(e.currentTarget.currentTime * 1000);
    },
    onLoadedMetadata: (e: SyntheticEvent<HTMLAudioElement>) => setDurationMs(e.currentTarget.duration * 1000),
    onEnded: () => {
      setIsPlaying(false);
      setTimeMs(0); // a finished clip is no longer "being spoken": drop its highlight
      // Live clips play on into the next one.
      if (mode === 'live' && detail && detail.segments.length > segmentIdx + 1) playSegmentAt(segmentIdx + 1);
    },
  };

  return {
    el,
    audioProps,
    mode,
    switchMode,
    setMode,
    liveAutoPlay,
    setLiveAutoPlay,
    segmentIdx,
    isPlaying,
    timeMs,
    durationMs,
    rate,
    setRate,
    toggle,
    seekMs,
    seekToCue,
    playSegmentAt,
    playTurn,
    markAllPlayed,
  };
}

export type AudioPlayer = ReturnType<typeof useAudioPlayer>;
