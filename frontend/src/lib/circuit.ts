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

export function pointOnTrack(track: Projected, fraction: number): [number, number] {
  const index = Math.max(0, Math.min(1, fraction)) * (track.x.length - 1);
  const low = Math.floor(index);
  const high = Math.min(track.x.length - 1, low + 1);
  const mix = index - low;
  return [track.x[low] + (track.x[high] - track.x[low]) * mix,
    track.y[low] + (track.y[high] - track.y[low]) * mix];
}

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

/** Place a small turn number beside its measured point, along the local track normal. */
export function placeTurnNumbers(track: Projected, corners: CornerMark[], width: number,
                                 height: number): CornerMark[] {
  const result = corners.map((corner) => ({ ...corner }));
  const indices = corners.map((_, index) => index).sort((a, b) => {
    const nearby = (i: number) => Math.min(...corners.map((other, j) =>
      i === j ? Infinity : Math.hypot(other.x - corners[i].x, other.y - corners[i].y)));
    return nearby(a) - nearby(b);
  });
  const placed: number[] = [];
  for (const index of indices) {
    const corner = corners[index];
    let nearest = 0;
    let distance = Infinity;
    for (let i = 0; i < track.x.length; i++) {
      const d = Math.hypot(track.x[i] - corner.x, track.y[i] - corner.y);
      if (d < distance) { distance = d; nearest = i; }
    }
    const before = Math.max(0, nearest - 2); const after = Math.min(track.x.length - 1, nearest + 2);
    const dx = track.x[after] - track.x[before]; const dy = track.y[after] - track.y[before];
    const length = Math.hypot(dx, dy) || 1;
    const nx = -dy / length; const ny = dx / length;
    let best = { ...corner }; let bestScore = Infinity;
    for (const radius of [16, 21, 27, 34]) for (const side of [-1, 1]) for (const shift of [0, -6, 6]) {
      const x = corner.x + nx * radius * side + dx / length * shift;
      const y = corner.y + ny * radius * side + dy / length * shift;
      const halfWidth = Math.max(7, corner.label.length * 3.5);
      if (x < halfWidth + 4 || x > width - halfWidth - 4 || y < 10 || y > height - 10) continue;
      let score = radius + Math.abs(shift) * .3;
      for (let i = 0; i < track.x.length; i++) {
        const outsideX = Math.max(0, Math.abs(track.x[i] - x) - halfWidth);
        const outsideY = Math.max(0, Math.abs(track.y[i] - y) - 6);
        const clearance = Math.hypot(outsideX, outsideY);
        if (clearance < 5) score += (5 - clearance) * 300;
      }
      for (const otherIndex of placed) {
        const other = result[otherIndex];
        const otherHalf = Math.max(7, other.label.length * 3.5);
        if (Math.abs(other.x - x) < halfWidth + otherHalf + 5 && Math.abs(other.y - y) < 17) score += 10000;
      }
      for (let j = 0; j < corners.length; j++) {
        if (j !== index && Math.hypot(corners[j].x - x, corners[j].y - y) < 12) score += 1000;
      }
      if (score < bestScore) { bestScore = score; best = { ...corner, x, y }; }
    }
    result[index] = best;
    placed.push(index);
  }
  return result;
}

const PAD = 10;

function ptp(values: number[]): number {
  return Math.max(...values) - Math.min(...values);
}

function fit(track: Outline, width: number, height: number, padding = PAD) {
  const spanX = ptp(track.x) || 1;
  const spanY = ptp(track.y) || 1;
  const scale = Math.min((width - 2 * padding) / spanX, (height - 2 * padding) / spanY);
  const minX = Math.min(...track.x);
  const minY = Math.min(...track.y);
  const offsetX = (width - (spanX * scale + 2 * padding)) / 2;
  const offsetY = (height - (spanY * scale + 2 * padding)) / 2;
  return (x: number, y: number): [number, number] => [
    (x - minX) * scale + padding + offsetX,
    (height - padding - offsetY) - (y - minY) * scale,
  ];
}

export function projectCornerMarks(track: Outline, width: number, height: number,
                                   corners: { x: number[]; y: number[]; labels: string[] }, padding = PAD): CornerMark[] {
  if (track.x.length < 3 || track.x.length !== track.y.length) return [];
  const at = fit(track, width, height, padding);
  return corners.x.map((x, i) => {
    const [px, py] = at(x, corners.y[i]);
    return { x: px, y: py, label: corners.labels[i] };
  });
}

/** Decimated screen-space points for a trackmap, or null if unusable. */
export function project(
  track: Outline | undefined, width: number, height: number, padding = PAD,
): Projected | null {
  if (!track || track.x.length < 3 || track.x.length !== track.y.length) {
    return null;
  }
  const { x, y } = track;

  // Fit into the viewbox, preserving aspect and flipping Y for screen space.
  const at = fit(track, width, height, padding);

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
