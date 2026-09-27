import { useEffect, useMemo, useRef, useState } from 'react';
import { interp, project } from '../../lib/circuit';
import type { Outline } from '../../lib/types';

export function Replay({ track, tA, tB, nameA, nameB }: {
  track: Outline; tA: (number | null)[]; tB: (number | null)[];
  nameA: string; nameB: string;
}) {
  const holder = useRef<HTMLDivElement>(null);
  const clock = useRef({ elapsed: 0, at: 0 });
  const [elapsed, setElapsed] = useState(0);
  const [speed, setSpeed] = useState(2);
  const [paused, setPaused] = useState(false);
  const [hovering, setHovering] = useState(false);
  const [full, setFull] = useState(false);
  const [reduce, setReduce] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const valid = tA.length >= 10 && tA.length === tB.length
    && tA.every((v) => v !== null && Number.isFinite(v))
    && tB.every((v) => v !== null && Number.isFinite(v));
  const a = valid ? tA as number[] : [];
  const b = valid ? tB as number[] : [];
  const total = valid ? Math.max(a[a.length - 1], b[b.length - 1]) : 0;
  const gapScale = useMemo(() => Math.max(0.1, ...a.map((time, i) => Math.abs(b[i] - time))), [a, b]);
  const points = useMemo(() => project(track, 960, 430), [track]);
  const fractions = useMemo(() => a.map((_, i) => i / (a.length - 1)), [a]);

  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const change = () => setReduce(media.matches);
    media.addEventListener('change', change);
    return () => media.removeEventListener('change', change);
  }, []);
  useEffect(() => {
    if (!valid || reduce || paused || (hovering && !full)) return;
    let frame = 0;
    clock.current.at = performance.now();
    const tick = (now: number) => {
      clock.current.elapsed = (clock.current.elapsed + (now - clock.current.at) / 1000 * speed) % total;
      clock.current.at = now;
      setElapsed(clock.current.elapsed);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [valid, reduce, paused, hovering, full, speed, total]);
  useEffect(() => {
    const sync = () => { if (!document.fullscreenElement) setFull(false); };
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !document.fullscreenElement) setFull(false);
    };
    document.addEventListener('fullscreenchange', sync);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('fullscreenchange', sync);
      document.removeEventListener('keydown', escape);
    };
  }, []);
  if (!valid || !points || total <= 0) return <p>Replay is unavailable for these laps.</p>;

  const time = reduce ? total : elapsed;
  const fA = interp(Math.min(time, a[a.length - 1]), a, fractions);
  const fB = interp(Math.min(time, b[b.length - 1]), b, fractions);
  const at = (fraction: number) => {
    const index = fraction * (points.x.length - 1);
    const low = Math.floor(index); const high = Math.min(points.x.length - 1, low + 1);
    const mix = index - low;
    return [points.x[low] + (points.x[high] - points.x[low]) * mix,
      points.y[low] + (points.y[high] - points.y[low]) * mix];
  };
  const [xA, yA] = at(fA); const [xB, yB] = at(fB);
  const trailing = Math.min(fA, fB);
  const gap = interp(trailing, fractions, b) - interp(trailing, fractions, a);
  const near = Math.min(a.length - 2, Math.max(1, Math.floor(trailing * (a.length - 1))));
  const slope = (b[near + 1] - a[near + 1]) - (b[near - 1] - a[near - 1]);
  const leaderA = fA >= fB;
  const glowA = slope > 0.001; const glowB = slope < -0.001;
  const path = points.x.map((x, i) => `${x.toFixed(1)},${points.y[i].toFixed(1)}`).join(' ');
  const toggleFull = () => {
    if (full) {
      if (document.fullscreenElement) void document.exitFullscreen().catch(() => setFull(false));
      else setFull(false);
    } else {
      if (holder.current?.requestFullscreen) {
        void holder.current.requestFullscreen().then(() => setFull(true)).catch(() => setFull(true));
      } else setFull(true);
    }
  };
  return <div className={`corner-replay${full ? ' corner-replay-full' : ''}`} ref={holder}>
    <div className="corner-replay-top"><div><span className="lab">RECORDED LAP REPLAY</span>
      <strong>{nameA} <em>vs</em> {nameB}</strong></div>
      <div className="corner-replay-controls">
        {!reduce && <label>Speed <select aria-label="Replay speed" value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
          <option value={1}>1× real time</option><option value={2}>2× real time</option><option value={4}>4× real time</option>
        </select></label>}
        {!reduce && <button type="button" onClick={() => setPaused((v) => !v)} aria-pressed={paused}>{paused ? 'RESUME' : 'PAUSE'}</button>}
        <button type="button" onClick={toggleFull} aria-pressed={full}>{full ? 'EXIT FULLSCREEN' : 'FULLSCREEN'}</button>
      </div>
    </div>
    <div className="corner-replay-map" onPointerEnter={() => setHovering(true)} onPointerLeave={() => setHovering(false)}>
      <svg viewBox="0 0 960 430" role="img" aria-label={`${nameA} and ${nameB} on the circuit at the same moment`}>
        <polyline points={path} fill="none" stroke="currentColor" strokeWidth="7" strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={xA} cy={yA} r="13" className={glowA ? 'corner-replay-glow-a' : ''} fill="none" stroke="#131313" strokeWidth="5" opacity={leaderA ? 1 : .48} />
        <circle cx={xB} cy={yB} r="8" className={glowB ? 'corner-replay-glow-b' : ''} fill="#E23B2E" stroke="#131313" strokeWidth="2" opacity={leaderA ? .48 : 1} />
      </svg>
    </div>
    <div className="corner-replay-bottom"><span>◯ {nameA} · REFERENCE</span><span>● {nameB} · COMPARE</span>
      <strong>{Math.abs(gap).toFixed(3)} s <small>{gap >= 0 ? `${nameA} ahead` : `${nameB} ahead`}</small></strong></div>
    <div className="corner-replay-meter"><div style={{ width: `${Math.min(100, Math.abs(gap) / gapScale * 100)}%` }} /></div>
  </div>;
}
