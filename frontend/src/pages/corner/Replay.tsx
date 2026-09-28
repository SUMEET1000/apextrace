import { useEffect, useMemo, useRef, useState } from 'react';
import { interp, pointOnTrack, project } from '../../lib/circuit';
import { SectorCircuit } from '../../components/charts/CornerCharts';
import type { Outline } from '../../lib/types';

export function Replay({ track, tA, tB, nameA, nameB, sectorFractions }: {
  track: Outline; tA: (number | null)[]; tB: (number | null)[];
  nameA: string; nameB: string; sectorFractions: number[];
}) {
  const holder = useRef<HTMLDivElement>(null);
  const clock = useRef({ elapsed: 0, at: 0 });
  const [elapsed, setElapsed] = useState(0);
  const [speed, setSpeed] = useState(2);
  const [paused, setPaused] = useState(false);
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
  const circuit = useMemo(() => points && <SectorCircuit track={points} sectorFractions={sectorFractions} strokeWidth={11} />,
    [points, sectorFractions]);
  const fractions = useMemo(() => a.map((_, i) => i / (a.length - 1)), [a]);

  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const change = () => setReduce(media.matches);
    media.addEventListener('change', change);
    return () => media.removeEventListener('change', change);
  }, []);
  useEffect(() => {
    if (!valid || reduce || paused) return;
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
  }, [valid, reduce, paused, speed, total]);
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
  const [xA, yA] = pointOnTrack(points, fA); const [xB, yB] = pointOnTrack(points, fB);
  const angle = (fraction: number) => {
    const [x0, y0] = pointOnTrack(points, Math.max(0, fraction - .003));
    const [x1, y1] = pointOnTrack(points, Math.min(1, fraction + .003));
    return Math.atan2(y1 - y0, x1 - x0) * 180 / Math.PI;
  };
  const trailing = Math.min(fA, fB);
  const gap = interp(trailing, fractions, b) - interp(trailing, fractions, a);
  const leaderA = fA > fB || (fA === fB && gap >= 0);
  const car = (x: number, y: number, rotation: number, name: string, colour: string, outline: string) =>
    <g transform={`translate(${x} ${y}) rotate(${rotation})`}>
      <path d="M-14,-8 L-9,-8 L-8,-5 L7,-5 L15,-2 L15,2 L7,5 L-8,5 L-9,8 L-14,8 Z"
        style={{ fill: colour }} stroke={outline} strokeWidth="2.5" />
      <path d="M-8,-3 L1,-3 L4,0 L1,3 L-8,3 Z" style={{ fill: colour }} stroke={outline} strokeWidth="1" />
      <title>{name}</title>
    </g>;
  const markerA = <g data-driver="a">
    {car(xA, yA, angle(fA), nameA, 'var(--driver-a)', '#fff')}
  </g>;
  const markerB = <g data-driver="b">
    {car(xB, yB, angle(fB), nameB, 'var(--driver-b)', '#131313')}
  </g>;
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
      <div className="corner-replay-controls" role="group" aria-label="Replay controls">
        {!reduce && <label className="corner-replay-speed"><span>SPEED</span><select aria-label="Replay speed" value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
          <option value={1}>1× real time</option><option value={2}>2× real time</option><option value={4}>4× real time</option>
          <option value={8}>8× real time</option><option value={10}>10× real time</option>
          <option value={15}>15× real time</option><option value={20}>20× real time</option>
        </select></label>}
        {!reduce && <button type="button" onClick={() => setPaused((v) => !v)} aria-pressed={paused}>{paused ? 'RESUME' : 'PAUSE'}</button>}
        <button type="button" onClick={toggleFull} aria-pressed={full}>{full ? 'EXIT FULLSCREEN' : 'FULLSCREEN'}</button>
      </div>
    </div>
    <div className="corner-replay-map">
      <svg viewBox="0 0 960 430" role="img" aria-label={`${nameA} and ${nameB} on the circuit at the same moment`}>
        {circuit}
        {leaderA ? <>{markerB}{markerA}</> : <>{markerA}{markerB}</>}
      </svg>
    </div>
    <div className="corner-sector-key"><span><i />Sector 1</span><span><i />Sector 2</span><span><i />Sector 3</span><span>▦ Start / finish</span></div>
    <div className="corner-replay-bottom"><span><i className="corner-driver-a" />{nameA} · REFERENCE</span><span><i className="corner-driver-b" />{nameB} · COMPARE</span>
      <strong>{Math.abs(gap).toFixed(3)} s <small>{Math.abs(gap) < .0005 ? 'LEVEL' : gap > 0 ? `${nameA} ahead` : `${nameB} ahead`}</small></strong></div>
    <div className="corner-replay-meter-labels"><span>{nameA} ahead</span><span>LEVEL</span><span>{nameB} ahead</span></div>
    <div className="corner-replay-meter" role="img" aria-label={`${Math.abs(gap).toFixed(3)} seconds, ${Math.abs(gap) < .0005 ? 'level' : `${gap > 0 ? nameA : nameB} ahead`}`}>
      <div className={gap >= 0 ? 'corner-replay-meter-a' : 'corner-replay-meter-b'}
        style={{ left: `${50 - Math.min(50, Math.abs(gap) / gapScale * 50) * Math.sign(gap)}%` }} />
    </div>
  </div>;
}
