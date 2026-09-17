/** Generated circuit imagery.
 *
 * All of it comes from this project's own telemetry: the shapes are the laps
 * the drivers on screen actually drove, not stock graphics. No external image
 * requests, no licensing question, and artwork that is genuinely specific to
 * the session being described.
 *
 * Ported from `circuit_svg`, `circuit_reel_svg` and `ghost_replay_svg` in
 * `app/brand.py`.
 */

import {
  useCallback, useEffect, useId, useRef, useState, type CSSProperties,
} from 'react';
import { closedPath, interp, polylinePoints, project } from '../../lib/circuit';
import type { Circuit, Outline } from '../../lib/types';
import { useTheme } from '../../lib/theme';
import { Select } from '../ui/primitives';

// --------------------------------------------------------------------------
// A single outline
// --------------------------------------------------------------------------

export function CircuitSvg(
  { track, width = 300, height = 190, stroke, glow = true }: {
    track: Outline | undefined;
    width?: number; height?: number; stroke?: string; glow?: boolean;
  },
) {
  const theme = useTheme();
  const filterId = useId().replace(/:/g, '');
  const points = polylinePoints(track, width, height);
  if (!points) return null;

  const colour = stroke ?? theme.colours.accent;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}
         role="img" aria-label="Outline of the circuit">
      {glow && (
        <defs>
          <filter id={filterId} x="-25%" y="-25%" width="150%" height="150%">
            <feGaussianBlur stdDeviation="3.2" result="b" />
            <feMerge>
              <feMergeNode in="b" /><feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
      )}
      <polyline
        points={points} fill="none" stroke={colour} strokeWidth="2.6"
        strokeLinejoin="round" strokeLinecap="round"
        filter={glow ? `url(#${filterId})` : undefined}
      />
    </svg>
  );
}

// --------------------------------------------------------------------------
// The reel
// --------------------------------------------------------------------------

const SECONDS_PER_CIRCUIT = 4.2;

/**
 * A stack of circuit outlines, each drawing itself in then handing over.
 *
 * Same honesty rule as CircuitSvg — every outline is this project's own
 * telemetry, one per circuit in the built dataset — but the home page shows
 * the whole calendar rather than a single shape. Because the artwork no longer
 * names the session in the sidebar by itself, each frame carries the circuit's
 * name; a reel of anonymous red squiggles would be decoration pretending to be
 * data.
 *
 * `circuits[0]` is the one on screen at load, so the caller can lead with the
 * selected session.
 *
 * The animation is pure CSS: no script, nothing to re-arm on a re-render, and
 * no work at all when the reader has asked for reduced motion. Only the
 * keyframes are generated here rather than living in `global.css`, because
 * their percentages depend on how many circuits are in the reel.
 */
export function CircuitReel(
  { circuits, width = 430, height = 280 }:
  { circuits: Circuit[]; width?: number; height?: number },
) {
  const theme = useTheme();
  const glowId = useId().replace(/:/g, '');

  const frames = circuits
    .map((circuit) => ({
      name: circuit.name,
      points: polylinePoints(circuit, width, height),
      track: circuit,
    }))
    .filter((frame) => frame.points !== '');

  if (frames.length === 0) return null;
  // Nothing to hand over to; a one-frame reel is just the static art.
  if (frames.length === 1) {
    return <CircuitSvg track={frames[0].track} width={width} height={height} />;
  }

  // One frame owns 100/n of the cycle and everything it does happens strictly
  // inside that slot: it fades in, holds, and is back at zero by the instant
  // the next frame's delay expires. Frame i+1 is delayed by exactly one slot,
  // so the handoff is sequential — an outline is never drawing itself on top
  // of the one still leaving.
  const slot = 100 / frames.length;
  const lit = slot * 0.14;   // fully opaque by here
  const dim = slot * 0.86;   // starts leaving here, reaching zero at `slot`
  const draw = slot * 0.55;  // the line keeps tracing itself after it is lit

  const keyframes = `
@keyframes pw-reel-fade {
  0% { opacity: 0 } ${lit.toFixed(4)}% { opacity: 1 }
  ${dim.toFixed(4)}% { opacity: 1 } ${slot.toFixed(4)}% { opacity: 0 }
  100% { opacity: 0 }
}
@keyframes pw-reel-draw {
  0% { stroke-dashoffset: 1000 } ${draw.toFixed(4)}% { stroke-dashoffset: 0 }
  100% { stroke-dashoffset: 0 }
}`;

  // Width plus a ratio rather than a pixel height: the frames are absolutely
  // positioned inside this box, so it needs an intrinsic size — but a fixed
  // height would stop the reel scaling down when the hero column is narrow.
  // The 26px is the name label under the outline.
  const style = {
    '--pw-step': `${SECONDS_PER_CIRCUIT}s`,
    '--pw-count': frames.length,
    width, aspectRatio: `${width} / ${height + 26}`,
  } as CSSProperties;

  return (
    <div className="pw-reel" style={style}>
      <style>{keyframes}</style>
      <svg className="pw-reel-defs" width="0" height="0" aria-hidden="true">
        <defs>
          <filter id={glowId} x="-25%" y="-25%" width="150%" height="150%">
            <feGaussianBlur stdDeviation="3.2" result="b" />
            <feMerge>
              <feMergeNode in="b" /><feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
      </svg>
      {frames.map((frame, i) => (
        <div
          key={`${frame.name}-${i}`}
          className={`pw-reel-frame${i === 0 ? ' pw-reel-frame--lead' : ''}`}
          style={{ '--pw-i': i } as CSSProperties}
        >
          <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}
               role="img" aria-label={`Outline of the ${frame.name} circuit`}>
            {/* `pathLength` renormalises every outline to 1000 units
                regardless of how long the circuit actually is, so one dash
                animation draws Monaco and Spa at the same visual rate instead
                of Spa taking twice as long. */}
            <polyline
              points={frame.points} fill="none" stroke={theme.colours.accent}
              strokeWidth="2.6" strokeLinejoin="round" strokeLinecap="round"
              pathLength={1000} strokeDasharray={1000} strokeDashoffset={1000}
              filter={`url(#${glowId})`}
            />
          </svg>
          <div className="pw-reel-name">{frame.name}</div>
        </div>
      ))}
    </div>
  );
}

