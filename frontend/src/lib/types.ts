/** Shapes returned by the FastAPI service in `api/`.
 *
 * These mirror the endpoints in `api/main.py`. Anything typed `unknown` here
 * is a frame whose columns depend on the data (a rejection table, a stint
 * fit) and is rendered by DataTable from its own column spec rather than
 * being destructured field by field. */

export interface ManifestSession {
  year: number;
  round: number;
  session: string;
  slug: string;
  event_name: string;
  location: string;
  country: string;
  event_date: string | null;
  n_drivers: number;
  n_laps: number;
  total_laps: number;
  n_corners: number;
  n_telemetry_rows: number;
  grid_points: number;
  n_telemetry_laps: number | null;
  telemetry_coverage: number | null;
}

export interface FeaturedSession {
  slug: string;
  route: string;
  title: string;
  blurb: string;
  params: Record<string, string>;
}

export interface ManifestResponse {
  sessions: ManifestSession[];
  years: number[];
  featured: FeaturedSession[];
}

export interface ThemeResponse {
  colours: Record<string, string>;
  series: string[];
  compound_colours: Record<string, string>;
  session_labels: Record<string, string>;
  race_sessions: string[];
  plotly_config: Record<string, unknown>;
  fuel_effect_s_per_kg: number;
}

export interface Outline {
  x: number[];
  y: number[];
  corners?: { x: number[]; y: number[]; labels: string[] };
}

export interface Circuit extends Outline {
  name: string;
}

/** One selectable lap, with everything the selector labels it with.
 *
 * `kind` and the coverage span are what let a partial lap announce itself at
 * the point of choosing it rather than after the charts have been read. */
export interface DriverLap {
  lap: number;
  time_s: number | null;
  compound: string | null;
  kind: string;
  cov_start: number;
  cov_end: number;
}

export interface CoverageSummary {
  n_laps: number;
  n_stored: number;
  n_missing: number;
  coverage: number;
  stores_all_laps: boolean;
}

export interface RejectionRow {
  reason: string;
  count: number;
  pct_of_input: number;
}

export interface SessionResponse {
  slug: string;
  meta: ManifestSession;
  session_label: string;
  is_race: boolean;
  has_telemetry: boolean;
  drivers: string[];
  driver_laps: Record<string, DriverLap[]>;
  trackmap: Outline;
  results: Record<string, unknown>[];
  availability: { summary: CoverageSummary; reasons: RejectionRow[] };
}

export interface HomeResponse {
  slug: string;
  meta: ManifestSession;
  session_label: string;
  fastest: { driver: string; lap_time: string } | null;
  track_temp: { mean: number; swing: number } | null;
  classification: Record<string, unknown>[];
  classification_columns: string[];
  fastest_per_driver: Record<string, string>[];
  circuit_lead: string | null;
}

export interface SegmentRow {
  label: string;
  kind: 'corner' | 'straight';
  delta_s: number | null;
  cum_delta_s: number | null;
  comparable: boolean;
  v_min_a: number | null;
  v_min_b: number | null;
  v_min_diff: number | null;
  brake_m_a: number | null;
  brake_m_b: number | null;
  brake_m_diff: number | null;
}

export interface ComparisonSummary {
  total_delta_s: number;
  corner_delta_s: number;
  straight_delta_s: number;
  coverage: number;
  n_segments: number;
  n_comparable: number;
  uncomparable_labels: string[];
  biggest_gains: { label: string; delta_s: number }[];
  biggest_losses: { label: string; delta_s: number }[];
}

export interface HeadToHeadRow {
  LapNumber: number;
  LapTime_s_a: number | null;
  LapTime_s_b: number | null;
  Compound_a: string | null;
  Compound_b: string | null;
  delta_s: number | null;
  cumulative_s: number | null;
  [key: string]: unknown;
}

export interface CornerAnalysisResponse {
  driver_a: string;
  driver_b: string;
  lap_a: number;
  lap_b: number;
  display_a: string;
  display_b: string;
  time_a: number | null;
  time_b: number | null;
  has_gap: boolean;
  gap: number | null;
  summary: ComparisonSummary;
  segments: SegmentRow[];
  ghost: { t_a: (number | null)[]; t_b: (number | null)[] };
  sector_fractions: number[];
  head_to_head: HeadToHeadRow[];
}

export interface CompoundSummaryRow {
  Compound: string;
  deg_s_per_lap: number;
  ci_low: number;
  ci_high: number;
  n_stints: number;
  n_laps: number;
  [key: string]: unknown;
}

export interface RaceArcResponse {
  slug: string;
  year: number;
  total_laps: number;
  is_race: boolean;
  fuel_effect: number;
  fuel_kg: number;
  degradation: {
    summary: CompoundSummaryRow[];
    stints: Record<string, unknown>[];
    rejections: RejectionRow[];
    n_prepared: number;
    n_all_laps: number;
    n_cliffs: number;
  };
  evolution: {
    available: boolean;
    result: {
      degradation: Record<string, unknown>[];
      n_laps: number;
      n_drivers: number;
      r_squared: number;
      total_gain_s: number;
    } | null;
    naive_gain: number | null;
    has_progression: boolean;
    session_best_gain?: number | null;
  };
  strategy: {
    stints?: Record<string, unknown>[];
    n_stints?: number;
    pace?: Record<string, unknown>[];
    pace_display?: Record<string, string | number>[];
    pit_loss?: Record<string, number>;
    gap_drivers?: string[];
    default_deg_rate?: number;
    default_advantage?: number;
  };
}

export interface UndercutResponse {
  table: Record<string, unknown>[];
  breakeven_lap: number | null;
  max_gain: number;
}
