import { useEffect, useRef, useState } from 'react';
import type { DebateDetail } from '../types';

interface StreamCallbacks {
  /** First snapshot of a newly selected debate (not reconnects). */
  onFirstSnapshot?: (snap: DebateDetail) => void;
  /** The run finished and the full detail (with the master audio) was refetched. */
  onDone?: (full: DebateDetail) => void;
  /** Something changed that the run list should reflect (done, cancelled, error). */
  onListChanged?: () => void;
}

/** Live detail of the selected debate: a snapshot, then SSE events applied on top. */
export function useDebateStream(selectedId: string | null, callbacks: StreamCallbacks) {
  const [detail, setDetail] = useState<DebateDetail | null>(null);
  const cb = useRef(callbacks);
  cb.current = callbacks;

  useEffect(() => {
    if (!selectedId) return;

    let es: EventSource | null = null;
    let closed = false;
    let retries = 0;
    let firstSnapshot = true;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;

    const refetch = () =>
      fetch(`/api/debates/${selectedId}`)
        .then((r) => r.json())
        .then((full: DebateDetail) => {
          if (!closed) setDetail(full);
          return full;
        });

    const connect = () => {
      es = new EventSource(`/api/debates/${selectedId}/events`);
      es.addEventListener('snapshot', onSnapshot);
      es.onmessage = onMessage;
      es.onerror = onError;
    };

    // A dropped stream (sleep, network blip, server restart) reconnects with backoff while the run is
    // still active; the snapshot on reconnect catches up on anything missed.
    const onError = () => {
      es?.close();
      if (closed) return;
      refetch()
        .then((full) => {
          if (closed || (full.status !== 'running' && full.status !== 'cancelling')) return;
          const delay = Math.min(1000 * 2 ** retries, 15000);
          retries += 1;
          retryTimer = setTimeout(connect, delay);
        })
        .catch(() => {
          if (closed) return;
          retryTimer = setTimeout(connect, Math.min(1000 * 2 ** retries++, 15000));
        });
    };

    const onSnapshot = (e: MessageEvent) => {
      retries = 0;
      const snap: DebateDetail = JSON.parse(e.data);
      setDetail(snap);
      if (!firstSnapshot) return; // reconnect: keep audio mode and play queue as they are
      firstSnapshot = false;
      cb.current.onFirstSnapshot?.(snap);
    };

    const onMessage = (e: MessageEvent) => {
      const evt = JSON.parse(e.data);
      setDetail((prev) => {
        if (!prev) return prev;
        const next: DebateDetail = {
          ...prev,
          current_step: evt.type !== 'segment_audio_ready' ? evt : prev.current_step,
          state: { ...prev.state },
        };

        switch (evt.type) {
          case 'counter_claim':
            next.state.counter_claim = evt.counter_claim;
            break;
          case 'research_queries':
            next.state.queries = { ...next.state.queries, [evt.side]: evt.queries };
            break;
          // The server subscribes before snapshotting, so an event may repeat what the snapshot has.
          case 'evidence_added':
            if (!next.state.ledger.items.some((it) => it.id === evt.evidence.id)) {
              next.state.ledger = { items: [...next.state.ledger.items, evt.evidence] };
            }
            break;
          case 'turn_complete':
            if (evt.turn_index >= next.state.turns.length) {
              next.state.turns = [...next.state.turns, evt.turn];
            }
            break;
          case 'judge_complete':
            next.state.judge = evt.judge;
            break;
          case 'phase_done':
            next.state.phases_done = evt.phases_done;
            next.state.timings_s = { ...next.state.timings_s, [evt.phase]: evt.elapsed_s };
            break;
          case 'segment_audio_ready':
            // Replace by id: a resumed run may re-synthesize a clip (new ?v= url).
            next.segments = [...prev.segments.filter((s) => s.segment_id !== evt.segment_id), evt];
            break;
          case 'render_complete':
            next.has_wav = true;
            next.audio_url = `/api/debates/${prev.id}/audio/master`;
            break;
          case 'debate_done':
            next.status = 'done';
            if (evt.state) next.state = evt.state;
            next.audio_url = `/api/debates/${prev.id}/audio/master`;
            break;
          case 'debate_cancelled':
            next.status = 'cancelled';
            break;
          case 'debate_error':
            next.status = 'error';
            next.error = evt.error || 'Debate failed';
            break;
        }
        return next;
      });

      // Side effects stay outside the state updater, which React may run twice.
      if (evt.type === 'debate_done') {
        refetch()
          .then((full) => cb.current.onDone?.(full))
          .catch(() => {});
      } else if (evt.type === 'debate_cancelled') {
        // The server dropped the half-finished phase; show what resume will continue from.
        refetch().catch(() => {});
      }
      if (evt.type === 'debate_done' || evt.type === 'debate_cancelled' || evt.type === 'debate_error') {
        cb.current.onListChanged?.();
      }
    };

    connect();

    return () => {
      closed = true;
      clearTimeout(retryTimer);
      es?.close();
    };
  }, [selectedId]);

  return [detail, setDetail] as const;
}
