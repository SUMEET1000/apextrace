import { useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { placeCornerMarks, placeTurnNumbers, pointOnTrack, type CornerMark, type Projected } from '../../lib/circuit';

gsap.registerPlugin(ScrollTrigger);

type Series = (number | null)[];
type Sector = { x: number[]; y: number[]; value: number };
type Corners = { x: number[]; y: number[]; labels: string[] };

export type MapData = {
  x: number[]; y: number[]; rate?: Series; speed?: Series;
  distance_m?: number[];
  sectors: Sector[]; corners: Corners; lo?: number; hi?: number; limit?: number;
  finding: string; x_unit: string; y_unit: string; colour_unit: string;
};
export type TraceData = {
  drivers: { name: string; distance: number[]; speed: Series; throttle: Series;
    brake: Series; gear: Series }[];
  delta: Series; corners: { apex_m: number; label: string }[];
  finding: string; x_unit: string;
};
export type CornerBarData = {
  labels: string[]; delta_s: Series; faster: string[]; finding: string;
};
export type LapData = {
  lap_times: { driver: string; lap: number[]; time_s: Series; pit_lap: number[] }[];
  delta: { lap: number[]; seconds: Series };
  cumulative: { lap: number[]; seconds: Series };
  finding: string;
};

function Frame({ id, finding, children }: { id: string; finding: string; children: ReactNode }) {
  const frame = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    const node = frame.current;
    if (!node) return;
    const media = gsap.matchMedia();
    media.add('(prefers-reduced-motion: no-preference)', () => {
      const clips = [...node.querySelectorAll<SVGRectElement>('[data-plot-draw]')];
      const context = gsap.context(() => clips.forEach((clip) => {
        const svg = clip.ownerSVGElement;
        if (!svg) return;
        const width = Number(clip.getAttribute('width'));
        gsap.set(clip, { attr: { width: 0 } });
        const below = svg.getBoundingClientRect().top >= innerHeight * .85;
        const tween = gsap.to(clip, { attr: { width }, duration: .8, ease: 'power2.inOut', paused: below });
        if (below) ScrollTrigger.create({ trigger: svg, start: 'top 88%', once: true, onEnter: () => tween.play() });
      }), node);
      return () => context.revert();
    });
    return () => media.revert();
  }, [id]);
  return <figure className="corner-chart" ref={frame}><figcaption data-finding>{finding}</figcaption>
    <div data-chart={id}>{children}</div></figure>;
}

function DriverLegend({ reference, compare }: { reference: string; compare: string }) {
  return <div className="corner-chart-legend" role="group" aria-label="Driver line legend">
    <span><i className="corner-legend-line reference" aria-hidden="true" /><span><small>REFERENCE · SOLID BLACK</small><strong>{reference}</strong></span></span>
    <span><i className="corner-legend-line compare" aria-hidden="true" /><span><small>COMPARE · DASHED RED</small><strong>{compare}</strong></span></span>
  </div>;
}

function extent(values: Series): [number, number] {
  const finite = values.filter((v): v is number => v !== null && Number.isFinite(v));
  return finite.length ? [Math.min(...finite), Math.max(...finite)] : [0, 1];
}

export function CornerLabels({ track, corners, width, height, size = 24, sectorFractions = [] }: {
  track: Projected; corners: CornerMark[]; width: number; height: number; size?: number;
  sectorFractions?: number[];
}) {
  const timedSectors = sectorFractions.length === 2 && sectorFractions[0] > 0
    && sectorFractions[1] > sectorFractions[0] && sectorFractions[1] < 1
  const sectors = (timedSectors ? [0, sectorFractions[0] / 2,
    (sectorFractions[0] + sectorFractions[1]) / 2, (sectorFractions[1] + 1) / 2] : [0])
    .map((fraction, i) => {
          const [x, y] = pointOnTrack(track, fraction);
          return { x, y, label: i === 0 ? 'S/F' : `S${i}` };
        });
  const marks = [...corners, ...sectors];
  const labels = placeCornerMarks(track, marks, width, height, size);
  return <g className="circuit-labels">{(timedSectors ? [0, ...sectorFractions] : [0]).map((fraction, i) => {
    const [x, y] = pointOnTrack(track, fraction);
    return <rect key={i} x={x - 5} y={y - 5} width="10" height="10" fill="#F2E600"
      stroke="#131313" strokeWidth="2"><title>{i === 0 ? 'Start / finish' : `Sector ${i} ends`}</title></rect>;
  })}{labels.map((mark, i) => {
    const target = marks[i];
    const lineX = mark.x + Math.max(-size / 2, Math.min(size / 2, target.x - mark.x));
    const lineY = mark.y + Math.max(-size / 2, Math.min(size / 2, target.y - mark.y));
    return <g key={`${mark.label}-${i}`}>
      <line x1={target.x} y1={target.y} x2={lineX} y2={lineY} stroke="#686862" strokeWidth="1" />
      <rect x={mark.x - size / 2} y={mark.y - size / 2} width={size} height={size}
        fill={i >= corners.length ? '#F2E600' : '#E7E7E3'} stroke="#131313" strokeWidth="2" />
      <text x={mark.x} y={mark.y + size * .17} textAnchor="middle"
        fontSize={size * .5} fontWeight="700" fill="#131313">{mark.label}</text>
    </g>;
  })}</g>;
}

