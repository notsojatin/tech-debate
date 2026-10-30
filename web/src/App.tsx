import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Award,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Cpu,
  ExternalLink,
  History,
  Loader2,
  Pause,
  Play,
  Quote,
  RotateCcw,
  Scale,
  Search,
  ShieldAlert,
  Sparkles,
  Square,
  Volume2,
  VolumeX,
  Zap,
} from 'lucide-react';
import type {
  AudioSegment,
  CurrentStep,
  DebateDetail,
  DebateSummary,
  EvidenceItem,
  ModelsResponse,
  SrtCue,
  TurnItem,
} from './types';

const PHASE_LABELS: Record<string, string> = {
  research: 'Research',
  openings: 'Openings',
  rebuttal_1: 'Rebuttal 1',
  rebuttal_2: 'Rebuttal 2',
  closings: 'Closings',
  judge: 'Judge',
  render: 'Render',
};

const PHASE_HEADINGS: Record<string, string> = {
  openings: 'Opening Statements',
  rebuttal_1: 'Rebuttals — Round 1',
  rebuttal_2: 'Rebuttals — Round 2',
  closings: 'Closing Lines',
};

function formatMs(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '0:00';
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function splitIntoSentences(text: string): string[] {
  return text
    .split(/(?<=[.!?])\s+(?=["'(]?[A-Z0-9])/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function normWords(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function describeStep(step: CurrentStep | null): string {
  if (!step) return 'Ready';
  switch (step.type) {
    case 'starting':
    case 'service_status':
    case 'service_log':
    case 'topic_gate':
    case 'debate_cancelling':
      return step.message || 'Preparing debate...';
    case 'phase_start':
      return `Running phase: ${PHASE_LABELS[step.phase || ''] || step.phase}`;
    case 'counter_claim':
      return 'Generated opposing counter-claim for stance verification';
    case 'research_status':
      return step.status === 'generating_queries'
        ? `${step.side?.toUpperCase()} model writing search queries...`
        : `Searching web via SearXNG for ${step.side?.toUpperCase()} evidence...`;
    case 'research_queries':
      return `${step.side?.toUpperCase()} search queries ready`;
    case 'turn_attempt': {
      const sideLabel = step.side === 'pro' ? 'Pro' : 'Con';
      const phaseLabel = PHASE_LABELS[step.phase || ''] || step.phase;
      const att = step.attempt && step.max_attempts ? ` (Attempt ${step.attempt}/${step.max_attempts})` : '';
      if (step.status === 'generating') {
        return `${sideLabel} (${step.model}) drafting ${phaseLabel}${att}...`;
      }
      if (step.status === 'stance_check') {
        return `Judge verifying ${sideLabel} stance consistency${att}...`;
      }
      if (step.status === 'rejected') {
        const reason = step.errors?.[0] || 'validation failed';
        return `${sideLabel} draft rejected${att}: ${reason} — retrying...`;
      }
      return `${sideLabel} turn in progress...`;
    }
    case 'turn_complete':
      return `Validated ${step.side?.toUpperCase() || ''} turn — queuing Kokoro TTS synthesis`;
    case 'judge_start':
      return `Judge (${step.model}) evaluating full transcript (2 passes with swapped order)...`;
    case 'judge_complete':
      return 'Verdict reached — preparing final audio & transcript';
    case 'render_status':
      return 'Stitching master WAV/MP3 & generating synchronized SRT captions...';
    case 'render_complete':
    case 'debate_done':
      return 'Debate complete';
    default:
      return step.message || 'Processing...';
  }
}

export default function App() {
  const [modelsInfo, setModelsInfo] = useState<ModelsResponse | null>(null);
  const [debates, setDebates] = useState<DebateSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DebateDetail | null>(null);

  // Form controls
  const [topic, setTopic] = useState<string>('');
  const [proModel, setProModel] = useState<string>('');
  const [conModel, setConModel] = useState<string>('');
  const [judgeModel, setJudgeModel] = useState<string>('');
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [formError, setFormError] = useState<string | null>(null);

  // UI panels & highlights
  const [showHistory, setShowHistory] = useState<boolean>(true);
  const [showResearch, setShowResearch] = useState<boolean>(true);
  const [highlightedCite, setHighlightedCite] = useState<string | null>(null);
  const [activePopoverCite, setActivePopoverCite] = useState<{ turnIdx: number; citeId: string } | null>(null);

  // Audio player state
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [audioMode, setAudioMode] = useState<'master' | 'live'>('master');
  const [liveAutoPlay, setLiveAutoPlay] = useState<boolean>(true);
  const [currentSegmentIdx, setCurrentSegmentIdx] = useState<number>(0);
  const playedSegmentsRef = useRef<Set<string>>(new Set());
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [currentTimeMs, setCurrentTimeMs] = useState<number>(0);
  const [durationMs, setDurationMs] = useState<number>(0);
  const [playbackRate, setPlaybackRate] = useState<number>(1.0);

  // Load initial models & debates list
  const fetchDebatesList = async () => {
    try {
      const res = await fetch('/api/debates');
      if (res.ok) {
        const list: DebateSummary[] = await res.json();
        setDebates(list);
        return list;
      }
    } catch {
      // ignore
    }
    return [];
  };

  useEffect(() => {
    (async () => {
      try {
        const [mRes, list] = await Promise.all([fetch('/api/models'), fetchDebatesList()]);
        if (mRes.ok) {
          const info: ModelsResponse = await mRes.json();
          setModelsInfo(info);
          setTopic(info.demo_topic);
          setProModel(info.defaults.pro);
          setConModel(info.defaults.con);
          setJudgeModel(info.defaults.judge);
          if (info.active_run_id) {
            setSelectedId(info.active_run_id);
          } else if (list.length > 0) {
            setSelectedId(list[0].id);
          }
        }
      } catch {
        // ignore
      }
    })();
  }, []);

  // Connect to SSE / load detail whenever selectedId changes
  useEffect(() => {
    if (!selectedId) return;
    playedSegmentsRef.current.clear();
    setCurrentSegmentIdx(0);
    setIsPlaying(false);
    setCurrentTimeMs(0);

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
      if (snap.status === 'running' || snap.status === 'cancelling') {
        setAudioMode('live');
        // Mark already existing segments so we only auto-play new ones or let user play from start
        snap.segments.forEach((s) => playedSegmentsRef.current.add(s.segment_id));
      } else if (snap.audio_url) {
        setAudioMode('master');
      } else if (snap.segments.length > 0) {
        setAudioMode('live');
      }
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
            fetch(`/api/debates/${prev.id}`)
              .then((r) => r.json())
              .then((full: DebateDetail) => {
                setDetail(full);
                if (full.audio_url) setAudioMode('master');
              })
              .catch(() => {});
            fetchDebatesList();
            break;
          case 'debate_cancelled':
            next.status = 'cancelled';
            // The server dropped the half-finished phase; show what resume will continue from.
            refetch().catch(() => {});
            fetchDebatesList();
            break;
          case 'debate_error':
            next.status = 'error';
            next.error = evt.error || 'Debate failed';
            fetchDebatesList();
            break;
        }
        return next;
      });
    };

    connect();

    return () => {
      closed = true;
      clearTimeout(retryTimer);
      es?.close();
    };
  }, [selectedId]);

  // Live segment auto-play queue effect
  useEffect(() => {
    if (!detail || audioMode !== 'live' || !liveAutoPlay) return;
    if (detail.status !== 'running' && detail.status !== 'cancelling') return;
    const segments = detail.segments;
    if (segments.length === 0) return;

    const audio = audioRef.current;
    if (!audio) return;

    // If audio is currently paused/ended, check if there is an unplayed segment
    if (audio.paused) {
      const nextIdx = segments.findIndex((s) => !playedSegmentsRef.current.has(s.segment_id));
      if (nextIdx !== -1) {
        const seg = segments[nextIdx];
        playedSegmentsRef.current.add(seg.segment_id);
        setCurrentSegmentIdx(nextIdx);
        audio.src = seg.url;
        audio.playbackRate = playbackRate;
        audio.play().catch(() => {});
      }
    }
  }, [detail?.segments, audioMode, liveAutoPlay, detail?.status, playbackRate]);

  // Map Evidence by ID
  const evidenceById = useMemo(() => {
    const map: Record<string, EvidenceItem> = {};
    detail?.state.ledger.items.forEach((item) => {
      map[item.id] = item;
    });
    return map;
  }, [detail?.state.ledger.items]);

  // Map SRT cues to turns and sentences for synchronized transcript highlighting & seeking
  const activeCue: SrtCue | null = useMemo(() => {
    if (!detail || audioMode !== 'master' || !detail.srt_cues.length) return null;
    return (
      detail.srt_cues.find((c) => currentTimeMs >= c.start_ms && currentTimeMs <= c.end_ms) || null
    );
  }, [detail, audioMode, currentTimeMs]);

  // Map each turn sentence to its matching SRT cue so clicking a sentence seeks the master audio
  const turnSentenceCueMap = useMemo(() => {
    const map = new Map<string, SrtCue>();
    if (!detail || !detail.srt_cues.length) return map;
    const cues = detail.srt_cues;
    let cueCursor = 0;

    detail.state.turns.forEach((turn, turnIdx) => {
      const sentences = splitIntoSentences(turn.text);
      sentences.forEach((sent, sentIdx) => {
        const normSent = normWords(sent).slice(0, 28);
        if (!normSent) return;
        for (let i = cueCursor; i < cues.length; i++) {
          const c = cues[i];
          if (c.speaker === turn.side && normWords(c.text).includes(normSent.slice(0, 18))) {
            map.set(`${turnIdx}:${sentIdx}`, c);
            cueCursor = i + 1;
            break;
          }
        }
      });
    });
    return map;
  }, [detail?.state.turns, detail?.srt_cues]);

  const handleStartDebate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!topic.trim()) return;
    setSubmitting(true);
    setFormError(null);
    try {
      const res = await fetch('/api/debates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic: topic.trim(),
          models: {
            pro: proModel,
            con: conModel,
            judge: judgeModel,
          },
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setFormError(data.detail || 'Could not start debate');
        return;
      }
      await fetchDebatesList();
      setSelectedId(data.id);
    } catch (err: any) {
      setFormError(err.message || 'Network error');
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancelDebate = async () => {
    if (!detail) return;
    await fetch(`/api/debates/${detail.id}/cancel`, { method: 'POST' });
  };

  const handleResumeDebate = async () => {
    if (!detail) return;
    setFormError(null);
    const res = await fetch(`/api/debates/${detail.id}/resume`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (!res.ok) {
      const err = await res.json();
      setFormError(err.detail || 'Could not resume debate');
      return;
    }
    const updated: DebateDetail = await res.json();
    setDetail(updated);
    // Re-trigger SSE connection by resetting selectedId briefly
    const id = detail.id;
    setSelectedId(null);
    setTimeout(() => setSelectedId(id), 20);
  };

  const seekToCue = (cue: SrtCue) => {
    if (!detail?.audio_url || !audioRef.current) return;
    if (audioMode !== 'master') {
      setAudioMode('master');
    }
    const audio = audioRef.current;
    const expectedSrc = detail.audio_url;
    if (!audio.src.endsWith(expectedSrc)) {
      audio.src = expectedSrc;
    }
    audio.currentTime = cue.start_ms / 1000;
    audio.playbackRate = playbackRate;
    audio.play().catch(() => {});
  };

  const playSegmentAt = (idx: number) => {
    if (!detail || !detail.segments[idx] || !audioRef.current) return;
    setAudioMode('live');
    setCurrentSegmentIdx(idx);
    const seg = detail.segments[idx];
    playedSegmentsRef.current.add(seg.segment_id);
    const audio = audioRef.current;
    audio.src = seg.url;
    audio.playbackRate = playbackRate;
    audio.play().catch(() => {});
  };

  const togglePlayPause = () => {
    const audio = audioRef.current;
    if (!audio || !detail) return;
    if (audio.paused) {
      if (audioMode === 'master' && detail.audio_url) {
        if (!audio.src.endsWith(detail.audio_url)) {
          audio.src = detail.audio_url;
        }
        audio.playbackRate = playbackRate;
        audio.play().catch(() => {});
      } else if (audioMode === 'live' && detail.segments.length > 0) {
        const seg = detail.segments[currentSegmentIdx] || detail.segments[0];
        if (!audio.src.endsWith(seg.url)) {
          audio.src = seg.url;
        }
        audio.playbackRate = playbackRate;
        audio.play().catch(() => {});
      }
    } else {
      audio.pause();
    }
  };

  const jumpToCitation = (citeId: string) => {
    setShowResearch(true);
    setHighlightedCite(citeId);
    setTimeout(() => {
      const el = document.getElementById(`evidence-${citeId}`);
      el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 80);
  };

  const isRunning = detail?.status === 'running' || detail?.status === 'cancelling';
  const activePlayingTurnIdx =
    audioMode === 'live' && isPlaying && detail?.segments[currentSegmentIdx]
      ? detail.segments[currentSegmentIdx].turn_index
      : null;

  return (
    <div className="min-h-screen flex flex-col bg-slate-950 text-slate-100 pb-28">
      {/* Top Navbar & New Debate Control Bar */}
      <header className="sticky top-0 z-30 border-b border-slate-800/80 bg-slate-950/90 backdrop-blur-md">
        <div className="max-w-[1600px] mx-auto px-4 py-3">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
            <div className="flex items-center gap-3">
              <button
                onClick={() => setShowHistory((v) => !v)}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-800 text-xs font-medium text-slate-300 transition"
                title="Toggle Past Debates Library"
              >
                <History className="w-4 h-4 text-indigo-400" />
                <span>Past Debates ({debates.length})</span>
              </button>
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-indigo-600/20 border border-indigo-500/40 flex items-center justify-center">
                  <Scale className="w-4 h-4 text-indigo-400" />
                </div>
                <div>
                  <h1 className="text-base font-bold tracking-tight text-white flex items-center gap-2">
                    Tech Debate Arena
                    {modelsInfo && (
                      <span className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full bg-indigo-500/15 text-indigo-300 border border-indigo-500/30 font-semibold">
                        {modelsInfo.profile} mode
                      </span>
                    )}
                  </h1>
                </div>
              </div>
            </div>

            {/* Preset Topic Selector */}
            {modelsInfo && modelsInfo.preset_topics.length > 0 && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-400">Preset motion:</span>
                <select
                  value={modelsInfo.preset_topics.includes(topic) ? topic : ''}
                  onChange={(e) => {
                    if (e.target.value) {
                      setTopic(e.target.value);
                      setFormError(null);
                    }
                  }}
                  className="bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 max-w-xs sm:max-w-md truncate"
                >
                  <option value="" disabled>
                    Choose a preset engineering motion...
                  </option>
                  {modelsInfo.preset_topics.map((pt) => (
                    <option key={pt} value={pt}>
                      {pt}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          {/* Topic Input + Role Model Dropdowns + Action Button */}
          <form onSubmit={handleStartDebate} className="grid grid-cols-1 lg:grid-cols-12 gap-2.5 items-center">
            <div className="lg:col-span-5 relative">
              <input
                type="text"
                value={topic}
                onChange={(e) => {
                  setTopic(e.target.value);
                  if (formError) setFormError(null);
                }}
                maxLength={200}
                placeholder="Enter a technology debate motion (e.g. Rust is better than Go for CLIs)..."
                className="w-full bg-slate-900/90 border border-slate-800 focus:border-indigo-500 rounded-lg pl-3.5 pr-14 py-2 text-sm text-white placeholder-slate-500 focus:outline-none transition"
              />
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[11px] text-slate-500 font-mono">
                {topic.length}/200
              </span>
            </div>

            {/* Pro, Con, Judge Dropdowns */}
            <div className="lg:col-span-5 grid grid-cols-3 gap-2">
              <div className="flex items-center bg-emerald-950/30 border border-emerald-500/30 rounded-lg px-2.5 py-1.5">
                <span className="text-[10px] font-bold uppercase tracking-wider text-emerald-400 mr-2 shrink-0">
                  Pro
                </span>
                <select
                  value={proModel}
                  onChange={(e) => setProModel(e.target.value)}
                  className="bg-transparent text-xs text-slate-100 font-mono w-full focus:outline-none truncate"
                >
                  {modelsInfo?.models.map((m) => (
                    <option key={m.name} value={m.name} className="bg-slate-900 text-slate-100">
                      {m.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="flex items-center bg-rose-950/30 border border-rose-500/30 rounded-lg px-2.5 py-1.5">
                <span className="text-[10px] font-bold uppercase tracking-wider text-rose-400 mr-2 shrink-0">
                  Con
                </span>
                <select
                  value={conModel}
                  onChange={(e) => setConModel(e.target.value)}
                  className="bg-transparent text-xs text-slate-100 font-mono w-full focus:outline-none truncate"
                >
                  {modelsInfo?.models.map((m) => (
                    <option key={m.name} value={m.name} className="bg-slate-900 text-slate-100">
                      {m.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="flex items-center bg-amber-950/30 border border-amber-500/30 rounded-lg px-2.5 py-1.5">
                <span className="text-[10px] font-bold uppercase tracking-wider text-amber-400 mr-2 shrink-0">
                  Judge
                </span>
                <select
                  value={judgeModel}
                  onChange={(e) => setJudgeModel(e.target.value)}
                  className="bg-transparent text-xs text-slate-100 font-mono w-full focus:outline-none truncate"
                >
                  {modelsInfo?.models.map((m) => (
                    <option key={m.name} value={m.name} className="bg-slate-900 text-slate-100">
                      {m.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Submit / Cancel Buttons */}
            <div className="lg:col-span-2 flex items-center gap-2">
              {isRunning ? (
                <button
                  type="button"
                  onClick={handleCancelDebate}
                  disabled={detail?.status === 'cancelling'}
                  className="w-full flex items-center justify-center gap-2 bg-rose-600 hover:bg-rose-500 disabled:opacity-50 text-white font-semibold text-xs py-2.5 px-4 rounded-lg shadow transition cursor-pointer"
                >
                  <Square className="w-3.5 h-3.5 fill-current" />
                  <span>{detail?.status === 'cancelling' ? 'Stopping...' : 'Stop Debate'}</span>
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={submitting || !topic.trim()}
                  className="w-full flex items-center justify-center gap-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-semibold text-xs py-2.5 px-4 rounded-lg shadow transition cursor-pointer"
                >
                  {submitting ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Zap className="w-4 h-4 fill-current" />
                  )}
                  <span>Start Debate</span>
                </button>
              )}
            </div>
          </form>

          {formError && (
            <div className="mt-2.5 flex items-center gap-2 text-xs text-rose-300 bg-rose-950/50 border border-rose-500/40 rounded-lg px-3 py-2">
              <ShieldAlert className="w-4 h-4 text-rose-400 shrink-0" />
              <span>{formError}</span>
            </div>
          )}
        </div>
      </header>

      {/* Main Content Area */}
      <div className="flex-1 max-w-[1600px] w-full mx-auto flex overflow-hidden">
        {/* Left Sidebar: Past Debates Library */}
        {showHistory && (
          <aside className="w-72 shrink-0 border-r border-slate-800/80 bg-slate-950/60 p-3 overflow-y-auto hidden md:block">
            <div className="flex items-center justify-between mb-3 px-1">
              <h2 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                Debate Runs ({debates.length})
              </h2>
            </div>
            <div className="space-y-2">
              {debates.map((item) => {
                const active = item.id === selectedId;
                return (
                  <button
                    key={item.id}
                    onClick={() => setSelectedId(item.id)}
                    className={`w-full text-left p-3 rounded-xl border transition cursor-pointer ${
                      active
                        ? 'bg-indigo-950/40 border-indigo-500/50 shadow-sm'
                        : 'bg-slate-900/50 hover:bg-slate-900 border-slate-800/70'
                    }`}
                  >
                    <p className="text-xs font-semibold text-slate-100 line-clamp-2 mb-1.5">
                      {item.topic}
                    </p>
                    <div className="flex items-center justify-between text-[11px] text-slate-400 mb-2">
                      <span className="font-mono text-[10px]">
                        {item.created_at.replace('T', ' ').slice(0, 16)}
                      </span>
                      {item.status === 'running' ? (
                        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 text-[10px] font-semibold">
                          <Loader2 className="w-2.5 h-2.5 animate-spin" /> LIVE
                        </span>
                      ) : item.winner ? (
                        <span
                          className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${
                            item.winner === 'pro'
                              ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                              : item.winner === 'con'
                              ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                              : 'bg-slate-700 text-slate-300'
                          }`}
                        >
                          {item.winner} won{' '}
                          {item.totals ? `(${item.totals.pro}–${item.totals.con})` : ''}
                        </span>
                      ) : (
                        <span className="px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 text-[10px]">
                          {item.status}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 text-[10px] text-slate-500 font-mono truncate">
                      <span className="text-emerald-400/80">{item.models.pro}</span>
                      <span>vs</span>
                      <span className="text-rose-400/80">{item.models.con}</span>
                    </div>
                  </button>
                );
              })}
            </div>
          </aside>
        )}

        {/* Center + Right Workspace */}
        <main className="flex-1 overflow-y-auto p-4 md:p-6 space-y-6">
          {!detail ? (
            <div className="flex flex-col items-center justify-center py-24 text-center">
              <Scale className="w-12 h-12 text-slate-700 mb-3" />
              <h2 className="text-lg font-semibold text-slate-300">No Debate Selected</h2>
              <p className="text-sm text-slate-500 max-w-md mt-1">
                Pick a preset motion or enter your own tech topic above and click Start Debate.
              </p>
            </div>
          ) : (
            <>
              {/* Active Debate Header Card + Phase Stepper */}
              <section className="rounded-2xl bg-slate-900/70 border border-slate-800/90 p-5 space-y-4">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2 text-xs text-slate-400">
                      <span className="font-mono">{detail.id}</span>
                      {detail.state.counter_claim && (
                        <span className="text-slate-500">
                          • Counter-claim: <em className="text-slate-400">"{detail.state.counter_claim}"</em>
                        </span>
                      )}
                    </div>
                    <h2 className="text-xl md:text-2xl font-bold text-white">{detail.state.topic}</h2>
                  </div>

                  {/* Resume Button if interrupted/cancelled */}
                  {(detail.status === 'interrupted' || detail.status === 'cancelled' || detail.status === 'error') &&
                    !detail.state.phases_done.includes('done') && (
                      <button
                        onClick={handleResumeDebate}
                        className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-amber-200 text-xs font-semibold transition cursor-pointer"
                      >
                        <RotateCcw className="w-3.5 h-3.5" />
                        <span>Resume Interrupted Run</span>
                      </button>
                    )}
                </div>

                {/* Role Pills */}
                <div className="flex flex-wrap items-center gap-3 text-xs">
                  <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-emerald-950/40 border border-emerald-500/30">
                    <span className="w-2 h-2 rounded-full bg-emerald-400" />
                    <span className="text-emerald-300 font-semibold">PRO (For):</span>
                    <code className="text-emerald-100 font-mono">{detail.state.models.pro}</code>
                  </div>
                  <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-rose-950/40 border border-rose-500/30">
                    <span className="w-2 h-2 rounded-full bg-rose-400" />
                    <span className="text-rose-300 font-semibold">CON (Against):</span>
                    <code className="text-rose-100 font-mono">{detail.state.models.con}</code>
                  </div>
                  <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-amber-950/40 border border-amber-500/30">
                    <Award className="w-3.5 h-3.5 text-amber-400" />
                    <span className="text-amber-300 font-semibold">JUDGE:</span>
                    <code className="text-amber-100 font-mono">{detail.state.models.judge}</code>
                  </div>
                </div>

                {/* Phase Progress Stepper */}
                <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2 pt-1">
                  {detail.phases_plan.map((phase) => {
                    const done = detail.state.phases_done.includes(phase);
                    const current =
                      isRunning &&
                      !done &&
                      detail.phases_plan.find((p) => !detail.state.phases_done.includes(p)) === phase;
                    const secs = detail.state.timings_s[phase];
                    return (
                      <div
                        key={phase}
                        className={`flex items-center justify-between px-3 py-2 rounded-xl border text-xs transition ${
                          done
                            ? 'bg-emerald-950/25 border-emerald-500/30 text-emerald-200'
                            : current
                            ? 'bg-indigo-950/50 border-indigo-500/60 text-indigo-200 ring-1 ring-indigo-500/30'
                            : 'bg-slate-950/50 border-slate-800/70 text-slate-500'
                        }`}
                      >
                        <div className="flex items-center gap-1.5 truncate">
                          {done ? (
                            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                          ) : current ? (
                            <Loader2 className="w-3.5 h-3.5 text-indigo-400 animate-spin shrink-0" />
                          ) : (
                            <Clock className="w-3.5 h-3.5 text-slate-600 shrink-0" />
                          )}
                          <span className="font-medium truncate">{PHASE_LABELS[phase] || phase}</span>
                        </div>
                        {secs !== undefined && (
                          <span className="text-[10px] font-mono text-slate-400 ml-1">{secs}s</span>
                        )}
                      </div>
                    );
                  })}
                </div>

                {/* Live Sub-Step Activity Banner */}
                {isRunning && (
                  <div className="flex items-center justify-between gap-3 px-4 py-2.5 rounded-xl bg-indigo-950/40 border border-indigo-500/40 text-xs text-indigo-200">
                    <div className="flex items-center gap-2.5">
                      <Activity className="w-4 h-4 text-indigo-400 animate-pulse shrink-0" />
                      <span className="font-medium">{describeStep(detail.current_step)}</span>
                    </div>
                    {detail.current_step?.status === 'rejected' && (
                      <span className="px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 text-[11px] font-mono">
                        Validation Retry
                      </span>
                    )}
                  </div>
                )}

                {detail.error && (
                  <div className="flex items-center gap-2.5 px-4 py-2.5 rounded-xl bg-rose-950/50 border border-rose-500/40 text-xs text-rose-200">
                    <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
                    <span>{detail.error}</span>
                  </div>
                )}
              </section>

              {/* Research & Evidence Ledger Accordion */}
              <section className="rounded-2xl bg-slate-900/50 border border-slate-800/80 overflow-hidden">
                <button
                  onClick={() => setShowResearch((v) => !v)}
                  className="w-full flex items-center justify-between px-5 py-3.5 bg-slate-900/80 hover:bg-slate-900 transition text-left cursor-pointer"
                >
                  <div className="flex items-center gap-2.5">
                    <Search className="w-4 h-4 text-indigo-400" />
                    <span className="text-sm font-semibold text-slate-200">
                      Web Research & Evidence Ledger ({detail.state.ledger.items.length} passages)
                    </span>
                  </div>
                  {showResearch ? (
                    <ChevronDown className="w-4 h-4 text-slate-400" />
                  ) : (
                    <ChevronRight className="w-4 h-4 text-slate-400" />
                  )}
                </button>

                {showResearch && (
                  <div className="p-5 space-y-4 border-t border-slate-800/70">
                    {/* Search Queries per side */}
                    {(detail.state.queries.pro || detail.state.queries.con) && (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="p-3.5 rounded-xl bg-emerald-950/20 border border-emerald-500/20">
                          <div className="text-[11px] font-bold uppercase tracking-wider text-emerald-400 mb-2">
                            Pro Search Queries ({detail.state.models.pro})
                          </div>
                          <ul className="space-y-1 text-xs text-slate-300">
                            {(detail.state.queries.pro || []).map((q, idx) => (
                              <li key={idx} className="flex items-center gap-2">
                                <span className="text-emerald-500 font-mono">#{idx + 1}</span>
                                <span>{q}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                        <div className="p-3.5 rounded-xl bg-rose-950/20 border border-rose-500/20">
                          <div className="text-[11px] font-bold uppercase tracking-wider text-rose-400 mb-2">
                            Con Search Queries ({detail.state.models.con})
                          </div>
                          <ul className="space-y-1 text-xs text-slate-300">
                            {(detail.state.queries.con || []).map((q, idx) => (
                              <li key={idx} className="flex items-center gap-2">
                                <span className="text-rose-500 font-mono">#{idx + 1}</span>
                                <span>{q}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      </div>
                    )}

                    {/* Evidence Cards Grid */}
                    {detail.state.ledger.items.length > 0 ? (
                      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                        {detail.state.ledger.items.map((ev) => {
                          const isHighlighted = highlightedCite === ev.id;
                          return (
                            <div
                              id={`evidence-${ev.id}`}
                              key={ev.id}
                              className={`p-3.5 rounded-xl border transition flex flex-col justify-between gap-2 ${
                                isHighlighted
                                  ? 'bg-indigo-950/60 border-indigo-400 ring-2 ring-indigo-500/40'
                                  : 'bg-slate-950/70 border-slate-800/80 hover:border-slate-700'
                              }`}
                            >
                              <div className="space-y-1.5">
                                <div className="flex items-center justify-between gap-2">
                                  <div className="flex items-center gap-2 min-w-0">
                                    <span
                                      className={`px-2 py-0.5 rounded text-xs font-mono font-bold shrink-0 ${
                                        ev.side === 'pro'
                                          ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                                          : 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                                      }`}
                                    >
                                      {ev.id}
                                    </span>
                                    <a
                                      href={ev.url}
                                      target="_blank"
                                      rel="noreferrer"
                                      className="text-xs font-semibold text-indigo-300 hover:underline truncate flex items-center gap-1"
                                    >
                                      <span className="truncate">{ev.title || ev.domain}</span>
                                      <ExternalLink className="w-3 h-3 shrink-0" />
                                    </a>
                                  </div>
                                  <span className="text-[10px] font-mono text-slate-500 shrink-0">
                                    {ev.domain}
                                  </span>
                                </div>
                                <p className="text-xs text-slate-300 leading-relaxed line-clamp-4">
                                  {ev.snippet}
                                </p>
                              </div>
                              <div className="text-[10px] text-slate-500 truncate pt-1 border-t border-slate-800/60">
                                Query: <span className="text-slate-400">{ev.query}</span>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <p className="text-xs text-slate-500 italic">
                        {isRunning ? 'Gathering web evidence via SearXNG...' : 'No web evidence recorded for this run.'}
                      </p>
                    )}
                  </div>
                )}
              </section>

              {/* Live Debate Arena — Grouped by Phase */}
              <section className="space-y-6">
                {Object.entries(PHASE_HEADINGS).map(([phaseKey, heading]) => {
                  const phaseTurns = detail.state.turns
                    .map((t, globalIdx) => ({ turn: t, globalIdx }))
                    .filter((item) => item.turn.phase === phaseKey);

                  const isCurrentPhase =
                    isRunning &&
                    detail.current_step?.phase === phaseKey &&
                    phaseTurns.length < 2;

                  if (phaseTurns.length === 0 && !isCurrentPhase) return null;

                  return (
                    <div key={phaseKey} className="space-y-4">
                      <div className="flex items-center gap-3">
                        <div className="h-px flex-1 bg-slate-800" />
                        <h3 className="text-xs font-bold uppercase tracking-widest text-slate-400 px-2">
                          {heading}
                        </h3>
                        <div className="h-px flex-1 bg-slate-800" />
                      </div>

                      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
                        {phaseTurns.map(({ turn, globalIdx }) => {
                          const isPro = turn.side === 'pro';
                          const sentences = splitIntoSentences(turn.text);
                          const isTurnSpeaking = activePlayingTurnIdx === globalIdx;

                          return (
                            <div
                              key={globalIdx}
                              className={`rounded-2xl border p-5 space-y-3.5 transition ${
                                isPro
                                  ? 'bg-emerald-950/15 border-emerald-500/30'
                                  : 'bg-rose-950/15 border-rose-500/30'
                              } ${isTurnSpeaking ? 'ring-2 ring-indigo-400 shadow-lg shadow-indigo-950/50' : ''}`}
                            >
                              {/* Turn Card Header */}
                              <div className="flex items-center justify-between gap-2">
                                <div className="flex items-center gap-2">
                                  <span
                                    className={`px-2.5 py-0.5 rounded-md text-xs font-bold uppercase tracking-wider ${
                                      isPro
                                        ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                                        : 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                                    }`}
                                  >
                                    {isPro ? 'Pro' : 'Con'}
                                  </span>
                                  <code className="text-xs font-mono text-slate-300">{turn.model}</code>
                                  {isTurnSpeaking && (
                                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 text-[10px] font-semibold animate-pulse">
                                      <Volume2 className="w-3 h-3" /> Speaking
                                    </span>
                                  )}
                                </div>

                                <div className="flex items-center gap-2">
                                  {/* Play single turn audio segment button */}
                                  {detail.segments.some((s) => s.turn_index === globalIdx) && (
                                    <button
                                      onClick={() => {
                                        const segIdx = detail.segments.findIndex(
                                          (s) => s.turn_index === globalIdx
                                        );
                                        if (segIdx !== -1) playSegmentAt(segIdx);
                                      }}
                                      className="flex items-center gap-1 px-2 py-1 rounded-lg bg-slate-800/80 hover:bg-slate-700 text-[11px] text-slate-200 transition cursor-pointer"
                                      title="Play this turn's audio"
                                    >
                                      <Play className="w-3 h-3 fill-current text-indigo-400" />
                                      <span>Play Turn</span>
                                    </button>
                                  )}
                                  <span
                                    className={`text-[11px] font-mono px-2 py-0.5 rounded ${
                                      turn.attempts === 1
                                        ? 'bg-slate-800/80 text-slate-400'
                                        : 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                                    }`}
                                    title="Validation attempts"
                                  >
                                    {turn.attempts === 1 ? '1st try' : `${turn.attempts} tries`}
                                  </span>
                                </div>
                              </div>

                              {/* Opponent Quote Block (for Rebuttals) */}
                              {turn.quote && (
                                <div className="p-3 rounded-xl bg-slate-950/70 border border-slate-800/90 space-y-1">
                                  <div className="flex items-center justify-between text-[11px] text-slate-400">
                                    <span className="flex items-center gap-1.5 font-medium">
                                      <Quote className="w-3 h-3 text-indigo-400" />
                                      Quoting opponent:
                                    </span>
                                    {turn.quote_matched ? (
                                      <span className="text-emerald-400 font-mono text-[10px]">
                                        ✓ Verbatim match
                                      </span>
                                    ) : (
                                      <span className="text-amber-400 font-mono text-[10px]">
                                        ⚠ Paraphrased
                                      </span>
                                    )}
                                  </div>
                                  <blockquote className="text-xs italic text-slate-300 pl-2 border-l-2 border-indigo-500/50">
                                    “{turn.quote}”
                                  </blockquote>
                                </div>
                              )}

                              {/* Spoken Turn Sentences (Synced with Audio) */}
                              <div className="text-sm text-slate-100 leading-relaxed space-x-1">
                                {sentences.map((sent, sentIdx) => {
                                  const matchedCue = turnSentenceCueMap.get(`${globalIdx}:${sentIdx}`);
                                  const isSentenceActive =
                                    activeCue && matchedCue && activeCue.index === matchedCue.index;

                                  return (
                                    <span
                                      key={sentIdx}
                                      onClick={() => matchedCue && seekToCue(matchedCue)}
                                      className={`inline rounded px-1 py-0.5 transition ${
                                        matchedCue ? 'cursor-pointer hover:bg-indigo-500/20' : ''
                                      } ${
                                        isSentenceActive
                                          ? 'bg-indigo-500/35 text-white ring-1 ring-indigo-400/50'
                                          : ''
                                      }`}
                                      title={
                                        matchedCue
                                          ? `Click to seek audio to ${formatMs(matchedCue.start_ms)}`
                                          : undefined
                                      }
                                    >
                                      {sent}
                                    </span>
                                  );
                                })}
                              </div>

                              {/* Citations + New Point Footer */}
                              {(turn.cites.length > 0 || turn.new_point) && (
                                <div className="pt-2 border-t border-slate-800/60 flex flex-wrap items-center justify-between gap-2">
                                  <div className="flex flex-wrap items-center gap-1.5">
                                    {turn.cites.map((citeId) => {
                                      const ev = evidenceById[citeId];
                                      const isOpen =
                                        activePopoverCite?.turnIdx === globalIdx &&
                                        activePopoverCite?.citeId === citeId;
                                      return (
                                        <div key={citeId} className="relative">
                                          <button
                                            onClick={() =>
                                              setActivePopoverCite(
                                                isOpen ? null : { turnIdx: globalIdx, citeId }
                                              )
                                            }
                                            className="px-2 py-0.5 rounded-md bg-indigo-500/20 hover:bg-indigo-500/30 border border-indigo-500/40 text-indigo-300 font-mono text-xs font-semibold transition cursor-pointer"
                                          >
                                            [{citeId}] {ev ? `· ${ev.domain}` : ''}
                                          </button>
                                          {isOpen && ev && (
                                            <div className="absolute left-0 bottom-full mb-2 w-80 p-3 rounded-xl bg-slate-900 border border-indigo-500/50 shadow-xl z-20 space-y-1.5">
                                              <div className="flex items-center justify-between gap-2">
                                                <span className="text-xs font-bold font-mono text-indigo-300">
                                                  {ev.id} — {ev.domain}
                                                </span>
                                                <button
                                                  onClick={() => jumpToCitation(citeId)}
                                                  className="text-[10px] text-indigo-400 hover:underline cursor-pointer"
                                                >
                                                  View in Ledger →
                                                </button>
                                              </div>
                                              <a
                                                href={ev.url}
                                                target="_blank"
                                                rel="noreferrer"
                                                className="text-xs font-semibold text-white hover:underline block truncate"
                                              >
                                                {ev.title || ev.url}
                                              </a>
                                              <p className="text-[11px] text-slate-300 line-clamp-4">
                                                {ev.snippet}
                                              </p>
                                            </div>
                                          )}
                                        </div>
                                      );
                                    })}
                                  </div>

                                  {turn.new_point && (
                                    <span className="text-[11px] text-slate-400 flex items-center gap-1">
                                      <Sparkles className="w-3 h-3 text-amber-400 shrink-0" />
                                      <span className="truncate max-w-xs">{turn.new_point}</span>
                                    </span>
                                  )}
                                </div>
                              )}

                              {/* Validation Warnings */}
                              {turn.warnings.length > 0 && (
                                <div className="space-y-1 pt-1">
                                  {turn.warnings.map((w, wIdx) => (
                                    <div
                                      key={wIdx}
                                      className="text-[11px] text-amber-300/90 bg-amber-950/40 border border-amber-500/30 rounded-lg px-2.5 py-1 flex items-center gap-1.5"
                                    >
                                      <AlertTriangle className="w-3 h-3 shrink-0 text-amber-400" />
                                      <span>{w}</span>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          );
                        })}

                        {/* Skeleton placeholder when generating the next turn in this phase */}
                        {isCurrentPhase && (
                          <div className="rounded-2xl border border-dashed border-indigo-500/40 bg-indigo-950/10 p-6 flex flex-col items-center justify-center text-center space-y-2 min-h-[160px]">
                            <Loader2 className="w-6 h-6 text-indigo-400 animate-spin" />
                            <p className="text-xs font-medium text-indigo-200">
                              {describeStep(detail.current_step)}
                            </p>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </section>

              {/* Judge Verdict & Dual-Pass Rubric */}
              {detail.state.judge && (
                <section className="rounded-2xl bg-gradient-to-br from-slate-900 via-slate-900 to-indigo-950/40 border border-amber-500/40 p-6 space-y-5 shadow-lg">
                  <div className="flex flex-wrap items-center justify-between gap-4">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-xl bg-amber-500/20 border border-amber-500/40 flex items-center justify-center">
                        <Award className="w-5 h-5 text-amber-400" />
                      </div>
                      <div>
                        <div className="text-xs font-bold uppercase tracking-wider text-amber-400">
                          Official Judge Verdict ({detail.state.models.judge})
                        </div>
                        <h3 className="text-xl font-bold text-white">
                          Winner:{' '}
                          <span
                            className={
                              detail.state.judge.winner === 'pro'
                                ? 'text-emerald-400'
                                : detail.state.judge.winner === 'con'
                                ? 'text-rose-400'
                                : 'text-amber-300'
                            }
                          >
                            {detail.state.judge.winner.toUpperCase()}
                          </span>{' '}
                          ({detail.state.judge.totals.pro} vs {detail.state.judge.totals.con} / 40)
                        </h3>
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <span
                        className={`px-3 py-1 rounded-full text-xs font-semibold border ${
                          detail.state.judge.position_consistent
                            ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                            : 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                        }`}
                      >
                        {detail.state.judge.position_consistent
                          ? '✓ Position-Consistent Across Both Passes'
                          : '⚠ Order-Sensitive (Passes Disagreed)'}
                      </span>
                    </div>
                  </div>

                  <p className="text-sm text-slate-200 leading-relaxed bg-slate-950/60 border border-slate-800 rounded-xl p-4">
                    {detail.state.judge.reason}
                  </p>

                  {/* Rubric Score Comparison Table */}
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    <div className="space-y-3">
                      <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                        Averaged Rubric Breakdown (Out of 10 per Criterion)
                      </h4>
                      <div className="space-y-2.5">
                        {Object.keys(detail.state.judge.average.pro).map((criterion) => {
                          const proScore = detail.state.judge!.average.pro[criterion];
                          const conScore = detail.state.judge!.average.con[criterion];
                          return (
                            <div
                              key={criterion}
                              className="p-3 rounded-xl bg-slate-950/60 border border-slate-800/80 space-y-1.5"
                            >
                              <div className="flex items-center justify-between text-xs">
                                <span className="font-mono text-emerald-400 font-bold">
                                  Pro: {proScore}
                                </span>
                                <span className="font-semibold text-slate-300 capitalize">
                                  {criterion.replace(/_/g, ' ')}
                                </span>
                                <span className="font-mono text-rose-400 font-bold">
                                  Con: {conScore}
                                </span>
                              </div>
                              <div className="grid grid-cols-2 gap-1 h-2">
                                <div className="bg-slate-800 rounded-l overflow-hidden flex justify-end">
                                  <div
                                    className="bg-emerald-500 h-full"
                                    style={{ width: `${(proScore / 10) * 100}%` }}
                                  />
                                </div>
                                <div className="bg-slate-800 rounded-r overflow-hidden">
                                  <div
                                    className="bg-rose-500 h-full"
                                    style={{ width: `${(conScore / 10) * 100}%` }}
                                  />
                                </div>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>

                    {/* Dual-Pass Audit */}
                    <div className="space-y-3">
                      <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                        Dual-Pass Position Bias Audit
                      </h4>
                      <div className="space-y-2.5">
                        {detail.state.judge.runs.map((pass, idx) => (
                          <div
                            key={idx}
                            className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800/80 space-y-1.5"
                          >
                            <div className="flex items-center justify-between text-xs">
                              <span className="font-mono text-slate-400">
                                Pass #{idx + 1} ({pass.order})
                              </span>
                              <span className="font-bold uppercase text-amber-300">
                                Winner: {pass.winner}
                              </span>
                            </div>
                            <p className="text-xs text-slate-300">{pass.reason}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </section>
              )}
            </>
          )}
        </main>
      </div>

      {/* Bottom Sticky Audio Player + Live Caption Bar */}
      {detail && (detail.audio_url || detail.segments.length > 0) && (
        <footer className="fixed bottom-0 inset-x-0 z-40 border-t border-slate-800 bg-slate-950/95 backdrop-blur-md px-4 py-2.5 shadow-2xl">
          <audio
            ref={audioRef}
            onPlay={() => setIsPlaying(true)}
            onPause={() => setIsPlaying(false)}
            onTimeUpdate={(e) => setCurrentTimeMs(e.currentTarget.currentTime * 1000)}
            onLoadedMetadata={(e) => setDurationMs(e.currentTarget.duration * 1000)}
            onEnded={() => {
              setIsPlaying(false);
              // In live mode, advance to the next segment automatically if available
              if (audioMode === 'live' && detail.segments.length > currentSegmentIdx + 1) {
                playSegmentAt(currentSegmentIdx + 1);
              }
            }}
          />

          <div className="max-w-[1600px] mx-auto flex flex-col gap-1.5">
            {/* Active Caption Ticker */}
            {activeCue && audioMode === 'master' && (
              <div className="flex items-center justify-center gap-2 text-xs text-center px-3 py-1 rounded-lg bg-slate-900/90 border border-slate-800/80">
                <span
                  className={`font-bold uppercase text-[10px] px-1.5 py-0.5 rounded ${
                    activeCue.speaker === 'pro'
                      ? 'bg-emerald-500/20 text-emerald-300'
                      : activeCue.speaker === 'con'
                      ? 'bg-rose-500/20 text-rose-300'
                      : 'bg-indigo-500/20 text-indigo-300'
                  }`}
                >
                  {activeCue.speaker}
                </span>
                <span className="text-slate-200 truncate">{activeCue.text}</span>
              </div>
            )}

            <div className="flex flex-wrap items-center justify-between gap-4">
              {/* Play/Pause & Mode Selector */}
              <div className="flex items-center gap-3">
                <button
                  onClick={togglePlayPause}
                  className="w-9 h-9 rounded-full bg-indigo-600 hover:bg-indigo-500 text-white flex items-center justify-center shadow transition cursor-pointer"
                >
                  {isPlaying ? (
                    <Pause className="w-4 h-4 fill-current" />
                  ) : (
                    <Play className="w-4 h-4 fill-current ml-0.5" />
                  )}
                </button>

                <div className="flex items-center rounded-lg bg-slate-900 border border-slate-800 p-0.5 text-xs">
                  {detail.audio_url && (
                    <button
                      onClick={() => {
                        setAudioMode('master');
                        if (audioRef.current && detail.audio_url) {
                          audioRef.current.src = detail.audio_url;
                        }
                      }}
                      className={`px-2.5 py-1 rounded-md font-medium transition cursor-pointer ${
                        audioMode === 'master'
                          ? 'bg-indigo-600 text-white'
                          : 'text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      Master MP3
                    </button>
                  )}
                  {detail.segments.length > 0 && (
                    <button
                      onClick={() => setAudioMode('live')}
                      className={`px-2.5 py-1 rounded-md font-medium transition cursor-pointer ${
                        audioMode === 'live'
                          ? 'bg-indigo-600 text-white'
                          : 'text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      Live Turn Segments ({detail.segments.length})
                    </button>
                  )}
                </div>
              </div>

              {/* Scrubber or Segment Pills */}
              {audioMode === 'master' && detail.audio_url ? (
                <div className="flex-1 flex items-center gap-3 min-w-[220px]">
                  <span className="text-xs font-mono text-slate-400 w-10 text-right">
                    {formatMs(currentTimeMs)}
                  </span>
                  <input
                    type="range"
                    min={0}
                    max={durationMs || 100}
                    value={currentTimeMs}
                    onChange={(e) => {
                      const ms = Number(e.target.value);
                      setCurrentTimeMs(ms);
                      if (audioRef.current) {
                        audioRef.current.currentTime = ms / 1000;
                      }
                    }}
                    className="flex-1 accent-indigo-500 h-1.5 bg-slate-800 rounded-lg cursor-pointer"
                  />
                  <span className="text-xs font-mono text-slate-400 w-10">
                    {formatMs(durationMs)}
                  </span>
                </div>
              ) : (
                <div className="flex-1 flex items-center gap-1.5 overflow-x-auto py-1">
                  {detail.segments.map((seg, idx) => (
                    <button
                      key={seg.segment_id}
                      onClick={() => playSegmentAt(idx)}
                      className={`px-2.5 py-1 rounded-lg text-xs font-mono shrink-0 border transition cursor-pointer ${
                        currentSegmentIdx === idx && audioMode === 'live'
                          ? 'bg-indigo-600/30 border-indigo-400 text-white'
                          : 'bg-slate-900 border-slate-800 text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      {idx + 1}. {seg.speaker.toUpperCase()}
                    </button>
                  ))}
                </div>
              )}

              {/* Right Controls: Live Auto-Play Toggle & Speed */}
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setLiveAutoPlay((v) => !v)}
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs font-medium transition cursor-pointer ${
                    liveAutoPlay
                      ? 'bg-emerald-950/40 border-emerald-500/40 text-emerald-300'
                      : 'bg-slate-900 border-slate-800 text-slate-400'
                  }`}
                  title="Automatically play each turn's audio as soon as Kokoro finishes synthesizing it"
                >
                  {liveAutoPlay ? (
                    <Volume2 className="w-3.5 h-3.5 text-emerald-400" />
                  ) : (
                    <VolumeX className="w-3.5 h-3.5 text-slate-500" />
                  )}
                  <span>Auto-Play Live</span>
                </button>

                <select
                  value={playbackRate}
                  onChange={(e) => {
                    const rate = Number(e.target.value);
                    setPlaybackRate(rate);
                    if (audioRef.current) audioRef.current.playbackRate = rate;
                  }}
                  className="bg-slate-900 border border-slate-800 rounded-lg px-2 py-1 text-xs font-mono text-slate-300"
                >
                  <option value={1}>1.0x</option>
                  <option value={1.15}>1.15x</option>
                  <option value={1.25}>1.25x</option>
                  <option value={1.5}>1.5x</option>
                </select>
              </div>
            </div>
          </div>
        </footer>
      )}
    </div>
  );
}

