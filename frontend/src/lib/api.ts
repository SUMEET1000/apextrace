/** Typed fetchers for the FastAPI service.
 *
 * `API_BASE` is relative on purpose: Vite proxies `/api` to 127.0.0.1:8000 in
 * development and FastAPI serves the built bundle from the same origin in
 * production, so neither environment needs a host baked into the client.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type {
  CornerAnalysisResponse, ManifestResponse, RaceArcResponse,
  SessionResponse, UndercutResponse,
} from './types';

const API_BASE = '/api';

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = 'ApiError';
  }
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { signal });
  if (!response.ok) {
    // FastAPI puts the reason in `detail`; surfacing it is what lets a page
    // say "this session does not support the pooled model" instead of "500".
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch { /* a non-JSON error body is still an error */ }
    throw new ApiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

function query(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') {
      search.set(key, String(value));
    }
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : '';
}

export const fetchManifest = (s?: AbortSignal) =>
  get<ManifestResponse>('/manifest', s);

export const fetchOpener = (prefer: string[], s?: AbortSignal) =>
  get<{ slug: string | null }>(`/opener${query({ prefer: prefer.join(',') })}`, s);

export const fetchSession = (slug: string, s?: AbortSignal) =>
  get<SessionResponse>(`/session${query({ slug })}`, s);

export const fetchCornerAnalysis = (
  slug: string, driver1: string, driver2: string,
  lap1?: number | null, lap2?: number | null, s?: AbortSignal,
) => get<CornerAnalysisResponse>(
  `/corner-analysis${query({ slug, driver1, driver2, lap1, lap2 })}`, s);

export const fetchRaceArc = (
  slug: string, fuelEffect: number, fuelKg: number, s?: AbortSignal,
) => get<RaceArcResponse>(
  `/race-arc${query({ slug, fuel_effect: fuelEffect, fuel_kg: fuelKg })}`, s);

export const fetchUndercut = (
  gapS: number, advantage: number, degRate: number, s?: AbortSignal,
) => get<UndercutResponse>(
  `/undercut${query({ gap_s: gapS, advantage, deg_rate: degRate })}`, s);

export function fetchChartData<T>(
  id: string,
  params: Record<string, string | number | null | undefined>,
  signal?: AbortSignal,
): Promise<T> {
  return get<T>(`/chart-data/${id}${query(params)}`, signal);
}

// --------------------------------------------------------------------------
// The one data hook
// --------------------------------------------------------------------------

export interface Async<T> {
  data: T | undefined;
  error: string | null;
  /** True only on the very first load. A refetch keeps the previous data on
   *  screen and dims it instead, which is how Streamlit behaved and why no
   *  spinner appears between two views of the same page. */
  loading: boolean;
  /** True whenever a request is in flight, including over stale data. */
  fetching: boolean;
  /** Runs the request again, for an error state's Retry button. */
  retry: () => void;
}

export function useAsync<T>(
  load: ((signal: AbortSignal) => Promise<T>) | null,
  deps: unknown[],
): Async<T> {
  const [state, setState] = useState<Omit<Async<T>, 'retry'>>({
    data: undefined, error: null, loading: load !== null, fetching: load !== null,
  });
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  // Held across renders so a refetch can keep showing the previous answer.
  const previous = useRef<T | undefined>(undefined);

  useEffect(() => {
    if (!load) {
      setState({ data: undefined, error: null, loading: false, fetching: false });
      return;
    }
    const controller = new AbortController();
    setState({
      data: previous.current, error: null,
      loading: previous.current === undefined, fetching: true,
    });
    load(controller.signal).then(
      (data) => {
        if (controller.signal.aborted) return;
        previous.current = data;
        setState({ data, error: null, loading: false, fetching: false });
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        // A superseded request is not a failure; only a real one clears the
        // data, so a transient error never blanks a page that had an answer.
        previous.current = undefined;
        setState({
          data: undefined,
          error: error instanceof Error ? error.message : String(error),
          loading: false, fetching: false,
        });
      },
    );
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, attempt]);

  return { ...state, retry };
}
