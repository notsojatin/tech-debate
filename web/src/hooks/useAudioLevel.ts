import { useEffect, useState } from 'react';

// One AudioContext for the page. A media element can be wrapped by createMediaElementSource only once
// (a second call throws InvalidStateError, and StrictMode re-runs effects), so the graph is cached per element
// and never torn down; effects only start and stop their animation loop.
let ctx: AudioContext | null = null;
const graphs = new WeakMap<HTMLMediaElement, AnalyserNode>();

function analyserFor(el: HTMLMediaElement): AnalyserNode | null {
  const cached = graphs.get(el);
  if (cached) return cached;
  try {
    ctx ??= new AudioContext();
    const source = ctx.createMediaElementSource(el);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 256;
    analyser.smoothingTimeConstant = 0.72;
    source.connect(analyser);
    analyser.connect(ctx.destination);
    graphs.set(el, analyser);
    return analyser;
  } catch {
    return null;
  }
}

export interface AudioLevel {
  level: number; // 0..1 loudness of the voice band
  bins: number[]; // 0..1 per bar
}

const silent = (bars: number): AudioLevel => ({ level: 0, bins: new Array(bars).fill(0) });

/** Live loudness and spectrum of whatever the element is playing, for the speaking avatar and waveform. */
export function useAudioLevel(el: HTMLMediaElement | null, playing: boolean, bars = 28): AudioLevel {
  const [state, setState] = useState<AudioLevel>(() => silent(bars));

  useEffect(() => {
    if (!el || !playing) {
      setState(silent(bars));
      return;
    }
    const analyser = analyserFor(el);
    if (!analyser) return;
    // Playback started from a user gesture, so the context is allowed to run.
    ctx?.resume().catch(() => {});
    const data = new Uint8Array(analyser.frequencyBinCount);
    // Speech lives in the lower ~half of the spectrum at this sample rate.
    const usable = Math.floor(data.length * 0.55);
    let raf = 0;
    let last = 0;
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      if (now - last < 33) return; // ~30 fps is plenty for ink
      last = now;
      analyser.getByteFrequencyData(data);
      const bins: number[] = [];
      let sum = 0;
      for (let b = 0; b < bars; b++) {
        const from = Math.floor((b / bars) * usable);
        const to = Math.max(from + 1, Math.floor(((b + 1) / bars) * usable));
        let peak = 0;
        for (let i = from; i < to; i++) peak = Math.max(peak, data[i]);
        const v = peak / 255;
        bins.push(v);
        sum += v;
      }
      setState({ level: Math.min(1, (sum / bars) * 1.8), bins });
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [el, playing, bars]);

  return state;
}
