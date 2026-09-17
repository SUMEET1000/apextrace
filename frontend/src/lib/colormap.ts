/** matplotlib's `RdBu_r`, and pandas' `Styler.background_gradient` rule.
 *
 * The Streamlit pages painted two columns — "Δ (s)" on the lap-by-lap table
 * and "Δ time (s)" on the corner table — with
 * `Styler.background_gradient(cmap="RdBu_r")`. That is a matplotlib colormap
 * applied through pandas' own normalisation and text-contrast rule, so
 * reproducing it by eye would drift.
 *
 * The 256-stop lookup below is matplotlib 3.11.1's `RdBu_r` dumped verbatim,
 * packed three bytes per stop. Embedding the table rather than re-deriving it
 * from ColorBrewer anchors is what makes this exact, and it is what let
 * matplotlib be dropped from the dependency list entirely — it was only ever
 * pulled in through this Styler call (see the note in `app/common.py`).
 */

// prettier-ignore
const RDBU_R_PACKED =
  '05306106326407346708366a09386d0a3b700c3d730d3f760e41790f437b10457e114781124984134c87144e8a15508d' +
  '1752901854931956961a58991b5a9c1c5c9f1d5fa21e61a51f63a82065ab2267ac2369ad246aae266caf276eb02870b1' +
  '2a71b22b73b32c75b42e77b52f79b5307ab6327cb7337eb83480b93681ba3783bb3885bc3a87bd3b88be3c8abe3e8cbf' +
  '3f8ec0408fc14291c24393c34695c44997c54c99c64f9bc7529dc8569fc959a1ca5ca3cb5fa5cd62a7ce65a9cf68abd0' +
  '6bacd16eaed271b0d375b2d478b4d57bb6d67eb8d781bad884bcd987beda8ac0db8dc2dc90c4dd93c6de96c7df98c8e0' +
  '9bc9e09dcbe1a0cce2a2cde3a5cee3a7d0e4a9d1e5acd2e5aed3e6b1d5e7b3d6e8b6d7e8b8d8e9bbdaeabddbeac0dceb' +
  'c2ddecc5dfecc7e0edcae1eecce2efcfe4efd1e5f0d2e6f0d4e6f1d5e7f1d7e8f1d8e9f1dae9f2dbeaf2ddebf2deebf2' +
  'e0ecf3e1edf3e3edf3e4eef4e6eff4e7f0f4e9f0f4eaf1f5ecf2f5edf2f5eff3f5f0f4f6f2f5f6f3f5f6f5f6f7f6f7f7' +
  'f7f6f6f7f5f4f8f4f2f8f3f0f8f2eff8f1edf9f0ebf9efe9f9eee7f9ede5f9ebe3faeae1fae9dffae8defae7dcfbe6da' +
  'fbe5d8fbe4d6fbe3d4fce2d2fce0d0fcdfcffcdecdfdddcbfddcc9fddbc7fdd9c4fcd7c2fcd5bffcd3bcfbd0b9fbceb7' +
  'fbccb4facab1fac8aff9c6acf9c4a9f9c2a7f8bfa4f8bda1f8bb9ef7b99cf7b799f7b596f6b394f6b191f6af8ef5ac8b' +
  'f5aa89f5a886f4a683f3a481f2a17ff19e7df09c7bef9979ee9677ec9374eb9172ea8e70e98b6ee8896ce6866ae58368' +
  'e48066e37e64e27b62e17860df765ede735cdd7059dc6e57db6b55da6853d86551d7634fd6604dd55d4cd35a4ad25849' +
  'd05548cf5246ce4f45cc4c44cb4942c94741c84440c6413ec53e3dc43b3cc2383ac13639bf3338be3036bd2d35bb2a34' +
  'ba2832b82531b72230b61f2eb41c2db3192cb1182bae172aab162aa81529a51429a213289f12289c1127991027960f27' +
  '930e26900d268d0c258a0b25870a248409248108237f08237c07227906227605217304217003206d02206a011f67001f';

/** The colour at position `t` in [0, 1] along RdBu_r, as `#rrggbb`. */
export function rdbuR(t: number): string {
  const clamped = Number.isFinite(t) ? Math.min(1, Math.max(0, t)) : 0.5;
  // matplotlib maps a normalised value onto N stops by truncation, not by
  // interpolating between them — `Colormap.__call__` does `int(x * N)`.
  const index = Math.min(255, Math.floor(clamped * 256));
  return `#${RDBU_R_PACKED.slice(index * 6, index * 6 + 6)}`;
}

/** WCAG relative luminance of an `#rrggbb` colour, as pandas computes it. */
function relativeLuminance(hex: string): number {
  const channel = (offset: number) => {
    const value = parseInt(hex.slice(offset, offset + 2), 16) / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
}

/** pandas' `text_color_threshold`: dark backgrounds get light text. */
const TEXT_COLOR_THRESHOLD = 0.408;

export interface GradientStyle {
  backgroundColor: string;
  color: string;
}

/**
 * A cell's background and text colour for a diverging gradient column.
 *
 * `vmin`/`vmax` come from the column itself, matching pandas' default
 * `Normalize(data.min(), data.max())` — the scale is relative to the numbers
 * on screen, not to a fixed range, so a table of small deltas still uses the
 * full ramp.
 */
export function gradientStyle(
  value: number | null | undefined, vmin: number, vmax: number,
): GradientStyle | undefined {
  if (value === null || value === undefined || !Number.isFinite(value)) return undefined;
  const span = vmax - vmin;
  const background = rdbuR(span === 0 ? 0.5 : (value - vmin) / span);
  return {
    backgroundColor: background,
    color: relativeLuminance(background) < TEXT_COLOR_THRESHOLD ? '#f1f1f1' : '#000000',
  };
}

/** Finite min/max of a column, for the gradient scale. */
export function columnRange(values: (number | null | undefined)[]): [number, number] {
  const finite = values.filter(
    (v): v is number => v !== null && v !== undefined && Number.isFinite(v));
  if (finite.length === 0) return [0, 1];
  return [Math.min(...finite), Math.max(...finite)];
}
