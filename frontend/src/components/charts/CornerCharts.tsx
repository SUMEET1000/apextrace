import type { ReactNode } from 'react';
import { placeCornerMarks, type CornerMark, type Projected } from '../../lib/circuit';

type Series = (number | null)[];
type Sector = { x: number[]; y: number[]; value: number };
type Corners = { x: number[]; y: number[]; labels: string[] };

export type MapData = {
  x: number[]; y: number[]; rate?: Series; speed?: Series;
  sectors: Sector[]; corners: Corners; lo?: number; hi?: number; limit?: number;
  finding: string; x_unit: string; y_unit: string; colour_unit: string;
};
export type TraceData = {
  drivers: { name: string; distance: number[]; speed: Series; throttle: Series;
    brake: Series; gear: Series }[];
  delta: Series; finding: string; x_unit: string;
};
export type CornerBarData = {
  labels: string[]; delta_s: Series; faster: string[]; finding: string;
};
export type LapData = {
  lap_times: { driver: string; lap: number[]; time_s: Series }[];
  delta: { lap: number[]; seconds: Series };
  cumulative: { lap: number[]; seconds: Series };
  finding: string;
};

function Frame({ id, finding, children }: { id: string; finding: string; children: ReactNode }) {
  return <figure className="corner-chart"><figcaption data-finding>{finding}</figcaption>
    <div data-chart={id}>{children}</div></figure>;
}

function extent(values: Series): [number, number] {
  const finite = values.filter((v): v is number => v !== null && Number.isFinite(v));
  return finite.length ? [Math.min(...finite), Math.max(...finite)] : [0, 1];
}

