/** Projecting a trackmap into a drawing box.
 *
 * Ported from `_projected` / `_circuit_points` in `app/brand.py`. One
 * projection is shared by every piece of circuit artwork, so the SVG polyline
 * and any CSS `path()` built from the same trackmap describe exactly the same
 * shape in exactly the same coordinates. The three call sites use three
 * different box sizes (page header 190x120, home reel 430x280, ghost replay
 * 520x340), which is why this lives on the client rather than being baked at
 * one size by the API.
 */

import type { Outline } from './types';

export interface Projected {
  x: number[];
  y: number[];
}

const PAD = 10;

function ptp(values: number[]): number {
  return Math.max(...values) - Math.min(...values);
}

/** Decimated screen-space points for a trackmap, or null if unusable. */
export function project(
  track: Outline | undefined, width: number, height: number,
): Projected | null {
  if (!track || track.x.length < 3 || track.x.length !== track.y.length) {
    return null;
  }
  const { x, y } = track;

  // Fit into the viewbox, preserving aspect and flipping Y for screen space.
  const spanX = ptp(x) || 1;
  const spanY = ptp(y) || 1;
  const scale = Math.min((width - 2 * PAD) / spanX, (height - 2 * PAD) / spanY);
  const minX = Math.min(...x);
  const minY = Math.min(...y);
  const offsetX = (width - (spanX * scale + 2 * PAD)) / 2;

  const px: number[] = [];
  const py: number[] = [];
  // Keep the path small. Same rule as the Python: one point in every
  // `len // 260`, so a 1000-point grid becomes ~334 points.
  const step = Math.max(1, Math.floor(x.length / 260));
  for (let i = 0; i < x.length; i += step) {
    px.push((x[i] - minX) * scale + PAD + offsetX);
    py.push((height - PAD) - (y[i] - minY) * scale);
  }
  return { x: px, y: py };
}

/** Projected `x,y ...` polyline points, or "" if the trackmap is unusable. */
export function polylinePoints(
  track: Outline | undefined, width: number, height: number,
): string {
  const projected = project(track, width, height);
  if (!projected) return '';
  return projected.x
    .map((x, i) => `${x.toFixed(1)},${projected.y[i].toFixed(1)}`)
    .join(' ');
}

/** The same outline as an SVG path string, closed — for CSS `offset-path`. */
export function closedPath(projected: Projected): string {
  const segments = projected.x
    .map((x, i) => `${x.toFixed(1)} ${projected.y[i].toFixed(1)}`)
    .join(' L ');
  return `M ${segments} Z`;
}

/** numpy's `interp`: piecewise-linear lookup with the ends held flat. */
export function interp(at: number, xs: number[], ys: number[]): number {
  const n = xs.length;
  if (n === 0) return NaN;
  if (at <= xs[0]) return ys[0];
  if (at >= xs[n - 1]) return ys[n - 1];

  let low = 0;
  let high = n - 1;
  while (high - low > 1) {
    const mid = (low + high) >> 1;
    if (xs[mid] <= at) low = mid; else high = mid;
  }
  const span = xs[high] - xs[low];
  if (span === 0) return ys[low];
  return ys[low] + ((at - xs[low]) / span) * (ys[high] - ys[low]);
}