const sectorColours = ['var(--sector-1)', 'var(--sector-2)', 'var(--sector-3)'];

function useScrollDraw<T extends SVGElement>(ref: RefObject<T | null>, redraw?: unknown, segmented = false) {
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    const media = gsap.matchMedia();
    media.add('(prefers-reduced-motion: no-preference)', () => {
      const paths = [...node.querySelectorAll<SVGPolylineElement>(':scope > polyline')];
      const drawnPaths = segmented ? paths.slice(0, 1) : paths;
      const segments = segmented ? paths.slice(1) : [];
      const marks = [...node.querySelectorAll<SVGElement>(':scope > g')];
      const lengths = drawnPaths.map((path) => path.getTotalLength());
      const context = gsap.context(() => {
        drawnPaths.forEach((path, i) => gsap.set(path, { strokeDasharray: lengths[i], strokeDashoffset: lengths[i] }));
        gsap.set([...segments, ...marks], { opacity: 0 });
        const below = node.getBoundingClientRect().top >= innerHeight * .85;
        const timeline = gsap.timeline({ paused: below })
          .to(drawnPaths, { strokeDashoffset: 0, duration: 1.1, stagger: .08, ease: 'power2.inOut' }, 0);
        if (segments.length) timeline.to(segments, { opacity: 1, duration: .12, stagger: { amount: .9 }, ease: 'none' }, .12);
        if (marks.length) timeline.to(marks, { opacity: 1, duration: .25 }, .8);
        if (below) ScrollTrigger.create({ trigger: node, start: 'top 88%', once: true, onEnter: () => timeline.play() });
      }, node);
      return () => context.revert();
    });
    return () => media.revert();
  }, [ref, redraw, segmented]);
}

function StartDirectionArrow({ track }: { track: Projected }) {
  const size = 24;
  let remaining = 28;
  let x = track.x[0]; let y = track.y[0]; let angle = 0;
  for (let i = 1; i < track.x.length; i++) {
    const dx = track.x[i] - track.x[i - 1];
    const dy = track.y[i] - track.y[i - 1];
    const length = Math.hypot(dx, dy);
    if (length === 0) continue;
    angle = Math.atan2(dy, dx);
    if (remaining <= length) {
      x = track.x[i - 1] + dx * remaining / length;
      y = track.y[i - 1] + dy * remaining / length;
      break;
    }
    remaining -= length;
    x = track.x[i]; y = track.y[i];
  }
  return <g className="circuit-direction" aria-label="Racing direction from start and finish"
    transform={`translate(${x} ${y}) rotate(${angle * 180 / Math.PI})`}>
    <path d={`M${-size / 2},0 H${size / 2} M${size / 2 - 7},-5 L${size / 2},0 L${size / 2 - 7},5`}
      fill="none" stroke="#f5f5f1" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
    <path d={`M${-size / 2},0 H${size / 2} M${size / 2 - 7},-5 L${size / 2},0 L${size / 2 - 7},5`}
      fill="none" stroke="#131313" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    <title>Racing direction</title>
  </g>;
}

