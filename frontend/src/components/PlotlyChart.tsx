/** A tuned `pitwall.viz` figure, fetched as Plotly JSON and rendered as-is.
 *
 * The API calls the very functions the Streamlit app called and returns
 * `fig.to_json()`, so the shared `pitwall` template, the hovertemplates, the
 * diverging colourscales and the stacked-panel layouts arrive intact. Nothing
 * here re-derives any of that; this component only fetches, sizes, and hands
 * the object to plotly.js.
 *
 * There is no spinner. A race session's traces resolve in ~100ms, under the
 * ~200ms at which a progress indicator starts helping, and shown anyway it
 * appeared and vanished inside two frames and read as a stutter rather than as
 * work being done. A refetch dims the previous figure instead — Streamlit's
 * own stale styling, and the reason the reader never sees a chart disappear
 * and come back while moving a slider.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import Plot from 'react-plotly.js';
import Plotly from 'plotly.js/dist/plotly';
import type { Data, Layout, PlotMouseEvent } from 'plotly.js';
import { ApiError, chartUrl } from '../lib/api';
import { usePlotlyConfig } from '../lib/theme';

interface Figure {
  data: Data[];
  layout: Partial<Layout>;
}

interface PlotlyChartProps {
  id: string;
  params: Record<string, string | number | null | undefined>;
  /** Reserved height while the first figure loads, so nothing jumps. */
  height?: number;
  onPointClick?: (event: Readonly<PlotMouseEvent>) => void;
  /** Shown instead of an error box when the API answers 404. */
  emptyMessage?: string;
}

export function PlotlyChart(
  { id, params, height = 420, onPointClick, emptyMessage }: PlotlyChartProps,
) {
  const url = chartUrl(id, params);
  const config = usePlotlyConfig();
  const [figure, setFigure] = useState<Figure | undefined>(undefined);
  const [error, setError] = useState<{ message: string; status: number } | null>(null);
  const [fetching, setFetching] = useState(true);
  // Held across renders so a refetch keeps the previous figure on screen.
  const previous = useRef<Figure | undefined>(undefined);
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    setFetching(true);
    setError(null);

    fetch(url, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          let detail = `${response.status} ${response.statusText}`;
          try {
            const body = await response.json();
            if (body?.detail) detail = String(body.detail);
          } catch { /* a non-JSON error body is still an error */ }
          throw new ApiError(detail, response.status);
        }
        return response.json() as Promise<Figure>;
      })
      .then((next) => {
        if (controller.signal.aborted) return;
        previous.current = next;
        setFigure(next);
        setFetching(false);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        previous.current = undefined;
        setFigure(undefined);
        setError({
          message: cause instanceof Error ? cause.message : String(cause),
          status: cause instanceof ApiError ? cause.status : 0,
        });
        setFetching(false);
      });

    return () => controller.abort();
  }, [url]);

  // `autosize` lets plotly.js track the container, which is what
  // `width="stretch"` did in Streamlit.
  //
  // The height every chart function sets deliberately via `theme.apply` is
  // kept — but as CSS on the container below, not as `layout.height`. It
  // cannot stay on the layout: `Plots.resize` does `delete gd.layout.height`
  // before re-measuring, and `gd.layout` is this very object (plotly assigns
  // it by reference), so the figure's stated height is erased within a frame
  // of mounting and whatever the div measured at that moment replaces it. In
  // CSS it is the thing plotly measures rather than the thing it overwrites.
  const layout = useMemo<Partial<Layout>>(() => {
    if (!figure) return {};
    const { height: _height, width: _width, ...rest } = figure.layout;
    return { ...rest, autosize: true };
  }, [figure]);

  // Falls back to the skeleton's reserved height, so a figure that somehow
  // arrives without one still gets a box rather than collapsing to nothing.
  const figureHeight = figure?.layout.height ?? height;

  // plotly.js ships no ResizeObserver anywhere: `responsive: true` adds a
  // window-resize listener, and react-plotly's `useResizeHandler` adds the
  // same listener again. So a container that changes width *without* the
  // window changing never reaches the figure — collapsing the sidebar is a
  // 300px swing, and a scrollbar arriving as later sections stream in is
  // another. Every chart would render at a stale width; the track maps, whose
  // aspect is fitted to the plot rectangle, render at a stale *scale*, with
  // the fixed-size corner labels and S/F marker no longer over the outline.
  useEffect(() => {
    const node = host.current;
    if (!node || typeof ResizeObserver === 'undefined') return;

    let frame = 0;
    const observer = new ResizeObserver(() => {
      // Coalesce to one redraw per frame: an observer fires per box change,
      // and a sidebar toggle changes several in a row.
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const gd = node.querySelector<HTMLElement>('.js-plotly-plot');
        // `Plots.resize` rejects outright on a hidden div, and there is
        // nothing to redraw for one anyway.
        if (gd && gd.offsetParent !== null) Plotly.Plots.resize(gd);
      });
    });
    observer.observe(node);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [figure]);

  if (error) {
    if (error.status === 404 && emptyMessage) {
      return <div className="pw-chart-error">{emptyMessage}</div>;
    }
    return (
      <div className="pw-chart-error" role="alert">
        Could not draw this chart — {error.message}
      </div>
    );
  }

  if (!figure) {
    return <div className="pw-chart-skeleton" style={{ height }} aria-busy="true" />;
  }

  return (
    <div
      ref={host}
      className="pw-chart pw-stale"
      data-stale={fetching || undefined}
      style={{ height: figureHeight }}
    >
      <Plot
        data={figure.data}
        layout={layout}
        config={config}
        onClick={onPointClick}
        // `position: relative` and `display: inline-block` are react-plotly's
        // own defaults and passing `style` at all replaces them wholesale, so
        // the one that matters has to be restored by hand. The size is here
        // rather than in the layout — see the note on `layout` above — and
        // fills the box the wrapper sets.
        style={{ position: 'relative', width: '100%', height: '100%' }}
      />
      {/* No `useResizeHandler`: it is a third window-resize listener behind
          the two `responsive: true` already installs, and it also fires
          `Plots.resize` on mount, which is what made the first draw's size
          non-deterministic. The observer above covers every case it did. */}
    </div>
  );
}