// --------------------------------------------------------------------------
// The ghost replay
// --------------------------------------------------------------------------

/** Playback speeds, as multiples of the pace the lap was actually driven at.
 *
 *  Stated against real time rather than as a bare "slow / normal / fast",
 *  because the multiplier is a fact about the replay the reader can check: at
 *  1x a dot takes exactly as long to reach a corner as the car did. The
 *  default is 10x, which puts a typical 90s lap at ~9s — the duration this
 *  component was fixed at before the control existed.
 *
 *  Anything faster than 20x stops being a replay a viewer can follow, and
 *  anything slower than real time would be claiming a pace nobody drove. */
const GHOST_SPEEDS = [1, 2, 5, 10, 20];
const DEFAULT_GHOST_SPEED = 10;

/** Keyframes are emitted roughly every 150ms of playback: finer than a viewer
 *  can follow, coarse enough that the inline stylesheet stays a couple of
 *  kilobytes. The count therefore rises as the replay slows down — at 1x a
 *  fixed 60 steps would hold each car on a 1.5s straight line and flatten the
 *  braking zones the slow playback exists to show. The floor keeps the fast
 *  speeds exactly where they were; the ceiling caps the emitted CSS. */
const GHOST_STEP_SECONDS = 0.15;
const GHOST_STEPS_MIN = 60;
const GHOST_STEPS_MAX = 240;

/** Candidate full-scale values for the gap bar, in seconds.
 *
 *  The bar carries the magnitude *relative to the rest of the lap*, so its full
 *  scale has to be a round number rather than the lap's own ragged maximum —
 *  otherwise "half the bar" means something different on every pair of laps.
 *  The lap's largest gap is rounded *up* to one of these, which keeps the bar
 *  honest (it never clips) while the end labels stay readable.
 *
 *  The exact interval is no longer read off this scale: it is printed on the
 *  bar, live, by `GapMeter`. */
const GAP_SCALES = [0.05, 0.1, 0.25, 0.5, 1, 2, 5];

/** Below this the two laps are the same lap, or close enough that a bar would
 *  be a permanently empty axis pretending to be a measurement. */
const GAP_FLOOR = 0.01;

/** Fullscreen chrome to leave around the map: the controls row above it and the
 *  gap bar plus legend below. Only the *first* fullscreen frame is sized from
 *  these — `useStageSize` measures the real gap immediately afterwards — but a
 *  first frame drawn at the full viewport height would flash a map taller than
 *  the space it lands in. */
const FULL_CHROME_Y = 230;
const FULL_CHROME_X = 64;

/** Does the reader want motion? Live, because the OS setting can change while
 *  the page is open and a replay that keeps running after it was turned off is
 *  exactly the thing the setting exists to stop. */
function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    const sync = () => setReduced(query.matches);
    sync();
    query.addEventListener('change', sync);
    return () => query.removeEventListener('change', sync);
  }, []);
  return reduced;
}

/** The viewport, for sizing the fullscreen map. Only measured while it is
 *  needed — a resize listener that runs for a component nobody has opened is
 *  a re-render on every drag of the window edge for nothing. */
function useViewport(active: boolean): { w: number; h: number } {
  const [size, setSize] = useState({ w: 1280, h: 800 });
  useEffect(() => {
    if (!active) return;
    const measure = () => setSize({ w: window.innerWidth, h: window.innerHeight });
    measure();
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
  }, [active]);
  return size;
}

/** The space actually left for the map once the controls, the gap bar and the
 *  legend have taken theirs.
 *
 *  Measured, not viewport-minus-a-constant: every one of those three wraps to a
 *  second line at some width, so a fixed allowance is wrong on some screen —
 *  too small and the fullscreen view scrolls, which is the one thing it exists
 *  to avoid; too large and the map is drawn short of the room it has. The stage
 *  is `flex: 1 1 0` with `overflow: hidden`, so sizing the map from it cannot
 *  feed back into its own measurement. */
