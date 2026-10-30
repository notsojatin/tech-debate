import type { DebateSummary } from '../types';

interface Props {
  debates: DebateSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

function Verdict({ item }: { item: DebateSummary }) {
  if (item.status === 'running' || item.status === 'cancelling') {
    return (
      <span className="stamp text-con flex items-center gap-1">
        <span className="w-1.5 h-1.5 rounded-full bg-con animate-pulse" /> live
      </span>
    );
  }
  if (item.winner) {
    const tone = item.winner === 'pro' ? 'text-pro' : item.winner === 'con' ? 'text-con' : 'text-judge';
    const score = item.totals ? ` ${item.totals.pro}–${item.totals.con}` : '';
    return <span className={`stamp ${tone}`}>{item.winner === 'tie' ? 'tie' : `${item.winner} won`}{score}</span>;
  }
  return <span className="hand text-base text-pencil">{item.status}</span>;
}

/** Past debates as a stack of index cards. */
export default function RunList({ debates, selectedId, onSelect }: Props) {
  return (
    <nav aria-label="Past debates" className="space-y-2.5">
      <h2 className="hand text-2xl text-ink-soft px-1">Notebook · {debates.length}</h2>
      {debates.length === 0 && <p className="text-sm text-pencil px-1">No debates yet.</p>}
      {debates.map((item) => {
        const active = item.id === selectedId;
        return (
          <button
            key={item.id}
            onClick={() => onSelect(item.id)}
            aria-current={active ? 'true' : undefined}
            className={`card w-full text-left px-3.5 py-3 transition cursor-pointer border-l-4 ${
              active ? 'border-l-pro -translate-y-0.5' : 'border-l-transparent hover:-translate-y-0.5'
            }`}
          >
            <p className="text-[0.95rem] leading-snug text-ink line-clamp-2">{item.topic}</p>
            <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1 mt-2">
              <span className="font-mono text-[11px] text-pencil">
                {item.created_at.replace('T', ' ').slice(5, 16)} · {item.rebuttal_rounds}r
              </span>
              <Verdict item={item} />
            </div>
            <div className="font-mono text-[11px] mt-1.5 truncate">
              <span className="text-pro">{item.models.pro}</span>
              <span className="text-pencil"> vs </span>
              <span className="text-con">{item.models.con}</span>
            </div>
          </button>
        );
      })}
    </nav>
  );
}