export function SectorCircuit({ track, sectorFractions, strokeWidth = 10 }: {
  track: Projected; sectorFractions: number[]; strokeWidth?: number;
}) {
  const circuit = useRef<SVGGElement>(null);
  useScrollDraw(circuit, track);
  const valid = sectorFractions.length === 2 && 0 < sectorFractions[0]
    && sectorFractions[0] < sectorFractions[1] && sectorFractions[1] < 1;
  const bounds = valid ? [0, ...sectorFractions, 1] : [0, 1];
  const path = track.x.map((x, i) => `${x},${track.y[i]}`).join(' ');
  const [finishX, finishY] = pointOnTrack(track, 0);
  return <g className="sector-circuit" ref={circuit}>
    <polyline points={path} fill="none" stroke="#131313" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" />
    {valid && sectorColours.map((colour, i) => {
      const start = bounds[i]; const end = bounds[i + 1];
      const points = [pointOnTrack(track, start),
        ...track.x.flatMap((x, index) => {
          const fraction = index / (track.x.length - 1);
          return fraction > start && fraction < end ? [[x, track.y[index]]] : [];
        }), pointOnTrack(track, end)];
      return <polyline key={i} points={points.map(([px, py]) => `${px},${py}`).join(' ')} fill="none"
        style={{ stroke: colour }} strokeWidth={strokeWidth * .55} strokeLinecap="round" strokeLinejoin="round" />;
    })}
    <g aria-label="Start and finish line">
      <rect x={finishX - 6} y={finishY - 6} width="12" height="12" fill="#f5f5f1" stroke="#131313" strokeWidth="1.5" />
      <path d={`M${finishX - 6},${finishY - 6}h6v6h-6z M${finishX},${finishY}h6v6h-6z`} fill="#131313" />
      <title>Start and finish</title>
    </g>
    <StartDirectionArrow track={track} />
  </g>;
}

function SubtleTurnLabels({ track, corners, width, height, sectorFractions }: {
  track: Projected; corners: CornerMark[]; width: number; height: number; sectorFractions: number[];
}) {
  const [finishX, finishY] = pointOnTrack(track, 0);
  const placed = placeTurnNumbers(track, corners, width, height);
  return <><g className="corner-map-marks">
    {placed.map((mark, i) => <g key={`${mark.label}-${i}`}>
      <circle cx={corners[i].x} cy={corners[i].y} r="2.5" fill="#f5f5f1" stroke="#131313" strokeWidth="1" />
      <text x={mark.x} y={mark.y + 3.5} textAnchor="middle" fill="#595953"
        stroke="#f5f5f1" strokeWidth="2" paintOrder="stroke"
        fontSize="11" fontWeight="600">{mark.label}</text>
    </g>)}
    {sectorFractions.map((fraction, i) => {
      const [x, y] = pointOnTrack(track, fraction);
      return <rect key={i} x={x - 3} y={y - 3} width="6" height="6" fill="#f5f5f1" stroke="#131313" strokeWidth="1.5">
        <title>Sector {i + 1} ends</title>
      </rect>;
    })}
    <rect x={finishX - 5} y={finishY - 5} width="10" height="10" fill="#f5f5f1" stroke="#131313" strokeWidth="2">
      <title>Start and finish</title>
    </rect>
  </g><StartDirectionArrow track={track} /></>;
}

function line(xs: number[], ys: Series, box: { x: number; y: number; w: number; h: number },
              domainX: [number, number], domainY: [number, number], stepped = false): string {
  const px = (v: number) => box.x + (v - domainX[0]) / (domainX[1] - domainX[0] || 1) * box.w;
  const py = (v: number) => box.y + box.h - (v - domainY[0]) / (domainY[1] - domainY[0] || 1) * box.h;
  let path = '';
  let previous: [number, number] | null = null;
  ys.forEach((value, i) => {
    if (value === null || !Number.isFinite(value) || !Number.isFinite(xs[i])) { previous = null; return; }
    const x = px(xs[i]); const y = py(value);
    path += previous ? `${stepped ? `H${x.toFixed(1)}V${y.toFixed(1)}` : `L${x.toFixed(1)},${y.toFixed(1)}`}`
      : `M${x.toFixed(1)},${y.toFixed(1)}`;
    previous = [x, y];
  });
  return path;
}

const plotBox = { x: 88, y: 28, w: 687, h: 60 };

