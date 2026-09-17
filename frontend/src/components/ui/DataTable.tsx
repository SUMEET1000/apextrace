/** `st.dataframe`, including the two Styler modes the pages used.
 *
 * A fixed pixel height with internal scroll, because a long classification
 * must not push the rest of the page off the screen. On a phone those same
 * heights (360–560px) would be the whole viewport, so `global.css` clamps them
 * at the `--bp-sm` breakpoint; that is where the height override lives rather
 * than here.
 */

import { type CSSProperties, type ReactNode, useMemo } from 'react';
import { columnRange, gradientStyle } from '../../lib/colormap';

export interface Column<T> {
  /** Header text, and the key read from the row unless `render` is given. */
  key: string;
  label?: string;
  /** Right-aligned and tabular-numbered. */
  numeric?: boolean;
  render?: (row: T, index: number) => ReactNode;
  /** Per-cell inline style — the timing-ink columns use this. */
  style?: (row: T, index: number) => CSSProperties | undefined;
  /**
   * Paint this column with matplotlib's RdBu_r, normalised over the column's
   * own min and max. Replaces `Styler.background_gradient(cmap="RdBu_r")`.
   */
  gradient?: boolean;
}

interface DataTableProps<T> {
  rows: T[];
  columns: Column<T>[];
  /** Matches the `height=` argument the pages passed to `st.dataframe`. */
  height?: number;
  emptyMessage?: string;
}

function cellText(value: unknown): ReactNode {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') {
    return Number.isFinite(value) ? String(value) : '—';
  }
  return String(value);
}

/** Read a column's raw value off a row.
 *
 * The generic is unconstrained on purpose so callers can pass their real
 * response types (`SegmentRow`, `RejectionRow`) rather than widening
 * everything to `Record<string, unknown>` at every call site. A column's `key`
 * is what pairs it with its row, and `render` overrides this whenever the
 * pairing is not a plain field read. */
const valueOf = <T,>(row: T, key: string): unknown =>
  (row as Record<string, unknown>)[key];

export function DataTable<T>(
  { rows, columns, height, emptyMessage = 'No rows.' }: DataTableProps<T>,
) {
  // One pass per gradient column for its normalisation range, matching
  // pandas' default `Normalize(data.min(), data.max())`: the scale is
  // relative to the numbers on screen, so a table of small deltas still
  // uses the full ramp.
  const ranges = useMemo(() => {
    const found: Record<string, [number, number]> = {};
    for (const column of columns) {
      if (!column.gradient) continue;
      found[column.key] = columnRange(
        rows.map((row) => valueOf(row, column.key) as number | null));
    }
    return found;
  }, [rows, columns]);

  if (rows.length === 0) {
    return <div className="pw-chart-error">{emptyMessage}</div>;
  }

  return (
    <div className="pw-table-wrap" style={height ? { height } : undefined}>
      <table className="pw-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} data-numeric={column.numeric || undefined}
                  scope="col">
                {column.label ?? column.key}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {columns.map((column) => {
                let style = column.style?.(row, index);
                let gradient = false;
                if (column.gradient) {
                  const [min, max] = ranges[column.key] ?? [0, 1];
                  const painted = gradientStyle(
                    valueOf(row, column.key) as number | null, min, max);
                  if (painted) {
                    style = { ...style, ...painted };
                    gradient = true;
                  }
                }
                return (
                  <td
                    key={column.key}
                    data-numeric={column.numeric || undefined}
                    data-gradient={gradient || undefined}
                    style={style}
                  >
                    {column.render
                      ? column.render(row, index)
                      : cellText(valueOf(row, column.key))}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --------------------------------------------------------------------------
// Timing ink
// --------------------------------------------------------------------------

export type TimingState = 'SB' | 'PB' | '' | null;

/**
 * Live-timing state for one or more lap-time columns, read in lap order.
 *
 * Purple when a lap is the quickest either driver has set so far, green when
 * it is that driver's own best so far, yellow otherwise. Ported from
 * `_timing_states` in `app/pages/1_Corner_Analysis.py`.
 *
 * `null` is a lap the driver did not complete. That is not a timing state and
 * must not be painted as the slowest one.
 */
export function timingStates(
  rows: (number | null | undefined)[][],
): TimingState[][] {
  const columns = rows[0]?.length ?? 0;
  let sessionBest = Infinity;
  const personal = new Array<number>(columns).fill(Infinity);

  return rows.map((row) => row.map((value, column) => {
    if (value === null || value === undefined || !Number.isFinite(value)) {
      return null;
    }
    if (value < sessionBest) {
      sessionBest = value;
      personal[column] = value;
      return 'SB';
    }
    if (value < personal[column]) {
      personal[column] = value;
      return 'PB';
    }
    return '';
  }));
}

/** The colour a timing state is drawn in.
 *
 * The state is also written into the cell as SB / PB, so the colour is a
 * recognition aid rather than the encoding — the same rule the compound
 * colours follow, and the reason a blank lap stays uncoloured. */
export function timingStyle(state: TimingState): CSSProperties | undefined {
  if (state === 'SB') {
    return { color: 'var(--timing-session-best)', fontWeight: 600 };
  }
  if (state === 'PB') return { color: 'var(--timing-personal-best)' };
  if (state === '') return { color: 'var(--timing-slower)' };
  return undefined;
}

/** A lap time with its timing state appended, or an em dash if not set. */
export function timingCell(
  value: number | null | undefined, state: TimingState,
): string {
  if (state === null || value === null || value === undefined) return '—';
  return `${value.toFixed(3)}${state ? ` ${state}` : ''}`;
}
