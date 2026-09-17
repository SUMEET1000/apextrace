/** Types for the exact plotly.js build `react-plotly.js` loads.
 *
 * `react-plotly.js` does `require("plotly.js/dist/plotly")` — the prebuilt UMD
 * bundle. The package's own `main` is `lib/index.js`, a different entry point
 * and therefore a different module in the graph, so importing `'plotly.js'`
 * for its runtime API would bundle a second complete copy of plotly alongside
 * the one the chart component is already using. Anything needing the Plotly
 * API directly has to import this specifier.
 *
 * That path ships no types, and `@types/plotly.js` describes the same surface,
 * so borrow it rather than hand-writing a second declaration that can drift.
 */
declare module 'plotly.js/dist/plotly' {
  import type * as Plotly from 'plotly.js';

  const plotly: typeof Plotly;
  export default plotly;
}