function useStageSize(el: HTMLElement | null): { w: number; h: number } | null {
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  useEffect(() => {
    if (!el || typeof ResizeObserver !== 'function') return;
    const measure = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [el]);
  return size;
}

/**
 * Keyframes for a value that only changes a handful of times per lap.
 *
 * The dots need a stop at all GHOST_STEPS because they move continuously. The
 * booleans — who is ahead, who is gaining — do not: emitting 61 stops for a
 * value that flips three times is most of the inline stylesheet spent saying
 * nothing changed. Emit a stop only where the value flips, with a duplicate a
 * hair earlier holding the old value so the switch is hard rather than a fade.
 */
function switchKeyframes(values: number[], property: string): string {
  const stop = (at: number, value: number) =>
    `${at.toFixed(3)}%{${property}:${value}}`;

  const parts = [stop(0, values[0])];
  for (let i = 1; i < values.length; i += 1) {
    if (values[i] === values[i - 1]) continue;
    const at = (i / (values.length - 1)) * 100;
    parts.push(stop(at - 0.001, values[i - 1]), stop(at, values[i]));
  }
  parts.push(stop(100, values[values.length - 1]));
  return parts.join(' ');
}

/**
 * The interval between the two cars, live, as a number over a bar.
 *
 * This is the one piece of the replay that cannot be a CSS animation: the
 * headline value is *text*, and no keyframe can animate text content. So it
 * runs a rAF loop — the only per-frame work in this component — and writes
 * straight to the DOM rather than through React state, because a `setState` at
 * 60 Hz would re-render the whole page for a three-character change.
 *
 * The interval is the same quantity the delta trace on this page plots and the
 * same one the timing screen means by "+0.184": how much longer the trailing
 * car took to reach the point it is standing on. It is read at the *trailing*
 * car's position, not the leader's — read at the leader's it would be the gap
 * at a point the car behind has not arrived at yet, which is a number about the
 * future.
 *
 * The clock is JS rather than the animation's own `currentTime` because it has
 * to survive the map being resized (fullscreen) without jumping, and because
 * the elapsed time lives in a ref: an effect restarting for an unrelated
 * re-render resumes the lap instead of throwing it back to the line.
 */
function GapMeter(
  { timeA, timeB, delta, grid, total, speed, scale, nameA, nameB,
    colourA, colourB, paused, phase0 }: {
    timeA: number[]; timeB: number[]; delta: number[]; grid: number[];
    total: number; speed: number; scale: number;
    nameA: string; nameB: string; colourA: string; colourB: string;
    paused: boolean;
    /** How far round the lap the replay already was when this meter was
     *  mounted, as a fraction — non-zero when a speed change re-anchored the
     *  replay mid-lap. The meter's own clock starts from here rather than from
     *  the line, so it keeps captioning the instant the dots are showing. */
    phase0: number;
  },
) {
  const reduced = usePrefersReducedMotion();
  const fillA = useRef<HTMLSpanElement>(null);
  const fillB = useRef<HTMLSpanElement>(null);
  const valueRef = useRef<HTMLSpanElement>(null);
  // The clock is an anchor plus wall time, not an accumulator over rAF deltas.
  // A backgrounded tab stops firing rAF but does not stop a CSS animation, so
  // an accumulator would come back from a tab switch reading a different moment
  // of the lap than the dots are showing. Subtracting the time spent paused
  // keeps it matching what the hover rule does to the animations.
  const startRef = useRef(0);
  const pausedAtRef = useRef<number | null>(null);
  const pausedTotalRef = useRef(0);

  useEffect(() => {
    if (paused) {
      pausedAtRef.current = performance.now();
    } else if (pausedAtRef.current !== null) {
      pausedTotalRef.current += performance.now() - pausedAtRef.current;
      pausedAtRef.current = null;
    }
  }, [paused]);

  /** Paint one instant of the lap. Pure DOM writes, no React. */
  const paint = useCallback((elapsed: number) => {
    const n = delta.length;
    // Where each car is on the circuit at this instant, from its own trace.
    const positionA = interp(elapsed, timeA, grid);
    const positionB = interp(elapsed, timeB, grid);
    const behindAt = Math.min(positionA, positionB);
    const gap = delta[Math.min(n - 1, Math.round((behindAt / 100) * (n - 1)))];

    // Sign convention throughout this component: delta is B minus A, so a
    // positive gap is the reference driver ahead.
    const level = Math.abs(gap) < GAP_FLOOR;
    const magnitude = Math.min(1, Math.abs(gap) / (scale || 1));
    if (fillA.current) {
      fillA.current.style.transform = `scaleX(${gap > 0 ? magnitude : 0})`;
    }
    if (fillB.current) {
      fillB.current.style.transform = `scaleX(${gap < 0 ? magnitude : 0})`;
    }
    if (valueRef.current) {
      // The driver is named, not just coloured: which end the bar reaches is
      // the visual answer, but colour alone must never be the only carrier.
      valueRef.current.textContent = level
        ? 'level'
        : `${gap > 0 ? nameA : nameB} +${Math.abs(gap).toFixed(3)} s`;
      valueRef.current.style.color = level ? '' : (gap > 0 ? colourA : colourB);
    }
  }, [colourA, colourB, delta, grid, nameA, nameB, scale, timeA, timeB]);

  useEffect(() => {
    // Nothing is playing under reduced motion, so there is no live interval to
    // show — the finishing margin is the honest still frame, matching the dots
    // parked at the line.
    if (reduced) {
      paint(total);
      return;
    }
    if (startRef.current === 0) startRef.current = performance.now();
    let frame = 0;
    const tick = () => {
      // While paused, the clock is read at the instant it stopped rather than
      // frozen by skipping the update — so a resize or a re-render repaints the
      // same moment instead of the wall time that has passed since.
      const now = pausedAtRef.current ?? performance.now();
      const played = phase0 * total
        + (now - startRef.current - pausedTotalRef.current) / 1000 * speed;
      paint(total > 0 ? ((played % total) + total) % total : 0);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [paint, phase0, reduced, speed, total]);

  const fills = [
    { key: 'a' as const, ref: fillA, colour: colourA },
    { key: 'b' as const, ref: fillB, colour: colourB },
  ];

  return (
    // Hidden from assistive tech: it restates the delta trace on this page for
    // readers who cannot resolve four pixels between the dots, and a number
    // rewritten sixty times a second is not something to announce. The result
    // is available as a sentence in the legend instead.
    <div className="pw-ghost-gap" aria-hidden="true">
      <div className="pw-ghost-gap-row">
        <span className="pw-ghost-gap-name">{nameA}</span>
        {/* The scale labels are the track's sibling inside this box, not the
            row's: the driver names either side are of unknown width, so
            anything aligned to the row lands a few pixels off the axis it is
            labelling. */}
        <div className="pw-ghost-gap-meter">
          <div className="pw-ghost-gap-track">
            <i className="pw-ghost-gap-mid" />
            {fills.map(({ key, ref, colour }) => (
              <span
                key={key} ref={ref}
                className={`pw-ghost-gap-fill pw-ghost-gap-fill--${key}`}
                style={{ '--pw-ghost-colour': colour } as CSSProperties}
              />
            ))}
            <span className="pw-ghost-gap-value" ref={valueRef} />
          </div>
          {/* The bar's own full scale, so a reader can tell a gap that is
              small from a bar that is simply zoomed in. Unsigned: which side
              the bar is on already says who, and a minus sign here invites
              reading it as a driver. */}
          <div className="pw-ghost-gap-scale">
            <span>{scale} s</span>
            <span>0</span>
            <span>{scale} s</span>
          </div>
        </div>
        <span className="pw-ghost-gap-name">{nameB}</span>
      </div>
    </div>
  );
}

/**
 * Two cars replaying their laps against each other around the circuit.
 *
 * The same trick the reel uses, pointed at a different property: pure CSS
 * animation over compositor-only values, no script, and nothing running at all
 * when the reader has asked for reduced motion. Here the property is
 * `offset-distance` along a `path()` built from the very outline drawn
 * underneath, so a dot is always exactly on the circuit rather than near it.
 *
 * The timing is not decoration. Each keyframe places a car at the distance its
 * *own* telemetry says it had reached at that moment of the lap, so the gap
 * that opens between the dots is the real gap, and the car that arrives at the
 * line first is the car that was quicker. That is only cheap because every lap
 * is stored on the same distance grid: distance along the path and row
 * position in the trace are the same number.
 *
 * What the map cannot do is answer "who is ahead". Both cars leave the line at
 * the same instant and the separation only ever grows to the final lap-time
 * delta — a few tenths, under half a percent of a lap, four to six pixels
 * here. The dots are genuinely on top of each other for the whole replay, and
 * that is the truth: it must not be faked by nudging them apart. So the answer
 * is carried on channels that are not sub-pixel, and the positions are left
 * alone:
 *
 *   - the leading car is drawn at full strength and the trailing one dimmed,
 *     so the pair reads as a leader even while overlapped;
 *   - a gap bar under the map grows toward whoever is ahead and prints the
 *     live interval, in seconds, over itself;
 *   - a glow lights on whichever car is currently taking time out of the other.
 *
 * And when four pixels is genuinely not enough, the whole replay goes
 * fullscreen: same laps, same timing, but the map is drawn at the height of the
 * viewport instead of 340px, so a gap that was sub-pixel becomes a separation
 * you can see. Nothing about the data changes — only how many pixels a metre of
 * track is worth.
 *
 * The last one is the *slope* of the delta and the first two are its *sign* —
 * different questions, which is why gaining and ahead are separate cues and a
 * car can perfectly well be gaining while behind.
 *
 * All three are opacity or transform cross-fades, so they cost nothing per
 * frame, and the dots keep their own driver colours, which the trace panel on
 * the same page already uses.
 */
export function GhostReplay(
  { track, tA, tB, nameA, nameB, width = 520, height = 340 }: {
    track: Outline | undefined;
    tA: (number | null)[];
    tB: (number | null)[];
    nameA: string; nameB: string;
    width?: number; height?: number;
  },
) {
  const theme = useTheme();
  const suffix = useId().replace(/:/g, '');
  // Speed travels with the lap phase it was chosen at, as one value, because
  // the two are only ever meaningful together: the animations have to restart
  // to be re-timed (see the map's key below), and the phase is what puts them
  // back where the reader was watching instead of at the line. `epoch` is what
  // the subtree is keyed on rather than the speed itself — picking the speed
  // that is already selected is then a no-op rather than a silent restart.
  const [play, setPlay] = useState(
    { speed: DEFAULT_GHOST_SPEED, phase: 0, epoch: 0 });
  const speed = play.speed;
  const [full, setFull] = useState(false);
  // Hover pauses the dots via CSS; the gap readout is JS, so it needs the same
  // fact as a value. Both are scoped to the drawing itself — reaching for the
  // speed control or the legend must not freeze the lap.
  const [hovering, setHovering] = useState(false);
  // Fullscreen pauses from a button instead. At 520px the pointer is only ever
  // over the map deliberately, but fullscreen *is* the whole screen: the
  // pointer rests on the drawing by default, so hover-to-pause there stops the
  // replay for anyone who does not know to move the mouse off it — and there is
  // nowhere much to move it to. An explicit control is also the only version of
  // this a keyboard or touch reader can reach at all.
  const [paused, setPaused] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const viewport = useViewport(full);
  // A callback ref, not `useRef`: the stage is keyed on the replay epoch, so
  // changing speed unmounts it and a stored `.current` would be measuring a
  // detached element from then on.
  const [stageEl, setStageEl] = useState<HTMLDivElement | null>(null);
  const stage = useStageSize(full ? stageEl : null);

  // Where the lap has got to, as a fraction of one lap. Anchored rather than
  // accumulated: `phase` is the reading taken the last time the clock was
  // disturbed (a speed change, a pause) and `since` is the wall time that
  // reading was taken at, so nothing here drifts against the CSS animations,
  // which keep their own clock and do not stop when a backgrounded tab stops
  // firing timers.
  const clockRef = useRef<{ phase: number; since: number | null }>(
    { phase: 0, since: null });
  // The seconds one lap currently takes. Written during render because the
  // value is derived from data that is only in scope after the guards below,
  // and read only from effects and event handlers, which run after it.
  const durationRef = useRef(1);
  const readPhase = () => {
    const { phase, since } = clockRef.current;
    if (since === null) return phase;
    const turned = phase + (performance.now() - since) / 1000 / durationRef.current;
    return turned - Math.floor(turned);
  };

  /** Leave fullscreen when the browser does — Escape, F11, or the user
   *  switching tabs out of it — so the overlay can never outlive it. */
  useEffect(() => {
    const sync = () => { if (!document.fullscreenElement) setFull(false); };
    document.addEventListener('fullscreenchange', sync);
    return () => document.removeEventListener('fullscreenchange', sync);
  }, []);

  /** The pause button only exists in fullscreen, so a paused replay that
   *  outlived the overlay would be frozen with nothing left on screen able to
   *  restart it. Leaving fullscreen always resumes. */
  useEffect(() => { if (!full) setPaused(false); }, [full]);

  /** Whichever mechanism stops the dots in the current mode. The phase clock
   *  has to stop with them, or a lap paused for a minute and then re-timed
   *  would resume a minute further round the circuit than the screen shows. */
  const frozen = full ? paused : hovering;
  useEffect(() => {
    if (frozen) {
      clockRef.current = { phase: readPhase(), since: null };
    } else if (clockRef.current.since === null) {
      clockRef.current = { ...clockRef.current, since: performance.now() };
    }
    // `readPhase` closes over refs only, so re-running this on every render
    // would restart the clock rather than read it — the freeze is the event.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frozen]);

  /** Escape also closes the fallback overlay, which is not a real fullscreen
   *  element and so gets no `fullscreenchange` to close it. */
  useEffect(() => {
    if (!full) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !document.fullscreenElement) setFull(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [full]);

  const toggleFull = () => {
    if (full) {
      if (document.fullscreenElement) void document.exitFullscreen().catch(() => {});
      setFull(false);
      return;
    }
    setFull(true);
    // The overlay is styled the same either way, so a browser that refuses
    // the request (or does not have the API) still gets the bigger map — it
    // just keeps its own chrome on screen.
    void wrapRef.current?.requestFullscreen?.().catch(() => {});
  };

  // Fullscreen redraws the same outline into the stage instead of a 520px box.
  // `project` preserves aspect and centres, so an over-wide box costs nothing
  // but margin; the height is what actually buys the separation. The box is
  // exactly the stage — no floor — because a minimum larger than the space
  // available is how the overlay grows a scrollbar.
  const box = full
    ? (stage && stage.w > 0 && stage.h > 0
      ? { width: stage.w, height: stage.h }
      : {
        width: Math.max(320, viewport.w - FULL_CHROME_X),
        height: Math.max(260, viewport.h - FULL_CHROME_Y),
      })
    : { width, height };

  const projected = project(track, box.width, box.height);
  if (!projected) return null;

  if (tA.length !== tB.length || tA.length < 10) return null;
  // A partial lap has no position for most of the track; a replay of it would
  // show a car teleporting onto the circuit mid-corner.
  const finite = (values: (number | null)[]) =>
    values.every((v) => v !== null && Number.isFinite(v));
  if (!finite(tA) || !finite(tB)) return null;

  const timeA = tA as number[];
  const timeB = tB as number[];
  const n = timeA.length;
  const grid = Array.from({ length: n }, (_, i) => (i / (n - 1)) * 100);
  const total = Math.max(timeA[n - 1], timeB[n - 1]) || 1;

  // The whole replay is one lap of real racing, so the playback speed is just
  // that lap divided by the multiplier the reader picked.
  const duration = total / speed;
  durationRef.current = duration;
  // A negative delay is the whole of "carry on from here": the animations are
  // restarted to be re-timed, and this starts them the distance round the lap
  // the reader had already watched rather than at the line.
  const startedAt = -(play.phase * duration);

  /** Re-time the replay without moving the cars. The clock is re-anchored here
   *  as well as read, because `readPhase` measures elapsed time against one
   *  lap duration — leaving the old anchor in place would have the seconds
   *  already watched at the old speed re-counted at the new one. */
  const changeSpeed = (next: number) => {
    if (next === speed) return;
    const phase = readPhase();
    clockRef.current = {
      phase,
      since: clockRef.current.since === null ? null : performance.now(),
    };
    setPlay((current) => ({ speed: next, phase, epoch: current.epoch + 1 }));
  };
  const steps = Math.min(
    GHOST_STEPS_MAX,
    Math.max(GHOST_STEPS_MIN, Math.round(duration / GHOST_STEP_SECONDS)),
  );

  // Who is gaining, by track position: the delta curve's own slope, smoothed
  // over ~2% of the lap exactly as the track map smooths it, so the two views
  // agree about where time changes hands.
  const delta = timeA.map((value, i) => timeB[i] - value);
  const gradient = delta.map((_, i) => {
    if (i === 0) return delta[1] - delta[0];
    if (i === n - 1) return delta[n - 1] - delta[n - 2];
    return (delta[i + 1] - delta[i - 1]) / 2;
  });
  // Named `smoothing`, not `window`: the fullscreen and reduced-motion effects
  // above need the global of that name, and a `const window` anywhere in this
  // function shadows it for the whole body.
  const smoothing = Math.max(3, Math.floor(n / 50));
  const half = Math.floor(smoothing / 2);
  const rate = gradient.map((_, i) => {
    let sum = 0;
    // A boxcar mean matching numpy's 'same'-mode convolution: positions
    // outside the array contribute zero rather than being dropped, so the
    // divisor stays the full window width.
    for (let k = i - half; k <= i - half + smoothing - 1; k += 1) {
      if (k >= 0 && k < n) sum += gradient[k];
    }
    return sum / smoothing;
  });

  const path = closedPath(projected);

  // The lap's largest gap sets the bar's full scale, rounded up to a round
  // number so "half the bar" means the same thing on every pair of laps.
  const maxGap = Math.max(...delta.map(Math.abs));
  const hasGap = maxGap >= GAP_FLOOR;
  const scale = GAP_SCALES.find((v) => v >= maxGap) ?? maxGap;

  const moves: Record<'a' | 'b', string[]> = { a: [], b: [] };
  const gaining: Record<'a' | 'b', number[]> = { a: [], b: [] };
  const gapAt: number[] = [];
  for (let step = 0; step <= steps; step += 1) {
    const fraction = step / steps;
    const elapsed = fraction * total;
    const at = fraction * 100;
    const position = {
      a: interp(elapsed, timeA, grid),
      b: interp(elapsed, timeB, grid),
    };
    for (const key of ['a', 'b'] as const) {
      moves[key].push(
        `${at.toFixed(3)}%{offset-distance:${position[key].toFixed(3)}%}`);
    }
    // Sign convention: delta is b - a, so a rising delta is the reference
    // driver pulling away.
    const index = Math.min(n - 1, Math.floor((position.a / 100) * (n - 1)));
    const slope = rate[index];
    gaining.a.push(slope > 0 ? 1 : 0);
    gaining.b.push(slope < 0 ? 1 : 0);

    // The gap is read at the *trailing* car's track position: the difference
    // in how long each took to reach the same point on the circuit, which is
    // what "N seconds behind" means and what the delta curve already plots.
    // Read at the leader's position instead and the number would be the gap at
    // a point the trailing car has not reached yet.
    const behindAt = Math.min(position.a, position.b);
    const gapIndex = Math.min(n - 1, Math.round((behindAt / 100) * (n - 1)));
    gapAt.push(delta[gapIndex]);
  }

  /**
   * Where, between step i-1 and step i, the running gap actually reaches
   * zero — linearly interpolated between the two sampled values rather than
   * assumed to be the midpoint. The marker brightness keys off this exact
   * instant rather than off the next sampled step, so the lead changing hands
   * on the map happens when it happened on track.
   */
  const crossingPercent = (i: number): number => {
    const before = gapAt[i - 1];
    const after = gapAt[i];
    const frac = before / (before - after);
    return ((i - 1 + frac) / steps) * 100;
  };

  /** A boolean cue (marker brightness) that switches at
   *  the same crossing instant the bar uses, rather than at the next sampled
   *  step — see `crossingPercent`. */
  const leadKeyframes = (
    mine: (v: number) => boolean, onValue: number, offValue: number,
  ): string => {
    const value = (v: number) => (mine(v) ? onValue : offValue);
    const stop = (at: number, v: number) => `${at.toFixed(3)}%{opacity:${v}}`;
    const parts = [stop(0, value(gapAt[0]))];
    for (let step = 1; step <= steps; step += 1) {
      if (value(gapAt[step]) === value(gapAt[step - 1])) continue;
      const cross = crossingPercent(step);
      parts.push(
        stop(cross - 0.001, value(gapAt[step - 1])), stop(cross, value(gapAt[step])));
    }
    parts.push(stop(100, value(gapAt[steps])));
    return parts.join(' ');
  };
  const leadTest: Record<'a' | 'b', (v: number) => boolean> = {
    a: (v) => v > 0,
    b: (v) => v < 0,
  };

  const keyframes = (['a', 'b'] as const).map((key) => (
    `@keyframes pw-ghost-${key}-${suffix} {${moves[key].join(' ')}}` +
    // The glow peaks well below full: at full strength it drowns the other
    // car's marker, which is sitting a couple of pixels away.
    `@keyframes pw-ghost-gaining-${key}-${suffix} ` +
    `{${switchKeyframes(gaining[key].map((v) => (v ? 0.55 : 0)), 'opacity')}}` +
    // The marker dims rather than disappearing: a car that is behind is still
    // a car on the circuit.
    `@keyframes pw-ghost-dim-${key}-${suffix} ` +
    `{${leadKeyframes(leadTest[key], 1, 0.62)}}`
  )).join('');

  // Reduced motion gets the finish rather than the race: the quicker car on
  // the line, the other still short of it by the gap it lost.
  const gap = timeB[n - 1] - timeA[n - 1];
  const [ahead, behind] = gap > 0 ? [nameA, nameB] : [nameB, nameA];
  const rest = {
    a: gap > 0 ? 100 : 99 - Math.min(Math.abs(gap), 6),
    b: gap < 0 ? 100 : 99 - Math.min(Math.abs(gap), 6),
  };

  // A ring and a dot rather than two dots. They still carry different
  // diameters, because the overlap is real and both have to stay readable
  // through it, but 14-against-10 reads as two shapes rather than as one blob
  // eating another, and the shape — not the size — is what the legend teaches.
  const cars = [
    {
      key: 'a' as const, colour: theme.colours.ref, size: 14,
      shape: 'ring' as const, name: nameA,
    },
    {
      key: 'b' as const, colour: theme.colours.cmp, size: 10,
      shape: 'dot' as const, name: nameB,
    },
  ];

  return (
    <>
      <style>{keyframes}</style>
      {/* The duration lives up here rather than on the map: the gap bar is the
          map's sibling, so a custom property set on the map would not reach it
          and every bar animation would silently fall back to a 0s duration. */}
      <div
        ref={wrapRef}
        className={
          `pw-ghost-replay${full ? ' pw-ghost-replay--full' : ''}`
          + (full && paused ? ' pw-ghost-replay--paused' : '')
        }
        style={{
          '--pw-ghost-dur': `${duration.toFixed(3)}s`,
          '--pw-ghost-delay': `${startedAt.toFixed(3)}s`,
          // The bar is the map's caption, not a full-width rule: matched to
          // the drawing's width it reads as part of the same object.
          '--pw-ghost-w': `${box.width}px`,
        } as CSSProperties}
      >
      <div className="pw-ghost-controls">
        {/* Hidden under reduced motion — with nothing animating there is no
            playback to have a speed, and `display` rather than `visibility` so
            the control does not go on occupying a row it cannot explain. */}
        <div className="pw-ghost-speed">
          <Select<number>
            label="Replay speed"
            options={GHOST_SPEEDS}
            value={speed}
            onChange={changeSpeed}
            format={(v) => `${v}x real time — ${(total / v).toFixed(1)} s`}
            help={
              'A multiple of the pace the lap was actually driven at: at 1x the '
              + 'dots take exactly as long to reach a corner as the cars did. '
              + 'Changing it picks up from where the cars are, not from the line.'
            }
          />
        </div>
        {/* Only in fullscreen, and only where there is motion to stop: inline,
            the pointer over the map already does this, and under reduced motion
            the dots are a still frame with nothing to pause. */}
        {full && (
          <button
            type="button" className="pw-ghost-pause"
            onClick={() => setPaused((v) => !v)}
            aria-pressed={paused}
          >
            {paused ? 'Resume replay' : 'Pause replay'}
          </button>
        )}
        {/* The one control that changes what the reader can *see* rather than
            what they are looking at: a few tenths is four pixels at 520px and
            three times that at the height of a screen. */}
        <button
          type="button" className="pw-ghost-full" onClick={toggleFull}
          aria-pressed={full}
        >
          {full ? 'Exit fullscreen' : 'Fullscreen'}
        </button>
      </div>
      {/* Keyed on the replay epoch so a speed change restarts the animations.
          Left to re-time themselves, running CSS animations keep their elapsed
          time and re-read it against the new duration, which throws both cars
          to an unrelated point on the circuit mid-replay. Restarting is not the
          same as going back to the line: `--pw-ghost-delay` is negative by the
          lap phase the reader was watching, so the fresh animations open at
          that point and the change reads as a change of pace, not a rewind.
          The control sits outside the keyed subtree so it keeps keyboard
          focus. */}
      <div className="pw-ghost-scroll" key={`map-${play.epoch}`} ref={setStageEl}>
      <div
        className="pw-ghost"
        // Hover pauses the dots in CSS; the gap readout is JS and needs the
        // same fact as a value, or the two would disagree about which moment
        // of the lap is on screen.
        onPointerEnter={() => setHovering(true)}
        onPointerLeave={() => setHovering(false)}
        style={{
          '--pw-ghost-path': `path('${path}')`,
          width: box.width, height: box.height,
        } as CSSProperties}
      >
        <svg width={box.width} height={box.height}
             viewBox={`0 0 ${box.width} ${box.height}`}
             role="img"
             aria-label={`${nameA} and ${nameB} replayed against each other around the circuit`}>
          <polyline
            points={polylinePoints(track, box.width, box.height)} fill="none"
            stroke={theme.colours.gridline} strokeWidth="3"
            strokeLinejoin="round" strokeLinecap="round"
          />
          <circle cx={projected.x[0].toFixed(1)} cy={projected.y[0].toFixed(1)}
                  r="3.5" fill={theme.colours.ink_primary} />
        </svg>
        {/* Every halo is laid down before any marker.

            Not a nicety: the cars sit on top of each other, so with one
            element per car the compared car's glow paints over the reference
            car's ring and erases the very thing the ring exists to show. Two
            passes over the same keyframes puts all the glow underneath, where
            it belongs. The marker is likewise its own element, so dimming the
            car that is behind does not dim its halo — the trailing car is
            very often the one gaining, which is exactly when its halo
            matters. */}
        {cars.map(({ key, colour, size }) => (
          <div
            key={`halo-${key}`} className="pw-ghost-car"
            style={{
              '--pw-ghost-colour': colour,
              '--pw-ghost-rest': `${rest[key].toFixed(1)}%`,
              '--pw-ghost-size': `${size}px`,
              animationName: `pw-ghost-${key}-${suffix}`,
            } as CSSProperties}
          >
            <span
              className="pw-ghost-halo"
              style={{ animationName: `pw-ghost-gaining-${key}-${suffix}` }}
            />
          </div>
        ))}
        {cars.map(({ key, colour, size, shape }) => (
          <div
            key={key} className="pw-ghost-car"
            style={{
              '--pw-ghost-colour': colour,
              '--pw-ghost-rest': `${rest[key].toFixed(1)}%`,
              '--pw-ghost-size': `${size}px`,
              animationName: `pw-ghost-${key}-${suffix}`,
            } as CSSProperties}
          >
            <span
              className={`pw-ghost-body pw-ghost-body--${shape}`}
              style={{ animationName: `pw-ghost-dim-${key}-${suffix}` }}
            />
          </div>
        ))}
      </div>
      </div>

      {/* Re-anchored with the map, not independently: the bar reads the gap at
          the moment the dots are showing, so a meter that kept its own clock
          through a speed change would be captioning a different instant. It
          resumes from the same phase for the same reason the map does. */}
      {hasGap && (
        <GapMeter
          key={`gap-${play.epoch}`} phase0={play.phase}
          timeA={timeA} timeB={timeB} delta={delta} grid={grid}
          total={total} speed={speed} scale={scale}
          nameA={nameA} nameB={nameB}
          colourA={theme.colours.ref} colourB={theme.colours.cmp}
          // Whichever mechanism is live in the current mode. The readout has to
          // agree with the dots about which instant of the lap is on screen, so
          // it must not still be reading hover once the map has stopped
          // honouring it.
          paused={frozen}
        />
      )}

      {/* Inside the wrapper, not beside it: fullscreen takes the wrapper, and
          a legend left outside it would be hidden underneath the overlay
          exactly when the markers are largest. */}
      <div className="pw-ghost-legend">
        <span><i style={{ borderColor: theme.colours.ref }} />{nameA}</span>
        <span>
          <i
            className="pw-ghost-legend-dot"
            style={{ background: theme.colours.cmp, borderColor: theme.colours.cmp }}
          />
          {nameB}
        </span>
        {/* Always in the DOM, not only under reduced motion: a screen reader
            has no way to watch the dots, so the result has to be readable in
            both motion modes. */}
        <span className="pw-ghost-static">
          {hasGap
            ? `${ahead} finished ${Math.abs(gap).toFixed(3)} s ahead of ${behind}`
            : 'Both laps are the same time — there is no gap to show.'}
        </span>
      </div>
      </div>
    </>
  );
}
