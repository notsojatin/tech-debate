import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowDown, Monitor, Moon, Notebook, RotateCcw, Sun, TriangleAlert } from 'lucide-react';
import AudioBar from './components/AudioBar';
import Composer, { type StartRequest } from './components/Composer';
import PhaseTimeline from './components/PhaseTimeline';
import ResearchNotes from './components/ResearchNotes';
import RunList from './components/RunList';
import Stage from './components/Stage';
import Transcript from './components/Transcript';
import Verdict from './components/Verdict';
import { useAudioPlayer } from './hooks/useAudioPlayer';
import { useDebateStream } from './hooks/useDebateStream';
import { useCueMap, useSpeech } from './hooks/useSpeech';
import { useTheme } from './hooks/useTheme';
import { describeStep, rebuttalRound } from './phases';
import type { DebateDetail, DebateSummary, EvidenceItem, ModelsResponse } from './types';

const LENGTH_WORD = { short: 'short', standard: 'standard-length', long: 'long' } as const;

export default function App() {
  const [info, setInfo] = useState<ModelsResponse | null>(null);
  const [debates, setDebates] = useState<DebateSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showNotebook, setShowNotebook] = useState(true);
  const [researchOpen, setResearchOpen] = useState(false);
  const [highlightedCite, setHighlightedCite] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const [actionError, setActionError] = useState<string | null>(null);
  const theme = useTheme();

  const refreshList = useCallback(async () => {
    try {
      const res = await fetch('/api/debates');
      if (res.ok) {
        const list: DebateSummary[] = await res.json();
        setDebates(list);
        return list;
      }
    } catch {
      // ignore: the list refreshes again on the next change
    }
    return [];
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const [mRes, list] = await Promise.all([fetch('/api/models'), refreshList()]);
        if (!mRes.ok) return;
        const m: ModelsResponse = await mRes.json();
        setInfo(m);
        setSelectedId(m.active_run_id ?? list[0]?.id ?? null);
      } catch {
        // server not reachable yet
      }
    })();
  }, [refreshList]);

  // `player` is created after the stream, so the stream's callbacks reach it through a ref.
  const playerRef = useRef<ReturnType<typeof useAudioPlayer> | null>(null);
  const [detail, setDetail] = useDebateStream(selectedId, {
    onFirstSnapshot: (snap) => {
      const p = playerRef.current;
      const running = snap.status === 'running' || snap.status === 'cancelling';
      if (running) {
        p?.setMode('live');
        p?.markAllPlayed(snap); // only new clips auto-play
      } else if (snap.audio_url) p?.setMode('master');
      else if (snap.segments.length > 0) p?.setMode('live');
      setResearchOpen(running && snap.state.turns.length === 0);
      setFollow(true);
      setActionError(null);
    },
    onDone: (full) => {
      // Don't swap the source under a clip that is still playing; the reader can switch when it ends.
      if (full.audio_url && !playerRef.current?.isPlaying) playerRef.current?.setMode('master');
    },
    onListChanged: refreshList,
  });
  const player = useAudioPlayer(detail, selectedId);
  playerRef.current = player;

  const cueMap = useCueMap(detail);
  const { pos, stage } = useSpeech(detail, player, cueMap);

  const evidenceById = useMemo(() => {
    const map: Record<string, EvidenceItem> = {};
    detail?.state.ledger.items.forEach((e) => (map[e.id] = e));
    return map;
  }, [detail?.state.ledger.items]);

  const running = detail?.status === 'running' || detail?.status === 'cancelling';
  const step = detail?.current_step ?? null;
  const currentPhase = running ? detail!.phases_plan.find((p) => !detail!.state.phases_done.includes(p)) ?? null : null;
  const drafting =
    running && step?.type === 'turn_attempt' && step.side && step.phase
      ? { phase: step.phase, side: step.side, status: describeStep(step) }
      : null;

  // ------------------------------------------------------------------ actions

  const startDebate = async (req: StartRequest): Promise<string | null> => {
    try {
      const res = await fetch('/api/debates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req),
      });
      const data = await res.json();
      if (!res.ok) return typeof data.detail === 'string' ? data.detail : 'Could not start the debate';
      await refreshList();
      setSelectedId(data.id);
      return null;
    } catch (e) {
      return e instanceof Error ? e.message : 'Network error';
    }
  };

  const cancelDebate = async () => {
    if (detail) await fetch(`/api/debates/${detail.id}/cancel`, { method: 'POST' });
  };

  const resumeDebate = async () => {
    if (!detail) return;
    setActionError(null);
    const res = await fetch(`/api/debates/${detail.id}/resume`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      setActionError(err.detail || 'Could not resume the debate');
      return;
    }
    const updated: DebateDetail = await res.json();
    setDetail(updated);
    // Reconnect the event stream for the resumed run.
    const id = detail.id;
    setSelectedId(null);
    setTimeout(() => setSelectedId(id), 20);
  };

  const scrollTo = (id: string) =>
    setTimeout(() => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60);

  const jumpToPhase = (phase: string) => {
    setFollow(false);
    if (phase === 'research') {
      setResearchOpen(true);
      scrollTo('research-notes');
    } else if (phase === 'judge') {
      scrollTo('verdict');
    } else {
      scrollTo(`phase-${phase}`);
    }
  };

  // Stable handlers for the memoised transcript entries; they read the latest state through a ref.
  const latest = useRef({ cueMap, player });
  latest.current = { cueMap, player };
  const onSentence = useCallback((turnIdx: number, sentIdx: number) => {
    const cue = latest.current.cueMap.byKey.get(`${turnIdx}:${sentIdx}`);
    if (cue) latest.current.player.seekToCue(cue);
  }, []);
  const onPlayTurn = useCallback((turnIdx: number) => latest.current.player.playTurn(turnIdx), []);
  const onOpenNotes = useCallback((citeId: string) => {
    setFollow(false);
    setResearchOpen(true);
    setHighlightedCite(citeId);
    setTimeout(
      () => document.getElementById(`evidence-${citeId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }),
      80,
    );
  }, []);

  // ------------------------------------------------------------------ follow the speaker

  const live = player.isPlaying || running;
  const followTarget = pos ? `turn-${pos.turnIdx}` : running && drafting ? 'turn-drafting' : null;

  useEffect(() => {
    if (!follow || !followTarget) return;
    document.getElementById(followTarget)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [follow, followTarget, detail?.state.turns.length]);

  // Scrolling by hand means the reader wants to look around: stop following until asked.
  useEffect(() => {
    if (!live) return;
    const stop = () => setFollow(false);
    const onKey = (e: KeyboardEvent) => {
      if (['PageUp', 'PageDown', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(e.key)) stop();
    };
    window.addEventListener('wheel', stop, { passive: true });
    window.addEventListener('touchmove', stop, { passive: true });
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('wheel', stop);
      window.removeEventListener('touchmove', stop);
      window.removeEventListener('keydown', onKey);
    };
  }, [live]);

  // ------------------------------------------------------------------ render

  const ThemeIcon = theme.choice === 'light' ? Sun : theme.choice === 'dark' ? Moon : Monitor;
  const themeLabel = theme.choice === 'light' ? 'Day paper' : theme.choice === 'dark' ? 'Night paper' : 'Match system';
  const hasAudio = !!detail && (!!detail.audio_url || detail.segments.length > 0);
  const resumable =
    !!detail &&
    (detail.status === 'interrupted' || detail.status === 'cancelled' || detail.status === 'error') &&
    !detail.state.phases_done.includes('done');
  const rounds = detail ? detail.phases_plan.filter((p) => rebuttalRound(p) !== null).length : 0;

  return (
    <div className="min-h-screen pb-32 text-ink">
      <header className="max-w-[1500px] mx-auto px-3 sm:px-5 pt-4 pb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <button
            onClick={() => setShowNotebook((v) => !v)}
            aria-pressed={showNotebook}
            className="p-2 rounded-full hover:bg-card text-ink-soft cursor-pointer"
            title="Show or hide past debates"
          >
            <Notebook className="w-5 h-5" />
          </button>
          <h1 className="hand text-4xl font-bold leading-none truncate">Tech Debate Arena</h1>
          {info && <span className="stamp text-judge hidden sm:inline-block">{info.profile} mode</span>}
        </div>
        <button
          onClick={theme.cycle}
          className="flex items-center gap-2 rounded-full px-3 py-1.5 text-sm text-ink-soft hover:bg-card cursor-pointer"
          title="Switch between day paper, night paper and your system setting"
        >
          <ThemeIcon className="w-4 h-4" />
          <span className="hidden sm:inline">{themeLabel}</span>
        </button>
      </header>

      <div className="max-w-[1500px] mx-auto px-3 sm:px-5">
        <Composer
          info={info}
          running={running}
          cancelling={detail?.status === 'cancelling'}
          onStart={startDebate}
          onCancel={cancelDebate}
        />
      </div>

      <div className="max-w-[1500px] mx-auto px-3 sm:px-5 mt-5 flex flex-col md:flex-row gap-5">
        {showNotebook && (
          <aside className="md:w-72 shrink-0">
            <div className="md:sticky md:top-4 md:max-h-[calc(100vh-2rem)] md:overflow-y-auto md:pr-1 pb-4 md:pb-28">
              <RunList debates={debates} selectedId={selectedId} onSelect={setSelectedId} />
            </div>
          </aside>
        )}

        <main className="flex-1 min-w-0 space-y-5">
          {!detail ? (
            <section className="sheet ruled px-6 py-16 text-center">
              <h2 className="hand text-4xl">A blank page</h2>
              <p className="text-ink-soft mt-3 max-w-md mx-auto leading-8">
                Write a technology motion above, pick who argues each side and how many rounds they get, then start
                the debate. The speeches appear here as they are written, and you can listen as they are read.
              </p>
            </section>
          ) : (
            <>
              <section className="sheet px-5 sm:px-8 py-5 space-y-3" aria-label="Debate">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="font-mono text-[11px] text-pencil truncate">{detail.id}</p>
                    <h2 className="text-2xl sm:text-3xl font-semibold leading-tight mt-1">{detail.state.topic}</h2>
                    <p className="hand text-xl text-ink-soft mt-1">
                      {rounds} rebuttal round{rounds === 1 ? '' : 's'} · {LENGTH_WORD[detail.speech_length] ?? detail.speech_length} speeches ·{' '}
                      <span className="text-pro">{detail.state.models.pro}</span> vs{' '}
                      <span className="text-con">{detail.state.models.con}</span>
                    </p>
                  </div>
                  {resumable && (
                    <button
                      onClick={resumeDebate}
                      className="flex items-center gap-2 rounded-full border-2 border-judge text-judge px-4 py-1.5 font-semibold hover:bg-judge hover:text-paper transition cursor-pointer"
                    >
                      <RotateCcw className="w-4 h-4" /> Resume where it stopped
                    </button>
                  )}
                </div>

                <PhaseTimeline
                  plan={detail.phases_plan}
                  done={detail.state.phases_done}
                  current={currentPhase}
                  timings={detail.state.timings_s}
                  onJump={jumpToPhase}
                />

                {(detail.error || actionError) && (
                  <p role="alert" className="flex items-start gap-2 text-con">
                    <TriangleAlert className="w-4 h-4 mt-1 shrink-0" />
                    <span>{actionError || detail.error}</span>
                  </p>
                )}
              </section>

              <div className="md:sticky md:top-2 z-30">
                <Stage
                  stage={stage}
                  audioEl={player.el}
                  isPlaying={player.isPlaying}
                  models={detail.state.models}
                  status={running ? describeStep(step) : detail.state.judge ? 'Debate complete. Press play to hear it.' : null}
                  winner={detail.state.judge?.winner ?? null}
                />
              </div>

              <ResearchNotes
                state={detail.state}
                open={researchOpen}
                onToggle={() => setResearchOpen((v) => !v)}
                highlighted={highlightedCite}
                running={running}
              />

              <Transcript
                detail={detail}
                evidenceById={evidenceById}
                speech={pos}
                cueByKey={cueMap.byKey}
                drafting={drafting}
                onSentence={onSentence}
                onPlayTurn={onPlayTurn}
                onOpenNotes={onOpenNotes}
              />

              {detail.state.judge && <Verdict judge={detail.state.judge} model={detail.state.models.judge} />}
            </>
          )}
        </main>
      </div>

      {/* Always mounted, so the Web Audio graph attaches once to the same element. */}
      <audio {...player.audioProps} preload="none" className="hidden" />
      {detail && hasAudio && <AudioBar detail={detail} player={player} />}

      {live && !follow && (
        <button
          onClick={() => setFollow(true)}
          className="fixed right-4 bottom-28 z-40 card flex items-center gap-2 px-4 py-2 hand text-xl text-ink hover:-translate-y-0.5 transition cursor-pointer"
        >
          <ArrowDown className="w-4 h-4" /> follow along
        </button>
      )}
    </div>
  );
}