function tick(value: number, unit: string): string {
  if (unit === 'on / off') return value ? 'ON' : 'OFF';
  if (unit === 'gear' || unit === 'km/h' || unit === '%' || unit === 'm' || unit === 'lap') return value.toFixed(0);
  return value.toFixed(unit === 's' ? 3 : 2);
}

function axisTick(value: number, unit: string): string {
  const number = tick(value, unit);
  if (unit === 'lap') return `L${number}`;
  if (unit === 'gear') return `G${number}`;
  if (unit === '%') return `${number}%`;
  if (unit === 'on / off') return number;
  return `${number} ${unit}`;
}

function ChartAxes({ x, y, unit, xUnit }: {
  x: [number, number]; y: [number, number]; unit: string; xUnit: string;
}) {
  return <g className="corner-chart-axes">
    <line className="corner-axis-edge" x1={plotBox.x} y1={plotBox.y} x2={plotBox.x} y2={plotBox.y + plotBox.h} />
    {(unit === 'on / off' ? [0, 1] : [0, .5, 1]).map((fraction) => {
    const yy = plotBox.y + plotBox.h * (1 - fraction);
    return <g key={fraction}>
      <line x1={plotBox.x} y1={yy} x2={plotBox.x + plotBox.w} y2={yy} />
      <text x={plotBox.x - 8} y={yy + 4} textAnchor="end">{axisTick(y[0] + fraction * (y[1] - y[0]), unit)}</text>
    </g>;
  })}
    {[0, .5, 1].map((fraction) => {
      const xx = plotBox.x + plotBox.w * fraction;
      return <g key={fraction}>
        <line x1={xx} y1={plotBox.y + plotBox.h} x2={xx} y2={plotBox.y + plotBox.h + 5} />
        <text x={xx} y="110" textAnchor={fraction === 0 ? 'start' : fraction === 1 ? 'end' : 'middle'}>
          {axisTick(x[0] + fraction * (x[1] - x[0]), xUnit)}
        </text>
      </g>;
    })}
    <text className="corner-axis-title" x={plotBox.x + plotBox.w / 2} y="135" textAnchor="middle">
      X · {xUnit === 'm' ? 'LAP DISTANCE (m)' : 'LAP NUMBER'}
    </text>
  </g>;
}

function nearest(xs: number[], ys: Series, at: number): number | null {
  if (!xs.length) return null;
  const i = xs.findIndex((x) => x >= at);
  const index = i < 0 ? xs.length - 1 : i > 0 && at - xs[i - 1] < xs[i] - at ? i - 1 : i;
  return ys[index] ?? null;
}

function atLap(xs: number[], ys: Series, lap: number): number | null {
  const index = xs.indexOf(lap);
  return index < 0 ? null : ys[index] ?? null;
}

