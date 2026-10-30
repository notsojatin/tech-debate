export type Side = 'pro' | 'con';

export interface ModelOption {
  name: string;
  label: string;
  think: boolean | 'low' | 'medium' | 'high' | null;
  temperature: number;
}

export type SpeechLength = 'short' | 'standard' | 'long';

export interface WordLimits {
  opening: number;
  rebuttal: number;
  closing: number;
}

export interface DebateOptions {
  rebuttal_rounds: { min: number; max: number; default: number };
  speech_lengths: Record<SpeechLength, WordLimits>;
  default_speech_length: SpeechLength;
}

export interface ModelsResponse {
  profile: string;
  models: ModelOption[];
  defaults: {
    pro: string;
    con: string;
    judge: string;
  };
  demo_topic: string;
  preset_topics: string[];
  debate_options: DebateOptions;
  active_run_id: string | null;
}

export interface DebateSummary {
  id: string;
  topic: string;
  created_at: string;
  models: Record<string, string>;
  phases_done: string[];
  status: 'done' | 'running' | 'cancelling' | 'cancelled' | 'interrupted' | 'error';
  winner: 'pro' | 'con' | 'tie' | null;
  totals: { pro: number; con: number } | null;
  rebuttal_rounds: number;
  turn_count: number;
  evidence_count: number;
  has_audio: boolean;
}

export interface EvidenceItem {
  id: string;
  side: Side;
  query: string;
  url: string;
  domain: string;
  title: string;
  snippet: string;
}

export interface TurnItem {
  phase: string;
  side: Side;
  model: string;
  text: string;
  cites: string[];
  quote: string | null;
  attacks: string | null;
  new_point: string | null;
  quote_matched: boolean | null;
  attempts: number;
  warnings: string[];
}

export interface JudgePass {
  order: string;
  pro: Record<string, number>;
  con: Record<string, number>;
  winner: 'pro' | 'con' | 'tie';
  reason: string;
}

export interface JudgeResult {
  runs: JudgePass[];
  average: {
    pro: Record<string, number>;
    con: Record<string, number>;
  };
  totals: {
    pro: number;
    con: number;
  };
  winner: 'pro' | 'con' | 'tie';
  reason: string;
  position_consistent: boolean;
}

export interface DebateState {
  topic: string;
  run_dir: string;
  models: {
    pro: string;
    con: string;
    judge: string;
  };
  rebuttal_rounds: number | null;
  speech_length: SpeechLength | null;
  phases_done: string[];
  ledger: {
    items: EvidenceItem[];
  };
  queries: {
    pro?: string[];
    con?: string[];
  };
  counter_claim: string | null;
  turns: TurnItem[];
  points_made: {
    pro: string[];
    con: string[];
  };
  judge: JudgeResult | null;
  warnings: string[];
  timings_s: Record<string, number>;
}

export interface SrtCue {
  index: number;
  start_ms: number;
  end_ms: number;
  speaker: 'pro' | 'con' | 'narrator';
  text: string;
}

export interface AudioSegment {
  segment_id: string;
  filename: string;
  speaker: 'pro' | 'con' | 'narrator';
  phase?: string;
  turn_index: number | null;
  duration_s?: number;
  cues?: Array<{
    start_ms: number;
    end_ms: number;
    speaker: string;
    text: string;
  }>;
  url: string;
}

export interface CurrentStep {
  type: string;
  phase?: string;
  side?: Side;
  model?: string;
  attempt?: number;
  max_attempts?: number;
  status?: string;
  message?: string;
  errors?: string[];
  timestamp?: number;
}

export interface DebateDetail {
  id: string;
  status: 'done' | 'running' | 'cancelling' | 'cancelled' | 'interrupted' | 'error';
  error: string | null;
  current_step: CurrentStep | null;
  state: DebateState;
  phases_plan: string[];
  rebuttal_rounds: number;
  speech_length: SpeechLength;
  has_mp3: boolean;
  has_wav: boolean;
  audio_url: string | null;
  srt_cues: SrtCue[];
  segments: AudioSegment[];
}

