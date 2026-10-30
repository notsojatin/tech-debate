import type { JudgeResult } from '../types';

interface Props {
  judge: JudgeResult;
  model: string;
}

const fmt = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1));

/** The judge's scorecard, marked up in red pen. */
export default function Verdict({ judge, model }: Props) {
  const winnerTone = judge.winner === 'pro' ? 'text-pro' : judge.winner === 'con' ? 'text-con' : 'text-judge';
  const criteria = Object.keys(judge.average.pro);

  return (
    <section id="verdict" className="sheet px-5 sm:px-8 py-6 scroll-mt-48" aria-label="Verdict">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h3 className="hand text-4xl font-bold">The verdict</h3>
          <p className="font-mono text-[12px] text-pencil">judged by {model}, twice with the sides swapped</p>
        </div>
        <div className="flex items-center gap-5">
          <div className="text-center">
            <div className="hand text-5xl leading-none">
              <span className="text-pro">{fmt(judge.totals.pro)}</span>
              <span className="text-pencil text-3xl"> – </span>
              <span className="text-con">{fmt(judge.totals.con)}</span>
            </div>
            <div className="text-xs text-pencil mt-1">out of 40 each</div>
          </div>
          <span className={`stamp stamp-down text-base px-3 py-1 ${winnerTone}`}>
            {judge.winner === 'tie' ? 'Tie' : `${judge.winner} wins`}
          </span>
        </div>
      </div>

      <p className="hand text-2xl leading-snug text-ink-soft mt-4 max-w-3xl">“{judge.reason}”</p>

      <div className="grid lg:grid-cols-2 gap-8 mt-6">
        <table className="w-full text-sm">
          <caption className="text-left hand text-xl text-ink-soft mb-1">Rubric (0–10 per criterion, averaged)</caption>
          <thead>
            <tr className="text-pencil text-xs">
              <th className="text-left font-normal py-1">Criterion</th>
              <th className="font-normal text-pro w-24">Pro</th>
              <th className="font-normal text-con w-24">Con</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-dashed divide-edge">
            {criteria.map((c) => {
              const p = judge.average.pro[c];
              const k = judge.average.con[c];
              return (
                <tr key={c}>
                  <td className="py-2 capitalize">{c.replace(/_/g, ' ')}</td>
                  {[
                    [p, 'pro', p > k],
                    [k, 'con', k > p],
                  ].map(([v, side, lead]) => (
                    <td key={side as string} className="text-center py-2">
                      <span
                        className={`hand text-2xl inline-grid place-items-center w-11 h-9 ${
                          side === 'pro' ? 'text-pro' : 'text-con'
                        } ${lead ? 'rounded-[50%] border-2 border-current' : ''}`}
                        title={lead ? 'Higher score' : undefined}
                      >
                        {fmt(v as number)}
                      </span>
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>

        <div>
          <div className="hand text-xl text-ink-soft mb-1">Both readings</div>
          <p className={`text-sm mb-3 ${judge.position_consistent ? 'text-ink-soft' : 'text-judge'}`}>
            {judge.position_consistent
              ? '✓ Same winner whichever side was read first.'
              : '⚠ The winner changed when the order was swapped, so treat this result with care.'}
          </p>
          <ol className="space-y-3">
            {judge.runs.map((run, i) => (
              <li key={i} className="card px-4 py-2.5">
                <div className="flex justify-between gap-3 text-xs text-pencil">
                  <span>Reading {i + 1}: {run.order}</span>
                  <span className={run.winner === 'pro' ? 'text-pro' : run.winner === 'con' ? 'text-con' : 'text-judge'}>
                    {run.winner === 'tie' ? 'tie' : `${run.winner} won`}
                  </span>
                </div>
                <p className="text-sm text-ink-soft mt-1">{run.reason}</p>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}