export function MapRibbon({ data, id, label, sectorFractions, nameA, nameB }: {
  data: MapData; id: string; label: string; sectorFractions: number[]; nameA: string; nameB: string;
}) {
  const circuit = useRef<SVGSVGElement>(null);
  useScrollDraw(circuit, data, true);
  const allX = data.x; const allY = data.y;
  const [minX, maxX] = extent(allX); const [minY, maxY] = extent(allY);
  const scale = Math.min(740 / (maxX - minX || 1), 290 / (maxY - minY || 1));
  const offsetX = (960 - (maxX - minX) * scale) / 2;
  const offsetY = (450 - (maxY - minY) * scale) / 2;
  const point = (x: number, y: number) => [offsetX + (x - minX) * scale,
    450 - offsetY - (y - minY) * scale];
  const coords = (xs: number[], ys: number[]) => xs.map((x, i) => point(x, ys[i]).map((v) => v.toFixed(1)).join(','));
  const [low, high] = data.rate ? [-(data.limit ?? 0), data.limit ?? 0]
    : [data.lo ?? 0, data.hi ?? 0];
  const sampleMeters = data.distance_m && data.distance_m.length > 1
    ? (data.distance_m[data.distance_m.length - 1] - data.distance_m[0]) / (data.distance_m.length - 1) : 0;
  const gainFactor = sampleMeters > 0 ? 100 / sampleMeters : 1;
  const gainUnit = sampleMeters > 0 ? 's / 100 m' : 's / sample';
  const swatch = (sector: Sector) => {
    if (data.rate) return sector.value > high * 0.1 ? '#F2E600'
      : sector.value < low * 0.1 ? '#E23B2E' : '#686862';
    return sector.value >= low + (high - low) * 0.66 ? '#F2E600'
      : sector.value >= low + (high - low) * 0.33 ? '#131313' : '#E23B2E';
  };
  return <Frame id={id} finding={data.finding}>
    <div className="corner-map-head"><b>{label}</b><span>{data.rate ? 'LOCAL GAP CHANGE' : `SPEED · ${data.colour_unit}`}</span></div>
    <svg ref={circuit} viewBox="0 0 960 450" role="img" aria-label={label}>
      <polyline points={coords(allX, allY).join(' ')} fill="none" stroke="#131313" strokeWidth="16" strokeLinejoin="round" />
      {data.sectors.map((sector, i) => <polyline key={i} points={coords(sector.x, sector.y).join(' ')}
        fill="none" stroke={swatch(sector)} strokeWidth="10" strokeLinejoin="round">
        <title>{data.rate ? `${sector.value >= 0 ? nameA : nameB} gaining · ${(Math.abs(sector.value) * gainFactor).toFixed(3)} ${gainUnit}` : `${sector.value.toFixed(0)} km/h`}</title>
      </polyline>)}
      <SubtleTurnLabels track={{ x: allX.map((x) => point(x, 0)[0]), y: allY.map((y) => point(0, y)[1]) }}
        corners={data.corners.x.map((x, i) => {
          const [px, py] = point(x, data.corners.y[i]);
          return { x: px, y: py, label: data.corners.labels[i] };
        })} width={960} height={450} sectorFractions={sectorFractions} />
    </svg>
    {sectorFractions.length === 2 && <div className="corner-map-sector-key">
      <span>Sector 1 · 0–{Math.round(sectorFractions[0] * 100)}% of lap</span>
      <span>Sector 2 · {Math.round(sectorFractions[0] * 100)}–{Math.round(sectorFractions[1] * 100)}%</span>
      <span>Sector 3 · {Math.round(sectorFractions[1] * 100)}–100%</span>
    </div>}
    <div className="corner-map-scale" aria-label={data.rate ? 'Local time gain scale' : 'Speed scale'}>
      <span><i style={{ background: '#E23B2E' }} />{data.rate ? `${nameB} gains · ≤ ${(-high * .1 * gainFactor).toFixed(3)} ${gainUnit}` : `SLOW · ${low.toFixed(0)}–${(low + (high - low) / 3).toFixed(0)} km/h`}</span>
      <span><i style={{ background: data.rate ? '#686862' : '#131313' }} />{data.rate ? 'NEAR EVEN' : `MID · ${(low + (high - low) / 3).toFixed(0)}–${(low + 2 * (high - low) / 3).toFixed(0)} km/h`}</span>
      <span><i style={{ background: '#F2E600' }} />{data.rate ? `${nameA} gains · ≥ ${(high * .1 * gainFactor).toFixed(3)} ${gainUnit}` : `FAST · ${(low + 2 * (high - low) / 3).toFixed(0)}–${high.toFixed(0)} km/h`}</span>
    </div>
    <p className="corner-axis">Small squares mark the start/finish and sector boundaries; the arrow shows racing direction. Turn numbers sit beside the circuit. {sectorFractions.length !== 2 ? 'Sector timing is unavailable for these laps. ' : ''}{data.rate ? `Colour shows local gap change, from ${(low * gainFactor).toFixed(3)} to +${(high * gainFactor).toFixed(3)} ${gainUnit}.` : `Measured speed ranges from ${low.toFixed(0)} to ${high.toFixed(0)} km/h.`}</p>
  </Frame>;
}

