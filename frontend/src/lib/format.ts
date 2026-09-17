/** Number and time formatting, ported from `app/common.py` and the pages. */

/** 90.123 -> "1:30.123", the way lap times are actually read. */
export function fmtLaptime(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) {
    return '—';
  }
  const minutes = Math.floor(seconds / 60);
  const rest = seconds - minutes * 60;
  return `${minutes}:${rest.toFixed(3).padStart(6, '0')}`;
}

/** Fixed decimals, with an em dash for anything missing.
 *
 * The em dash rather than "0.000" or "NaN" is deliberate throughout this app:
 * a lap the source feed gave no time for is unknown, not zero. */
export function fmt(
  value: number | null | undefined, digits = 3, options: { sign?: boolean } = {},
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const text = Math.abs(value).toFixed(digits);
  if (!options.sign) return value < 0 ? `-${text}` : text;
  return `${value < 0 ? '-' : '+'}${text}`;
}

/** Signed to three decimals with a unit — "+0.384 s". */
export const fmtDelta = (value: number | null | undefined, unit = ' s'): string =>
  value === null || value === undefined || !Number.isFinite(value)
    ? '—'
    : `${fmt(value, 3, { sign: true })}${unit}`;

export function fmtInt(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return Math.round(value).toLocaleString('en-GB');
}

/** 0.9234 -> "92%" — Python's `{:.0%}`. */
export function fmtPercent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return `${(value * 100).toFixed(digits)}%`;
}

/** Title case for a single word, matching Python's `str.title()` usage. */
export const titleCase = (text: string): string =>
  text.charAt(0).toUpperCase() + text.slice(1).toLowerCase();

/** "a" or "an", for the partial-lap sentence that reads "is an in-lap". */
export const article = (word: string): string =>
  'aeiou'.includes(word.charAt(0).toLowerCase()) ? 'an' : 'a';

/** Join a list the way prose does: "T1, T4 and T9". */
export function joinProse(items: string[], conjunction = 'and'): string {
  if (items.length === 0) return '';
  if (items.length === 1) return items[0];
  return `${items.slice(0, -1).join(', ')} ${conjunction} ${items[items.length - 1]}`;
}
