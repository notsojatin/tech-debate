import { useEffect, useRef } from 'react';

interface Props {
  bins: number[];
  color: string; // a CSS custom property name, e.g. "--pro"
  active: boolean;
}

/** The voice drawn as ink strokes mirrored around a baseline; a flat pencil line when silent. */
export default function Waveform({ bins, color, active }: Props) {
  const ref = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
      canvas.width = w * dpr;
      canvas.height = h * dpr;
    }
    const g = canvas.getContext('2d');
    if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    const css = getComputedStyle(document.documentElement);
    const ink = css.getPropertyValue(active ? color : '--pencil').trim() || '#555';
    const mid = h / 2;
    g.strokeStyle = ink;
    g.lineCap = 'round';

    if (!active) {
      g.lineWidth = 1.2;
      g.globalAlpha = 0.6;
      g.setLineDash([4, 5]);
      g.beginPath();
      g.moveTo(4, mid);
      g.lineTo(w - 4, mid);
      g.stroke();
      return;
    }

    // Mirror the spectrum so the loudest band sits in the middle, like a voice-memo waveform.
    const shape = [...bins.slice().reverse(), ...bins];
    const step = w / shape.length;
    g.setLineDash([]);
    g.globalAlpha = 0.9;
    g.lineWidth = Math.max(2, step * 0.45);
    g.beginPath();
    shape.forEach((v, i) => {
      const x = step * (i + 0.5);
      const amp = Math.max(1.5, v * (mid - 3));
      g.moveTo(x, mid - amp);
      g.lineTo(x, mid + amp);
    });
    g.stroke();
  }, [bins, color, active]);

  return <canvas ref={ref} className="w-full h-full block" aria-hidden="true" />;
}