export function TracePanel({ data }: { data: TraceData }) {
  if (data.drivers.length < 2) return null;
  const maxDistance = Math.max(...data.drivers.flatMap((d) => d.distance));
  const [distance, setDistance] = useState(data.corners[0]?.apex_m ?? 0);
  const rows: { key: 'speed' | 'throttle' | 'brake' | 'gear'; label: string; unit: string; stepped: boolean }[] = [
    { key: 'speed', label: 'SPEED', unit: 'km/h', stepped: false },
    { key: 'throttle', label: 'THROTTLE', unit: '%', stepped: false },
    { key: 'brake', label: 'BRAKE', unit: 'on / off', stepped: true },
    { key: 'gear', label: 'GEAR', unit: 'gear', stepped: true },
  ];
  const allDelta = extent(data.delta);
  const nearby = data.corners.reduce<{ apex_m: number; label: string } | null>((best, corner) =>
    Math.abs(corner.apex_m - distance) < Math.abs((best?.apex_m ?? Infinity) - distance) ? corner : best, null);
  const at = (driver: TraceData['drivers'][number], key: 'speed' | 'throttle' | 'brake' | 'gear') =>
    nearest(driver.distance, driver[key], distance);
  const shown = (value: number | null, unit: string) => value === null ? 'no sample' : `${tick(value, unit)}${unit === 'km/h' || unit === '%' ? ` ${unit}` : ''}`;
  return <Frame id="trace-panel" finding={data.finding}>
    <p className="corner-chart-explain">Both laps share distance along the track. Vertical guides mark turn apexes; a gap in a line means the feed has no reading there.</p>
    <DriverLegend reference={data.drivers[0].name} compare={data.drivers[1].name} />
    <div className="corner-chart-readout"><strong>{distance.toFixed(0)} m{nearby && Math.abs(nearby.apex_m - distance) < 130 ? ` · ${nearby.label}` : ''}</strong>
      <span>{data.drivers.map((driver) => `${driver.name}: ${shown(at(driver, 'speed'), 'km/h')} · throttle ${shown(at(driver, 'throttle'), '%')} · brake ${shown(at(driver, 'brake'), 'on / off')} · gear ${shown(at(driver, 'gear'), 'gear')}`).join(' / ')}</span>
      <span>Running delta: {shown(nearest(data.drivers[0].distance, data.delta, distance), 's')} s · positive means {data.drivers[0].name} ahead</span></div>
    <label className="corner-chart-scrubber">Inspect distance <input type="range" min="0" max={maxDistance} step="1" value={distance}
      onChange={(event) => setDistance(Number(event.target.value))} /></label>
    {rows.map((row) => {
      const limits = extent(data.drivers.flatMap((d) => d[row.key]));
      const domain: [number, number] = row.key === 'brake' ? [0, 1] : row.key === 'throttle' ? [0, 100]
        : row.key === 'gear' ? limits : [Math.min(0, limits[0]), limits[1] || 1];
      return <div className="corner-trace-row" key={row.key}><span>{row.label}<small>Y · {row.unit}</small></span>
        <div className="corner-plot"><svg viewBox="0 0 800 142" aria-label={`${row.label} (${row.unit}) against lap distance (m)`}>
          <defs><clipPath id={`corner-trace-${row.key}`}><rect data-plot-draw x={plotBox.x} y={plotBox.y - 4} width={plotBox.w} height={plotBox.h + 8} /></clipPath></defs>
          <ChartAxes x={[0, maxDistance]} y={domain} unit={row.unit} xUnit="m" />
          {data.corners.map((corner, i) => <g key={i} className="corner-turn-guide">
            <line x1={plotBox.x + corner.apex_m / maxDistance * plotBox.w} y1={plotBox.y} x2={plotBox.x + corner.apex_m / maxDistance * plotBox.w} y2={plotBox.y + plotBox.h} />
            {row.key === 'speed' && <text x={plotBox.x + corner.apex_m / maxDistance * plotBox.w} y={i % 2 ? 24 : 12} textAnchor="middle">{corner.label}</text>}
          </g>)}
          <g clipPath={`url(#corner-trace-${row.key})`}>
            <path d={line(data.drivers[0].distance, data.drivers[0][row.key], plotBox, [0, maxDistance], domain, row.stepped)} className="trace-a" />
            <path d={line(data.drivers[1].distance, data.drivers[1][row.key], plotBox, [0, maxDistance], domain, row.stepped)} className="trace-b" />
          </g>
          <line className="corner-cursor" x1={plotBox.x + distance / maxDistance * plotBox.w} x2={plotBox.x + distance / maxDistance * plotBox.w} y1={plotBox.y} y2={plotBox.y + plotBox.h} />
        </svg></div></div>;
    })}
    <div className="corner-trace-row"><span>DELTA<small>Y · s</small></span>
      <div className="corner-plot"><svg viewBox="0 0 800 142" aria-label="Running time delta (s) against lap distance (m)">
        <defs><clipPath id="corner-trace-delta"><rect data-plot-draw x={plotBox.x} y={plotBox.y - 4} width={plotBox.w} height={plotBox.h + 8} /></clipPath></defs>
        <ChartAxes x={[0, maxDistance]} y={allDelta} unit="s" xUnit="m" />
        {data.corners.map((corner, i) => <line key={i} className="corner-turn-guide" x1={plotBox.x + corner.apex_m / maxDistance * plotBox.w} x2={plotBox.x + corner.apex_m / maxDistance * plotBox.w} y1={plotBox.y} y2={plotBox.y + plotBox.h} />)}
        <g clipPath="url(#corner-trace-delta)"><path d={line(data.drivers[0].distance, data.delta, plotBox, [0, maxDistance], allDelta)} className="trace-a" /></g>
        <line className="corner-cursor" x1={plotBox.x + distance / maxDistance * plotBox.w} x2={plotBox.x + distance / maxDistance * plotBox.w} y1={plotBox.y} y2={plotBox.y + plotBox.h} />
      </svg></div></div>
    <p className="corner-axis">Each row shows its Y measure and unit; X is lap distance in {data.x_unit}. DELTA is {data.drivers[1].name} minus {data.drivers[0].name}; negative means {data.drivers[1].name} ahead at that point.</p>
  </Frame>;
}

