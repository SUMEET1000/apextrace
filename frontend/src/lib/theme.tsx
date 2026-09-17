/** The design tokens, fetched from the API rather than duplicated here.
 *
 * `pitwall/viz/theme.py` and `pitwall/config.py` are the single definition of
 * every colour in this app. `styles/tokens.css` mirrors the subset CSS needs;
 * everything JavaScript needs — compound colours, the timing palette, the
 * Plotly modebar config, the session labels — comes over the wire from
 * `/api/theme` so it can never drift from the charts.
 */

import {
  createContext, useContext, useEffect, useState, type ReactNode,
} from 'react';
import type { Config } from 'plotly.js';
import { fetchTheme } from './api';
import type { ThemeResponse } from './types';

/** Used until `/api/theme` answers, and if it never does.
 *
 * Not a second source of truth: these are the same values, present only so
 * the first paint is not unstyled and a theme request failure degrades to the
 * right colours rather than to none. */
const FALLBACK: ThemeResponse = {
  colours: {
    surface: '#080808', panel: '#202329', panel_hi: '#2A2E36',
    ink_primary: '#FFFFFF', ink_secondary: '#AFAFAF', ink_muted: '#7C818A',
    gridline: '#5A5F6A', baseline: '#6A707C',
    accent: '#E63946', accent_text: '#FF4D5E', accent_dim: '#5A0A10',
    accent_hover: '#C90500',
    ref: '#3987e5', cmp: '#d95926',
    timing_session_best: '#C06BF0', timing_personal_best: '#3FBF5F',
    timing_slower: '#FFF200',
  },
  series: ['#3987e5', '#d95926', '#199e70', '#c98500',
           '#d55181', '#008300', '#9085e9', '#e66767'],
  compound_colours: {
    SOFT: '#E8484D', MEDIUM: '#F0C64B', HARD: '#EDEDED',
    INTERMEDIATE: '#43B02A', WET: '#3A82D8', UNKNOWN: '#7A7F87',
  },
  session_labels: {
    FP1: 'Practice 1', FP2: 'Practice 2', FP3: 'Practice 3',
    SQ: 'Sprint Qualifying', Sprint: 'Sprint', Q: 'Qualifying', R: 'Race',
  },
  race_sessions: ['R', 'Sprint'],
  plotly_config: {
    displaylogo: false,
    modeBarButtonsToRemove: ['autoScale2d', 'toggleSpikelines'],
    displayModeBar: 'hover',
  },
  fuel_effect_s_per_kg: 0.032,
};

const ThemeContext = createContext<ThemeResponse>(FALLBACK);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<ThemeResponse>(FALLBACK);

  useEffect(() => {
    const controller = new AbortController();
    fetchTheme(controller.signal)
      .then(setTheme)
      .catch(() => { /* the fallback above is already the right answer */ });
    return () => controller.abort();
  }, []);

  return <ThemeContext.Provider value={theme}>{children}</ThemeContext.Provider>;
}

export const useTheme = (): ThemeResponse => useContext(ThemeContext);

export function usePlotlyConfig(): Partial<Config> {
  return useTheme().plotly_config as Partial<Config>;
}

/** A session code as it is written for a reader — "Q" becomes "Qualifying". */
export function useSessionLabel(): (code: string) => string {
  const { session_labels: labels } = useTheme();
  return (code: string) => labels[code] ?? code;
}
