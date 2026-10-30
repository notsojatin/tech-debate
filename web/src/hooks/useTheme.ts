import { useEffect, useState } from 'react';

export type ThemeChoice = 'system' | 'light' | 'dark';
const KEY = 'paper-theme';

function readChoice(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY);
    if (v === 'light' || v === 'dark') return v;
  } catch {
    // storage blocked: follow the system
  }
  return 'system';
}

/** Day paper / night paper. "system" follows prefers-color-scheme; the choice is remembered per browser. */
export function useTheme() {
  const [choice, setChoice] = useState<ThemeChoice>(readChoice);

  useEffect(() => {
    const root = document.documentElement;
    if (choice === 'system') delete root.dataset.theme;
    else root.dataset.theme = choice;
    try {
      if (choice === 'system') localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, choice);
    } catch {
      // ignore
    }
  }, [choice]);

  const cycle = () => setChoice((c) => (c === 'system' ? 'light' : c === 'light' ? 'dark' : 'system'));
  return { choice, cycle };
}
