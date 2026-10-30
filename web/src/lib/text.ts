export function formatMs(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '0:00';
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export function splitIntoSentences(text: string): string[] {
  return text
    .split(/(?<=[.!?])\s+(?=["'(]?[A-Z0-9])/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export function normWords(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

export function wordsOf(s: string): string[] {
  return s.split(/\s+/).filter(Boolean);
}

/** Spoken minutes for a debate, at ~150 words per minute plus the narrator's lines. */
export function estimateMinutes(rounds: number, words: { opening: number; rebuttal: number; closing: number }): number {
  const total = 2 * (words.opening + rounds * words.rebuttal + words.closing) + 150;
  return Math.max(1, Math.round(total / 150));
}