export function CornerLabels({ track, corners, width, height, size = 24 }: {
  track: Projected; corners: CornerMark[]; width: number; height: number; size?: number;
}) {
  const labels = placeCornerMarks(track, corners, width, height, size);
  return <g className="circuit-labels">{labels.map((mark, i) => {
    const target = corners[i];
    const lineX = mark.x + Math.max(-size / 2, Math.min(size / 2, target.x - mark.x));
    const lineY = mark.y + Math.max(-size / 2, Math.min(size / 2, target.y - mark.y));
    return <g key={`${mark.label}-${i}`}>
      <line x1={target.x} y1={target.y} x2={lineX} y2={lineY} stroke="#131313" strokeWidth="2" />
      <rect x={mark.x - size / 2} y={mark.y - size / 2} width={size} height={size}
        fill="#E7E7E3" stroke="#131313" strokeWidth="2" />
      <text x={mark.x} y={mark.y + size * .17} textAnchor="middle"
        fontSize={size * .5} fontWeight="700" fill="#131313">{mark.label}</text>
    </g>;
  })}</g>;
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

export function MapRibbon({ data, id, label }: { data: MapData; id: string; label: string }) {
  const allX = data.x; const allY = data.y;
  const [minX, maxX] = extent(allX); const [minY, maxY] = extent(allY);
  const scale = Math.min(900 / (maxX - minX || 1), 390 / (maxY - minY || 1));
  const offsetX = (960 - (maxX - minX) * scale) / 2;
  const offsetY = (450 - (maxY - minY) * scale) / 2;
  const point = (x: number, y: number) => [offsetX + (x - minX) * scale,
    450 - offsetY - (y - minY) * scale];
  const coords = (xs: number[], ys: number[]) => xs.map((x, i) => point(x, ys[i]).map((v) => v.toFixed(1)).join(','));
  const [low, high] = data.rate ? [-(data.limit ?? 0), data.limit ?? 0]
    : [data.lo ?? 0, data.hi ?? 0];
  const swatch = (sector: Sector) => {
    if (data.rate) return sector.value > high * 0.1 ? '#F2E600'
      : sector.value < low * 0.1 ? '#E23B2E' : '#686862';
    return sector.value >= low + (high - low) * 0.66 ? '#F2E600'
      : sector.value >= low + (high - low) * 0.33 ? '#131313' : '#E23B2E';
  };
  return <Frame id={id} finding={data.finding}>
    <div className="corner-map-head"><b>{label}</b><span>{data.rate ? 'YELLOW · REFERENCE GAINS / RED · COMPARE GAINS' : `SPEED · ${data.colour_unit}`}</span></div>
    <svg viewBox="0 0 960 450" role="img" aria-label={label}>
      <polyline points={coords(allX, allY).join(' ')} fill="none" stroke="#131313" strokeWidth="16" strokeLinejoin="round" />
      {data.sectors.map((sector, i) => <polyline key={i} points={coords(sector.x, sector.y).join(' ')}
        fill="none" stroke={swatch(sector)} strokeWidth="10" strokeLinejoin="round" />)}
      <CornerLabels track={{ x: allX.map((x) => point(x, 0)[0]), y: allY.map((y) => point(0, y)[1]) }}
        corners={data.corners.x.map((x, i) => {
          const [px, py] = point(x, data.corners.y[i]);
          return { x: px, y: py, label: data.corners.labels[i] };
        })} width={960} height={450} />
    </svg>
    <p className="corner-axis">CIRCUIT COORDINATES · {data.x_unit} / {data.y_unit}</p>
  </Frame>;
}

export function TracePanel({ data }: { data: TraceData }) {
  if (data.drivers.length < 2) return null;
  const maxDistance = Math.max(...data.drivers.flatMap((d) => d.distance));
  const rows: { key: 'speed' | 'throttle' | 'brake' | 'gear'; label: string; unit: string; stepped: boolean }[] = [
    { key: 'speed', label: 'SPEED', unit: 'km/h', stepped: false },
    { key: 'throttle', label: 'THROTTLE', unit: '%', stepped: false },
    { key: 'brake', label: 'BRAKE', unit: 'on / off', stepped: true },
    { key: 'gear', label: 'GEAR', unit: 'gear', stepped: true },
  ];
  const allDelta = extent(data.delta);
  return <Frame id="trace-panel" finding={data.finding}>
    <div className="corner-chart-legend"><span>━ {data.drivers[0].name}</span><span>┄ {data.drivers[1].name}</span></div>
    {rows.map((row) => {
      const limits = extent(data.drivers.flatMap((d) => d[row.key]));
      const domain: [number, number] = row.key === 'brake' ? [0, 1] : row.key === 'throttle' ? [0, 100]
        : [Math.min(0, limits[0]), limits[1] || 1];
      return <div className="corner-trace-row" key={row.key}><span>{row.label}<small>{row.unit}</small></span>
        <svg viewBox="0 0 800 96" preserveAspectRatio="none" aria-label={`${row.label} against lap distance`}>
          <path d={line(data.drivers[0].distance, data.drivers[0][row.key], { x: 0, y: 7, w: 800, h: 80 }, [0, maxDistance], domain, row.stepped)} className="trace-a" />
          <path d={line(data.drivers[1].distance, data.drivers[1][row.key], { x: 0, y: 7, w: 800, h: 80 }, [0, maxDistance], domain, row.stepped)} className="trace-b" />
        </svg></div>;
    })}
    <div className="corner-trace-row"><span>DELTA<small>s</small></span>
      <svg viewBox="0 0 800 96" preserveAspectRatio="none" aria-label="Time delta in seconds">
        <path d={line(data.drivers[0].distance, data.delta, { x: 0, y: 7, w: 800, h: 80 }, [0, maxDistance], allDelta)} className="trace-a" />
      </svg></div>
    <p className="corner-axis">LAP DISTANCE · {data.x_unit}</p>
  </Frame>;
}

export function CornerBars({ data }: { data: CornerBarData }) {
  const max = Math.max(0.001, ...data.delta_s.map((v) => Math.abs(v ?? 0)));
  return <Frame id="corner-delta-bars" finding={data.finding}>
    <div className="corner-bars" role="img" aria-label="Time gained or lost by segment in seconds">
      {data.labels.map((label, i) => {
        const value = data.delta_s[i];
        return <div className="corner-bar" key={`${label}-${i}`}><span>{label}</span>
          <div className="corner-bar-track"><div style={{ width: `${Math.abs(value ?? 0) / max * 50}%`,
            left: value !== null && value < 0 ? `${50 - Math.abs(value) / max * 50}%` : '50%',
            background: value !== null && value < 0 ? '#E23B2E' : '#131313' }} /></div>
          <strong>{value === null ? '—' : `${value >= 0 ? '+' : ''}${value.toFixed(3)} s`}</strong></div>;
      })}
    </div>
    <p className="corner-axis">LEFT: COMPARE GAINS / RIGHT: REFERENCE GAINS · s</p>
  </Frame>;
}

export function LapChart({ data }: { data: LapData }) {
  const rows = [
    { label: 'LAP TIME', unit: 's', series: data.lap_times.map((r) => ({ x: r.lap, y: r.time_s, name: r.driver })) },
    { label: 'LAP DELTA', unit: 's', series: [{ x: data.delta.lap, y: data.delta.seconds, name: 'Delta' }] },
    { label: 'RUNNING GAP', unit: 's', series: [{ x: data.cumulative.lap, y: data.cumulative.seconds, name: 'Cumulative' }] },
  ].filter((row) => row.series.some((series) => series.y.some((value) => value !== null && Number.isFinite(value))));
  return <Frame id="lap-by-lap" finding={data.finding}>
    {rows.map((row) => {
      const xs = row.series.flatMap((s) => s.x);
      const xDomain = extent(xs); const yDomain = extent(row.series.flatMap((s) => s.y));
      return <div className="corner-trace-row" key={row.label}><span>{row.label}<small>{row.unit}</small></span>
        <svg viewBox="0 0 800 116" preserveAspectRatio="none" aria-label={`${row.label} by lap`}>
          {row.series.map((series, i) => <path key={series.name}
            d={line(series.x, series.y, { x: 0, y: 8, w: 800, h: 99 }, xDomain, yDomain)}
            className={i ? 'trace-b' : 'trace-a'} />)}
        </svg></div>;
    })}
    <p className="corner-axis">LAP NUMBER · lap</p>
  </Frame>;
}
