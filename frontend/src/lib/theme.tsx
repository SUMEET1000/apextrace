/** Colours and labels for the pre-2B pages, until Steps 5 and 6 replace them.
 *
 * Compound colours and session labels come from `landing/facts.json`, which
 * scripts/landing_facts.py bakes from `/api/theme` and drift-checks, so no
 * screen waits on the API for them. `colours`, `series` and the Plotly config
 * are the old dark chart palette, used only inside `.pw-legacy`; they leave
 * with those pages in Step 7.
 */

import { createContext, useContext, type ReactNode } from 'react';
import type { Config } from 'plotly.js';
import facts from '../landing/facts.json';
import type { ThemeResponse } from './types';

const THEME: ThemeResponse = {
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
  compound_colours: facts.compound_colours,
  session_labels: facts.session_labels,
  race_sessions: ['R', 'Sprint'],
  plotly_config: {
    displaylogo: false,
    modeBarButtonsToRemove: ['autoScale2d', 'toggleSpikelines'],
    displayModeBar: 'hover',
  },
  fuel_effect_s_per_kg: 0.032,
};

const ThemeContext = createContext<ThemeResponse>(THEME);

export function ThemeProvider({ children }: { children: ReactNode }) {
  return <ThemeContext.Provider value={THEME}>{children}</ThemeContext.Provider>;
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