export function CornerBars({ data }: { data: CornerBarData }) {
  const bars = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const node = bars.current;
    if (!node) return;
    const media = gsap.matchMedia();
    media.add('(prefers-reduced-motion: no-preference)', () => {
      const context = gsap.context(() => {
        const fills = node.querySelectorAll('.corner-bar-track > div');
        gsap.set(fills, { scaleX: 0 });
        const below = node.getBoundingClientRect().top >= innerHeight * .85;
        const tween = gsap.to(fills, { scaleX: 1, duration: .7, ease: 'power2.out', stagger: .05, paused: below });
        if (below) ScrollTrigger.create({ trigger: node, start: 'top 88%', once: true, onEnter: () => tween.play() });
      }, node);
      return () => context.revert();
    });
    return () => media.revert();
  }, [data]);
  const max = Math.max(0.001, ...data.delta_s.map((v) => Math.abs(v ?? 0)));
  return <Frame id="corner-delta-bars" finding={data.finding}>
    <p className="corner-chart-explain">Each bar is one measured segment. Left means the comparison lap gained time; right means the reference lap gained time. Bar length is proportional to the seconds printed beside it.</p>
    <div className="corner-bar-axis"><span>SEGMENT</span><div><strong>TIME GAIN / LOSS (s)</strong>
      <div className="corner-bar-scale"><span>−{max.toFixed(3)} s</span><span>0 s</span><span>+{max.toFixed(3)} s</span></div></div>
      <span>EXACT Δ (s)</span></div>
    <div className="corner-bars" role="img" aria-label="Time gained or lost by segment in seconds" ref={bars}>
      {data.labels.map((label, i) => {
        const value = data.delta_s[i];
        return <div className="corner-bar" key={`${label}-${i}`}><span>{label}</span>
          <div className="corner-bar-track"><div style={{ width: `${Math.abs(value ?? 0) / max * 50}%`,
            left: value !== null && value < 0 ? `${50 - Math.abs(value) / max * 50}%` : '50%',
            background: value !== null && value < 0 ? '#E23B2E' : '#131313',
            transformOrigin: value !== null && value < 0 ? 'right center' : 'left center' }} /></div>
          <strong>{value === null ? '—' : `${value >= 0 ? '+' : ''}${value.toFixed(3)} s`}</strong></div>;
      })}
    </div>
    <p className="corner-axis">LEFT: COMPARE GAINS / RIGHT: REFERENCE GAINS · s</p>
  </Frame>;
}

