import { useMemo, useState } from 'react';
import { ChevronDown, ExternalLink, Search } from 'lucide-react';
import type { DebateState } from '../types';

interface Props {
  state: DebateState;
  open: boolean;
  onToggle: () => void;
  highlighted: string | null;
  running: boolean;
}

type Filter = 'all' | 'pro' | 'con';

/** The evidence ledger as a folded appendix: search queries, then one line per passage. */
export default function ResearchNotes({ state, open, onToggle, highlighted, running }: Props) {
  const [filter, setFilter] = useState<Filter>('all');
  const [q, setQ] = useState('');
  const items = state.ledger.items;

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return items.filter(
      (e) =>
        (filter === 'all' || e.side === filter) &&
        (!needle || `${e.id} ${e.title} ${e.domain} ${e.snippet}`.toLowerCase().includes(needle)),
    );
  }, [items, filter, q]);

  const count = (side: 'pro' | 'con') => items.filter((e) => e.side === side).length;

  return (
    <section id="research-notes" className="sheet scroll-mt-48" aria-label="Research notes">
      <button
        onClick={onToggle}
        aria-expanded={open}
        className="w-full flex items-center justify-between gap-3 px-5 sm:px-6 py-3 text-left cursor-pointer"
      >
        <span className="flex items-baseline gap-3">
          <span className="hand text-3xl font-bold">Research notes</span>
          <span className="text-sm text-pencil">
            {items.length} passages{running && items.length === 0 ? ' · searching…' : ''}
          </span>
        </span>
        <ChevronDown className={`w-5 h-5 text-pencil transition ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="px-5 sm:px-6 pb-5 space-y-4 border-t border-dashed border-edge pt-4">
          {state.counter_claim && (
            <p className="text-sm text-ink-soft">
              <span className="hand text-lg text-judge">Stance check against: </span>
              <em>“{state.counter_claim}”</em>
            </p>
          )}

          {(state.queries.pro || state.queries.con) && (
            <div className="grid sm:grid-cols-2 gap-x-8 gap-y-2">
              {(['pro', 'con'] as const).map((side) => (
                <div key={side}>
                  <div className={`hand text-xl ${side === 'pro' ? 'text-pro' : 'text-con'}`}>
                    {side === 'pro' ? 'Pro searched for' : 'Con searched for'}
                  </div>
                  <ol className="list-decimal pl-5 text-sm text-ink-soft space-y-0.5 marker:text-pencil">
                    {(state.queries[side] || []).map((query, i) => (
                      <li key={i}>{query}</li>
                    ))}
                  </ol>
                </div>
              ))}
            </div>
          )}

          {items.length > 0 && (
            <div className="flex flex-wrap items-center gap-3">
              <div role="tablist" aria-label="Filter by side" className="flex rounded-full border border-edge p-0.5 text-sm">
                {(['all', 'pro', 'con'] as Filter[]).map((f) => (
                  <button
                    key={f}
                    role="tab"
                    aria-selected={filter === f}
                    onClick={() => setFilter(f)}
                    className={`px-3 py-0.5 rounded-full cursor-pointer ${
                      filter === f ? 'bg-ink text-paper' : 'text-ink-soft hover:text-ink'
                    }`}
                  >
                    {f === 'all' ? `All ${items.length}` : `${f === 'pro' ? 'Pro' : 'Con'} ${count(f)}`}
                  </button>
                ))}
              </div>
              <label className="flex items-center gap-2 border-b border-dashed border-edge focus-within:border-ink flex-1 min-w-[12rem] max-w-sm">
                <Search className="w-4 h-4 text-pencil" />
                <input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="Search the notes"
                  className="bg-transparent py-1 text-sm w-full focus:outline-none placeholder:text-pencil"
                />
              </label>
            </div>
          )}

          <ul className="divide-y divide-dashed divide-edge">
            {shown.map((ev) => (
              <li
                key={ev.id}
                id={`evidence-${ev.id}`}
                className={`py-2.5 grid grid-cols-[3rem_minmax(0,1fr)] gap-x-3 scroll-mt-48 rounded transition ${
                  highlighted === ev.id ? 'marker' : ''
                }`}
              >
                <span className={`font-mono text-sm pt-0.5 ${ev.side === 'pro' ? 'text-pro' : 'text-con'}`}>{ev.id}</span>
                <div className="min-w-0">
                  <a href={ev.url} target="_blank" rel="noreferrer" className="ink-link font-semibold text-[0.95rem] inline-flex gap-1 max-w-full">
                    <span className="truncate">{ev.title || ev.domain}</span>
                    <ExternalLink className="w-3 h-3 mt-1.5 shrink-0 text-pencil" />
                  </a>
                  <span className="text-xs text-pencil font-mono ml-2">{ev.domain}</span>
                  <p className="text-sm text-ink-soft leading-relaxed line-clamp-2">{ev.snippet}</p>
                </div>
              </li>
            ))}
          </ul>
          {items.length > 0 && shown.length === 0 && <p className="text-sm text-pencil">No passages match.</p>}
          {items.length === 0 && (
            <p className="hand text-xl text-pencil">{running ? 'Searching the web…' : 'No web evidence was gathered for this run.'}</p>
          )}
        </div>
      )}
    </section>
  );
}
