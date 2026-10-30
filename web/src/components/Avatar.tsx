import type { StageMode } from '../hooks/useSpeech';

interface Props {
  role: 'pro' | 'con' | 'judge';
  label: string;
  active: boolean;
  mode: StageMode;
  level: number; // 0..1 voice loudness, drives the mouth and the ink glow
}

const COLOR = { pro: 'var(--pro)', con: 'var(--con)', judge: 'var(--judge)' } as const;

/** An ink-sketched speaker at a podium (or the judge at the bench). */
export default function Avatar({ role, label, active, mode, level }: Props) {
  const color = COLOR[role];
  const speaking = active && mode === 'speaking';
  const drafting = active && mode === 'drafting';
  const glow = speaking ? 0.16 + level * 0.3 : drafting ? 0.12 : 0;
  const mouthOpen = speaking ? 1.2 + level * 7 : 0;

  return (
    <svg
      viewBox="0 0 120 120"
      className={`w-full h-full overflow-visible ${active ? '' : 'breathe'}`}
      role="img"
      aria-label={`${label}${speaking ? ', speaking' : drafting ? ', writing' : ''}`}
    >
      {/* ink-blot glow behind the active speaker */}
      <circle
        cx="60"
        cy="44"
        r={34 + (speaking ? level * 12 : 0)}
        fill={color}
        opacity={glow}
        style={{ transition: 'r 80ms linear, opacity 200ms ease' }}
      />

      {/* shoulders */}
      <path d="M30 92 Q33 70 60 68 Q87 70 90 92" fill="var(--card)" stroke="var(--ink)" strokeWidth="2.2" strokeLinecap="round" />

      {/* head: two offset strokes read as a pen sketch */}
      <circle cx="60" cy="42" r="20" fill="var(--card)" stroke="var(--ink)" strokeWidth="2.2" />
      <circle cx="60.8" cy="41.4" r="20.6" fill="none" stroke="var(--ink)" strokeWidth="0.8" opacity="0.35" />

      {role === 'judge' && (
        // a judge's wig curls
        <g fill="none" stroke="var(--ink)" strokeWidth="1.6" opacity="0.8">
          <path d="M40 34 q-6 4 -2 10 q-5 4 -1 10" />
          <path d="M80 34 q6 4 2 10 q5 4 1 10" />
        </g>
      )}

      {/* eyes: looking down at the page while writing */}
      {drafting ? (
        <g stroke="var(--ink)" strokeWidth="2" fill="none" strokeLinecap="round">
          <path d="M50 42 q3 2.5 6 0" />
          <path d="M64 42 q3 2.5 6 0" />
        </g>
      ) : (
        <g fill="var(--ink)">
          <circle cx="53" cy="40" r="2.3" />
          <circle cx="67" cy="40" r="2.3" />
        </g>
      )}

      {/* mouth */}
      {speaking ? (
        <ellipse cx="60" cy="51" rx="5.5" ry={mouthOpen} fill="var(--ink)" style={{ transition: 'ry 60ms linear' }} />
      ) : (
        <path d="M54 50 Q60 54 66 50" fill="none" stroke="var(--ink)" strokeWidth="2" strokeLinecap="round" />
      )}

      {/* podium or bench */}
      {role === 'judge' ? (
        <g>
          <path d="M14 86 H106 V118 H14 Z" fill="var(--card)" stroke="var(--ink)" strokeWidth="2.2" strokeLinejoin="round" />
          <path d="M14 92 H106" stroke="var(--ink)" strokeWidth="1" opacity="0.4" />
          {/* gavel */}
          <g transform="translate(92 74) rotate(-28)" stroke="var(--ink)" strokeWidth="1.8" fill="var(--card)">
            <rect x="-7" y="-4" width="14" height="8" rx="1.5" />
            <path d="M0 4 V16" />
          </g>
        </g>
      ) : (
        <path d="M28 86 L92 86 L86 118 L34 118 Z" fill="var(--card)" stroke="var(--ink)" strokeWidth="2.2" strokeLinejoin="round" />
      )}
      <text
        x="60"
        y={role === 'judge' ? 110 : 108}
        textAnchor="middle"
        fontFamily="var(--font-hand)"
        fontWeight="700"
        fontSize={label.length > 6 ? 15 : 19}
        fill={color}
      >
        {label}
      </text>

      {/* pen scribbling above the head while the model drafts */}
      {drafting && (
        <g className="scribble" stroke={color} strokeWidth="2.2" fill="none" strokeLinecap="round">
          <path d="M80 14 q4 -6 8 0 t8 0 t8 0" />
          <path d="M102 4 l6 -6 l3 3 l-6 6 z" fill={color} stroke="none" />
        </g>
      )}
    </svg>
  );
}