export function LapChart({ data }: { data: LapData }) {
  const firstLap = Math.min(...data.lap_times.flatMap((driver) => driver.lap));
  const lastLap = Math.max(...data.lap_times.flatMap((driver) => driver.lap));
  const [selectedLap, setSelectedLap] = useState(firstLap);
  const lapSeconds = (laps: number[], seconds: Series) => {
    const value = atLap(laps, seconds, selectedLap);
    return value === null ? 'no pair' : `${value.toFixed(3)} s`;
  };
  const rows = [
    { label: 'LAP TIME', unit: 's', series: data.lap_times.map((r) => ({ x: r.lap, y: r.time_s, name: r.driver })) },
    { label: 'LAP DELTA', unit: 's', series: [{ x: data.delta.lap, y: data.delta.seconds, name: 'Delta' }] },
    { label: 'RUNNING GAP', unit: 's', series: [{ x: data.cumulative.lap, y: data.cumulative.seconds, name: 'Cumulative' }] },
  ].filter((row) => row.series.some((series) => series.y.some((value) => value !== null && Number.isFinite(value))));
  return <Frame id="lap-by-lap" finding={data.finding}>
    <p className="corner-chart-explain">Top: each driver's lap time. Middle: compare minus reference on that lap. Bottom: the sum of those differences across comparable laps; it is not the on-track race gap. Red dashed guides mark pit laps.</p>
    <DriverLegend reference={data.lap_times[0]?.driver ?? ''} compare={data.lap_times[1]?.driver ?? ''} />
    <div className="corner-chart-readout"><strong>Lap {selectedLap}</strong>
      <span>{data.lap_times.map((driver) => {
        const value = atLap(driver.lap, driver.time_s, selectedLap);
        return `${driver.driver}: ${value === null ? 'no time' : `${value.toFixed(3)} s`}${driver.pit_lap?.includes(selectedLap) ? ' · pit lap' : ''}`;
      }).join(' / ')}</span>
      <span>Per-lap delta: {lapSeconds(data.delta.lap, data.delta.seconds)} · running sum: {lapSeconds(data.cumulative.lap, data.cumulative.seconds)}</span></div>
    <label className="corner-chart-scrubber">Inspect lap <input type="range" min={firstLap} max={lastLap} step="1" value={selectedLap}
      onChange={(event) => setSelectedLap(Number(event.target.value))} /></label>
    {rows.map((row) => {
      const yDomain = extent(row.series.flatMap((s) => s.y));
      return <div className="corner-trace-row" key={row.label}><span>{row.label}<small>Y · {row.unit}</small></span>
        <div className="corner-plot"><svg viewBox="0 0 800 142" aria-label={`${row.label} (${row.unit}) by lap number`}>
          <defs><clipPath id={`corner-lap-${row.label.toLowerCase().replaceAll(' ', '-')}`}><rect data-plot-draw x={plotBox.x} y={plotBox.y - 4} width={plotBox.w} height={plotBox.h + 8} /></clipPath></defs>
          <ChartAxes x={[firstLap, lastLap]} y={yDomain} unit="s" xUnit="lap" />
          {row.label === 'LAP TIME' && data.lap_times.flatMap((driver) => driver.pit_lap ?? []).filter((lap, i, all) => all.indexOf(lap) === i).map((lap) =>
            <g key={lap} className="corner-pit-guide"><title>Pit lap {lap}</title>
              <line x1={plotBox.x + (lap - firstLap) / (lastLap - firstLap || 1) * plotBox.w} x2={plotBox.x + (lap - firstLap) / (lastLap - firstLap || 1) * plotBox.w} y1={plotBox.y} y2={plotBox.y + plotBox.h} /></g>)}
          <g clipPath={`url(#corner-lap-${row.label.toLowerCase().replaceAll(' ', '-')})`}>
            {row.series.map((series, i) => <path key={series.name}
              d={line(series.x, series.y, plotBox, [firstLap, lastLap], yDomain)}
              className={i ? 'trace-b' : 'trace-a'} />)}
          </g>
          <line className="corner-cursor" x1={plotBox.x + (selectedLap - firstLap) / (lastLap - firstLap || 1) * plotBox.w}
            x2={plotBox.x + (selectedLap - firstLap) / (lastLap - firstLap || 1) * plotBox.w} y1={plotBox.y} y2={plotBox.y + plotBox.h} />
        </svg></div></div>;
    })}
    <p className="corner-axis">X is lap number; each row measures seconds on Y. Positive delta means {data.lap_times[0]?.driver} was quicker; negative means {data.lap_times[1]?.driver} was quicker. The table below gives every exact value.</p>
  </Frame>;
}
