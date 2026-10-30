import type { ReactNode } from 'react';
import { useAudioLevel } from '../hooks/useAudioLevel';
import type { StageState } from '../hooks/useSpeech';
import Avatar from './Avatar';
import Waveform from './Waveform';

interface Props {
  stage: StageState;
  audioEl: HTMLAudioElement | null;
  isPlaying: boolean;
  models: { pro: string; con: string; judge: string };
  status: string | null; // what the pipeline is doing, shown while nobody is speaking
  winner: 'pro' | 'con' | 'tie' | null;
}

const NAMES = { pro: 'For the motion', con: 'Against', judge: 'The bench' } as const;

/** The debate floor: two podiums, the bench, and the voice of whoever is speaking. */
export default function Stage({ stage, audioEl, isPlaying, models, status, winner }: Props) {
  const { level, bins } = useAudioLevel(audioEl, isPlaying);
  const { speaker, mode } = stage;
  // The narrator reads from the bench.
  const benchActive = speaker === 'judge' || speaker === 'narrator';
  const color = speaker === 'pro' ? '--pro' : speaker === 'con' ? '--con' : '--judge';

  const podium = (role: 'pro' | 'con') => (
    <div className="flex flex-col items-center min-w-0">
      <div className="w-20 h-20 sm:w-24 sm:h-24">
        <Avatar role={role} label={role.toUpperCase()} active={speaker === role} mode={mode} level={level} />
      </div>
      <div className="text-center leading-tight mt-0.5 min-w-0 max-w-full">
        <div className={`hand text-lg ${role === 'pro' ? 'text-pro' : 'text-con'}`}>{NAMES[role]}</div>
        <div className="font-mono text-[11px] text-pencil truncate">{models[role]}</div>
      </div>
    </div>
  );

  let line: ReactNode;
  if (mode === 'speaking' && stage.caption) {
    line = <span className="italic">“{stage.caption}”</span>;
  } else if (mode === 'drafting') {
    line = <span className="text-ink-soft">{status}</span>;
  } else {
    line = <span className="text-pencil">{status || 'The floor is quiet. Press play to hear the debate.'}</span>;
  }

  return (
    <section className="sheet px-3 sm:px-6 py-3" aria-label="Debate stage">
      <div className="grid grid-cols-[1fr_minmax(0,2.2fr)_1fr] items-center gap-2 sm:gap-6">
        {podium('pro')}

        <div className="flex flex-col items-center min-w-0">
          <div className="relative w-16 h-16 sm:w-20 sm:h-20">
            <Avatar
              role="judge"
              label={speaker === 'narrator' ? 'NARRATOR' : 'JUDGE'}
              active={benchActive}
              mode={mode}
              level={level}
            />
            {winner && (
              <span
                className={`stamp stamp-down absolute -right-14 top-2 bg-card text-[0.7rem] hidden sm:inline-block ${
                  winner === 'pro' ? 'text-pro' : winner === 'con' ? 'text-con' : 'text-judge'
                }`}
              >
                {winner === 'tie' ? 'Tie' : `${winner} wins`}
              </span>
            )}
          </div>
          <div className="w-full h-10 sm:h-12 mt-1">
            <Waveform bins={bins} color={color} active={mode === 'speaking'} />
          </div>
          <p
            className="mt-1 w-full text-center text-sm sm:text-[0.95rem] leading-snug line-clamp-2 min-h-[2.6em]"
          >
            {line}
          </p>
          <div className="font-mono text-[11px] text-pencil truncate max-w-full">judge · {models.judge}</div>
        </div>

        {podium('con')}
      </div>
    </section>
  );
}
