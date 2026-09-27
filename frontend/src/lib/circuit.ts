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

export interface CornerMark { x: number; y: number; label: string }

/** Keep numbered boxes clear of the racing line, with leaders to the measured turn. */
export function placeCornerMarks(track: Projected, corners: CornerMark[], width: number,
                                 height: number, size: number): CornerMark[] {
  const placed: CornerMark[] = [];
  const directions = [[0, -1], [1, 0], [0, 1], [-1, 0],
    [1, -1], [1, 1], [-1, 1], [-1, -1]];
  for (const corner of corners) {
    let best = { x: corner.x, y: corner.y, label: corner.label };
    let bestScore = Infinity;
    for (const radius of [size * 1.5, size * 2.2, size * 3]) {
      for (const [dx, dy] of directions) {
        const x = corner.x + dx * radius;
        const y = corner.y + dy * radius;
        if (x < size / 2 + 3 || x > width - size / 2 - 3
          || y < size / 2 + 3 || y > height - size / 2 - 3) continue;
        let score = radius;
        for (let i = 0; i < track.x.length; i++) {
          const outsideX = Math.max(0, Math.abs(track.x[i] - x) - size / 2);
          const outsideY = Math.max(0, Math.abs(track.y[i] - y) - size / 2);
          const clearance = Math.hypot(outsideX, outsideY);
          if (clearance < 7) score += (7 - clearance) * 150;
        }
        for (const other of placed) {
          const overlapX = size + 5 - Math.abs(other.x - x);
          const overlapY = size + 5 - Math.abs(other.y - y);
          if (overlapX > 0 && overlapY > 0) score += 3000 + overlapX * overlapY;
        }
        if (score < bestScore) { bestScore = score; best = { x, y, label: corner.label }; }
      }
    }
    placed.push(best);
  }
  return placed;
}

const PAD = 10;

function ptp(values: number[]): number {
  return Math.max(...values) - Math.min(...values);
}

function fit(track: Outline, width: number, height: number) {
  const spanX = ptp(track.x) || 1;
  const spanY = ptp(track.y) || 1;
  const scale = Math.min((width - 2 * PAD) / spanX, (height - 2 * PAD) / spanY);
  const minX = Math.min(...track.x);
  const minY = Math.min(...track.y);
  const offsetX = (width - (spanX * scale + 2 * PAD)) / 2;
  return (x: number, y: number): [number, number] => [
    (x - minX) * scale + PAD + offsetX,
    (height - PAD) - (y - minY) * scale,
  ];
}

export function projectCornerMarks(track: Outline, width: number, height: number,
                                   corners: { x: number[]; y: number[]; labels: string[] }): CornerMark[] {
  if (track.x.length < 3 || track.x.length !== track.y.length) return [];
  const at = fit(track, width, height);
  return corners.x.map((x, i) => {
    const [px, py] = at(x, corners.y[i]);
    return { x: px, y: py, label: corners.labels[i] };
  });
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
  const at = fit(track, width, height);

  const px: number[] = [];
  const py: number[] = [];
  // Keep the path small. Same rule as the Python: one point in every
  // `len // 260`, so a 1000-point grid becomes ~334 points.
  const step = Math.max(1, Math.floor(x.length / 260));
  for (let i = 0; i < x.length; i += step) {
    const [pointX, pointY] = at(x[i], y[i]);
    px.push(pointX);
    py.push(pointY);
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
