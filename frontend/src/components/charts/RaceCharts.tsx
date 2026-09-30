import { useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { ErrorState, Loading } from '../states';
import { fetchChartData, useAsync } from '../../lib/api';
import { fmt } from '../../lib/format';
import facts from '../../landing/facts.json';

gsap.registerPlugin(ScrollTrigger);

type Values = (number | null)[];
type ChartId = 'degradation-scatter' | 'degradation-bars' | 'session-best' | 'evolution-curve'
  | 'evolution-temperature' | 'stint-chart' | 'race-pace-box' | 'gap-chart'
  | 'position-chart' | 'undercut-chart';
const CHART_GUIDES: Record<ChartId, string> = {
  'degradation-scatter': 'Each dot is one clean lap after fuel correction. The black line pools stint fits by inverse variance. A steeper upward line means more lap time lost as the tyre ages; compare slopes, not the raw height of different compounds.',
  'degradation-bars': 'Each bar starts at zero and shows the estimated lap-time change for one additional lap of tyre age. Positive rates mean wear. Whiskers mark the 95% confidence interval.',
  'session-best': 'Dots are recorded timed laps; the black line is the quickest lap seen up to that point. It describes the session best and does not separate track change from tyres or fuel.',
  'evolution-curve': 'The black line estimates lap-time change relative to the first fitted point after fuel correction and adjustment for driver, tyre compound and tyre age. Below zero means faster. The red dashed line joins binned median fuel-corrected laps; it still mixes those drivers and tyres.',
  'evolution-temperature': 'The upper panel is the adjusted track estimate; the lower panel is recorded track temperature at the same session progress. Their vertical scales are separate, and similar shapes alone do not establish that temperature caused the pace change.',
  'stint-chart': 'One row per driver. Each coloured block runs from the first to the last recorded lap of a tyre stint; the colour names the compound. A block does not mean every lap inside it passed the pace filter.',
  'race-pace-box': 'Each row summarizes a driver’s clean, fuel-corrected lap times. Farther left means quicker laps. The yellow box contains the middle half; the red mark is the median, whiskers reach values within 1.5 × IQR, and red dots are outliers.',
  'gap-chart': 'Each line is the recorded time behind the race leader at that lap. Zero is the leader; a line moving down means the driver fell farther behind. The graph shows gaps, not the cause of a sudden change.',
  'position-chart': 'Each line is a driver’s recorded running place. P1 is the leader at the top; a line moving up gains places. Crossings show changes between recorded laps, not the exact point of an overtake.',
  'undercut-chart': 'The black line is the modelled cumulative gain after a fresh-tyre stop. The red dashed line is the gap to close. A crossing predicts breakeven under the selected assumptions, not an observed race result.',
};
type Base = { finding: string };
type Panel = { compound: string; age: number[]; lap_time_s: Values;
  fit: { age: number[]; lap_time_s: Values; slope_s_per_lap: number } | null };
type Evolution = Base & { progress: number[]; evolution_s: Values; lower: Values; upper: Values;
  naive: { progress: number[]; evolution_s: Values } | null;
  temperature?: { progress: number[]; celsius: Values } | null };
type Series = { driver: string; lap: number[]; gap_s?: Values; position?: Values };
type Stint = { driver: string; compound: string; start_lap: number; end_lap: number };
type Box = { driver: string; q1: number | null; median: number | null; q3: number | null;
  lo: number | null; hi: number | null; outliers: number[] };

const INK = '#131313';
const RED = '#E23B2E';
const COMPOUND_COLOURS: Record<string, string> = { ...facts.compound_colours,
  MEDIUM: '#946B00', HARD: '#5A6875', INTERMEDIATE: '#267F42' };
const DRIVER_COLOURS = [INK, RED, '#493D97', '#267F42', '#A85216', '#19728A', '#77518A', '#7B5B12',
  '#007ACC', '#B51D83', '#5D721B', '#C65B7C', '#00847E', '#88562C', '#5F69BE', '#B57B08',
  '#846A9A', '#5A6875', '#63344D', '#377EAA', '#696A2C', '#C14464'];
const WIDTH = 900;

function finite(values: Values): number[] {
  return values.filter((value): value is number => value !== null && Number.isFinite(value));
}

function extent(values: Values, pad = .06): [number, number] {
  const all = finite(values);
  if (!all.length) return [0, 1];
  const min = Math.min(...all); const max = Math.max(...all);
  const spread = max - min || Math.max(Math.abs(max) * .1, 1);
  return [min - spread * pad, max + spread * pad];
}

function path(x: number[], y: Values, px: (value: number) => number, py: (value: number) => number): string {
  let open = false;
  return x.map((value, index) => {
    const sample = y[index];
    if (!Number.isFinite(value) || sample === null || sample === undefined || !Number.isFinite(sample)) {
      open = false; return '';
    }
    const segment = `${open ? 'L' : 'M'}${px(value).toFixed(2)},${py(sample).toFixed(2)}`;
    open = true;
    return segment;
  }).join('');
}

function band(x: number[], low: Values, high: Values,
              px: (value: number) => number, py: (value: number) => number): string[] {
  const shapes: string[] = [];
  let points: [number, number, number][] = [];
  const flush = () => {
    if (points.length > 1) {
      shapes.push(`M${points.map(([a, b]) => `${a},${b}`).join('L')}L${[...points].reverse()
        .map(([a, , c]) => `${a},${c}`).join('L')}Z`);
    }
    points = [];
  };
  x.forEach((value, index) => {
    const a = low[index]; const b = high[index];
    if (!Number.isFinite(value) || a === null || b === null || a === undefined || b === undefined
      || !Number.isFinite(a) || !Number.isFinite(b)) { flush(); return; }
    points.push([px(value), py(a), py(b)]);
  });
  flush();
  return shapes;
}

type Line = { x: number[]; y: Values; label: string; colour?: string; dash?: string;
  width?: number; endLabel?: boolean };
type PlotProps = { lines: Line[]; xUnit: string; yUnit: string; height?: number; reverseY?: boolean;
  dots?: Line[]; interval?: { x: number[]; low: Values; high: Values }; limitY?: [number, number];
  yTicks?: number[];
  children?: (scale: { x: (n: number) => number; y: (n: number) => number;
    left: number; right: number; top: number; bottom: number }) => ReactNode };

function Plot({ lines, xUnit, yUnit, height = 300, reverseY = false, dots = [], interval,
                limitY, yTicks, children }: PlotProps) {
  const drawId = useId().replaceAll(':', '');
  const left = 72; const right = WIDTH - (lines.some((line) => line.endLabel) ? 60 : 24);
  const top = 34; const bottom = height - 65;
  const xs = [...lines, ...dots].flatMap((row) => row.x).concat(interval?.x ?? []);
  const ys = [...lines, ...dots].flatMap((row) => row.y).concat(interval?.low ?? [], interval?.high ?? []);
  const [xMin, xMax] = extent(xs, 0);
  const [yMin, yMax] = limitY ?? extent(ys);
  const x = (value: number) => left + (value - xMin) / (xMax - xMin || 1) * (right - left);
  const y = (value: number) => reverseY
    ? top + (value - yMin) / (yMax - yMin || 1) * (bottom - top)
    : bottom - (value - yMin) / (yMax - yMin || 1) * (bottom - top);
  const ticks = [0, .5, 1];
  const defaultYTicks = ticks.map((fraction) => yMin + (yMax - yMin) * fraction);
  const yTickValues = yTicks ?? (yMin < 0 && yMax > 0 && !defaultYTicks.some((value) => Math.abs(value) < .00001)
    ? [...defaultYTicks, 0].sort((a, b) => a - b) : defaultYTicks);
  return <div className="race-plot-scroll"><svg viewBox={`0 0 ${WIDTH} ${height}`} role="img"
    aria-label={`${yUnit} against ${xUnit}`} className="race-plot">
    <defs><clipPath id={drawId}><rect data-race-draw x={left} y="0" width={right - left} height={height} /></clipPath></defs>
    <g className="race-axes">
      {yTickValues.map((value) => {
        return <g key={value}><line className={Math.abs(value) < .00001 ? 'race-zero-guide' : undefined}
          x1={left} x2={right} y1={y(value)} y2={y(value)} />
          <text x={left - 9} y={y(value) + 4} textAnchor="end">{yTicks ? `P${value}` : fmt(value, 1)}</text></g>;
      })}
      <line className="race-axis-edge" x1={left} x2={right} y1={bottom} y2={bottom} />
      {ticks.map((fraction) => {
        const value = xMin + (xMax - xMin) * fraction;
        return <text key={fraction} x={x(value)} y={bottom + 20} textAnchor="middle">
          {fmt(value, xUnit === 'session progress (%)' ? 0 : xUnit.includes('lap') ? 0 : 1)}</text>;
      })}
      <text x={left} y={20} className="race-axis-title">{yUnit}</text>
      <text x={(left + right) / 2} y={height - 12} textAnchor="middle" className="race-axis-title">{xUnit}</text>
    </g>
    {interval && band(interval.x, interval.low, interval.high, x, y).map((shape, index) =>
      <path key={index} d={shape} className="race-interval" clipPath={`url(#${drawId})`} />)}
    {lines.map((line, index) => <path key={`${line.label}-${index}`} d={path(line.x, line.y, x, y)}
      fill="none" stroke={line.colour ?? DRIVER_COLOURS[index % DRIVER_COLOURS.length]}
      strokeWidth={line.width ?? 3}
      strokeDasharray={line.dash} vectorEffect="non-scaling-stroke"
      clipPath={`url(#${drawId})`} />)}
    {lines.filter((line) => line.endLabel).map((line) => {
      const last = line.y.reduce<number>((found, value, index) => value !== null && Number.isFinite(value)
        ? index : found, -1);
      if (last < 0 || !Number.isFinite(line.x[last])) return null;
      return <text key={line.label} x={x(line.x[last]) + 6} y={y(line.y[last] as number) + 4}
        className="race-line-end" style={{ fill: line.colour ?? INK }}>{line.label}</text>;
    })}
    {dots.flatMap((line, row) => line.x.map((value, index) => {
      const sample = line.y[index];
      return sample === null || sample === undefined || !Number.isFinite(sample) ? null
        : <circle key={`${row}-${index}`} cx={x(value)} cy={y(sample)} r="2.4"
            fill={line.colour ?? INK} opacity=".9" clipPath={`url(#${drawId})`} />;
    }))}
    {children?.({ x, y, left, right, top, bottom })}
  </svg></div>;
}

function Legend({ rows }: { rows: { label: string; colour: string; dash?: string; band?: boolean }[] }) {
  return <div className="race-legend">{rows.map((row) => <span key={row.label}>
    {row.band ? <i className="race-legend-band" style={{ background: row.colour }} />
      : <svg viewBox="0 0 25 8" aria-hidden="true"><line x1="0" x2="25" y1="4" y2="4"
          stroke={row.colour} strokeWidth="4" strokeDasharray={row.dash} /></svg>}{row.label}
  </span>)}</div>;
}

function DegradationScatter({ data }: { data: Base & { panels: Panel[] } }) {
  return <div><div className="race-legend"><span><i style={{ borderColor: INK }} />Pooled stint fit</span>
    <span><b className="race-dot-key" />Clean laps (panel tyre colour)</span></div>{data.panels.map((panel) => {
    const colour = COMPOUND_COLOURS[panel.compound] ?? INK;
    return <div key={panel.compound} className="race-panel"><h3>{panel.compound} · {panel.fit
      ? `${fmt(panel.fit.slope_s_per_lap)} s/lap` : 'no fitted slope'}</h3>
      <Plot xUnit="tyre age (laps)" yUnit="fuel-corrected lap time (s)" height={260}
        lines={panel.fit ? [{ x: panel.fit.age, y: panel.fit.lap_time_s, label: 'Pooled fit', colour: INK }] : []}
        dots={[{ x: panel.age, y: panel.lap_time_s, label: 'Clean laps', colour }]} />
    </div>;
  })}</div>;
}

function DegradationBars({ data }: { data: Base & { compounds: string[]; rate: Values;
  lower: Values; upper: Values; n_stints: number[] } }) {
  const height = Math.max(150, data.compounds.length * 70 + 80);
  const [low, high] = extent([...data.lower, ...data.upper, 0]);
  const x = (value: number) => 180 + (value - low) / (high - low || 1) * 600;
  return <div className="race-plot-scroll"><svg viewBox={`0 0 900 ${height}`} className="race-plot"
    role="img" aria-label="Pooled tyre degradation rate and 95% confidence interval, seconds per lap">
    <text x="180" y="22" className="race-axis-title">RATE · s/lap · WHISKERS = 95% CI</text>
    {data.compounds.map((name, index) => {
      const rate = data.rate[index]; const lower = data.lower[index]; const upper = data.upper[index];
      if (rate === null || lower === null || upper === null) return null;
      const cy = 55 + index * 70;
      return <g key={name}><text x="12" y={cy + 4}>{name} · {data.n_stints[index]} stints</text>
        <rect data-race-grow data-grow-origin={rate < 0 ? 'right' : 'left'}
          x={x(Math.min(0, rate))} y={cy - 11} width={Math.abs(x(rate) - x(0))} height="22"
          fill={COMPOUND_COLOURS[name] ?? INK} stroke={INK} />
        <line x1={x(lower)} x2={x(upper)} y1={cy} y2={cy} stroke={INK} strokeWidth="3" />
        <line x1={x(lower)} x2={x(lower)} y1={cy - 14} y2={cy + 14} stroke={INK} strokeWidth="2" />
        <line x1={x(upper)} x2={x(upper)} y1={cy - 14} y2={cy + 14} stroke={INK} strokeWidth="2" />
        <text x="795" y={cy + 4}>{fmt(rate)} s/lap</text>
      </g>;
    })}
    <line x1={x(0)} x2={x(0)} y1="38" y2={height - 40} className="race-zero-guide" />
    <text x={x(0)} y={height - 30} textAnchor="middle">0 s/lap</text>
    <text x="470" y={height - 10} textAnchor="middle" className="race-axis-title">DEGRADATION RATE (s/lap)</text>
  </svg></div>;
}

function EvolutionPlot({ data, temperature = false }: { data: Evolution; temperature?: boolean }) {
  const pct = data.progress.map((value) => value * 100);
  const lines: Line[] = [{ x: pct, y: data.evolution_s, label: 'Adjusted track change', colour: INK }];
  if (data.naive) lines.push({ x: data.naive.progress.map((value) => value * 100),
    y: data.naive.evolution_s, label: 'Fuel-corrected lap trend', colour: RED, dash: '8 6' });
  return <div><Legend rows={[...lines.map((line) => ({ label: line.label, colour: line.colour ?? INK,
    dash: line.dash })), { label: '95% confidence band', colour: '#F2E600', band: true }]} />
    <Plot lines={lines} xUnit="session progress (%)" yUnit="lap-time change vs first fitted point (s)"
      interval={{ x: pct, low: data.lower, high: data.upper }} />
    <p className="race-chart-note">The fitted range may start after 0% when earlier timed laps were not usable.</p>
    {temperature && data.temperature && <div className="race-panel"><h3>TRACK TEMPERATURE</h3>
      <Plot lines={[{ x: data.temperature.progress.map((value) => value * 100),
        y: data.temperature.celsius, label: 'Track temperature', colour: '#E66A22' }]}
        xUnit="session progress (%)" yUnit="recorded track temperature (°C)" height={220} /></div>}
  </div>;
}

function StintTimeline({ data }: { data: Base & { order: string[]; stints: Stint[] } }) {
  const height = Math.max(140, data.order.length * 29 + 60);
  const maxLap = Math.max(1, ...data.stints.map((row) => row.end_lap));
  const x = (lap: number) => 80 + (lap - 1) / Math.max(1, maxLap - 1) * 780;
  return <div className="race-plot-scroll"><svg viewBox={`0 0 900 ${height}`} className="race-plot"
    role="img" aria-label="Tyre compound stints by driver and lap">
    {data.order.map((driver, index) => <g key={driver}><text x="12" y={36 + index * 29}>{driver}</text>
      <line x1="80" x2="860" y1={32 + index * 29} y2={32 + index * 29} className="race-row-line" /></g>)}
    {data.stints.map((row, index) => {
      const position = data.order.indexOf(row.driver);
      if (position < 0) return null;
      return <rect key={index} data-race-grow x={x(row.start_lap)} y={22 + position * 29}
        width={Math.max(3, x(row.end_lap) - x(row.start_lap) + 2)} height="20"
        fill={COMPOUND_COLOURS[row.compound] ?? '#888'}
        stroke={INK}><title>{row.driver} · {row.compound} · laps {row.start_lap}–{row.end_lap}</title></rect>;
    })}
    <text x="80" y={height - 9}>L1</text><text x="860" y={height - 9} textAnchor="end">L{maxLap}</text>
    <text x="470" y={height - 9} textAnchor="middle" className="race-axis-title">LAP NUMBER</text>
  </svg><div className="race-compound-key">{[...new Set(data.stints.map((row) => row.compound))].map((compound) =>
    <span key={compound}><i style={{ background: COMPOUND_COLOURS[compound] ?? '#888' }} />{compound}</span>)}</div></div>;
}

function PaceBoxes({ data }: { data: Base & { order: string[]; boxes: Box[] } }) {
  const rows = data.order.map((driver) => data.boxes.find((box) => box.driver === driver)).filter((box): box is Box => !!box);
  const values = rows.flatMap((box) => [box.lo, box.q1, box.median, box.q3, box.hi, ...box.outliers]);
  const [min, max] = extent(values);
  const x = (value: number) => 90 + (value - min) / (max - min || 1) * 760;
  const height = Math.max(150, rows.length * 30 + 62);
  return <div className="race-plot-scroll"><svg viewBox={`0 0 900 ${height}`} className="race-plot"
    role="img" aria-label="Fuel-corrected lap time box statistics by driver, seconds">
    {rows.map((box, index) => {
      if (box.lo === null || box.q1 === null || box.median === null || box.q3 === null || box.hi === null) return null;
      const cy = 31 + index * 30;
      return <g key={box.driver}><text x="12" y={cy + 4}>{box.driver}</text>
        <line x1={x(box.lo)} x2={x(box.hi)} y1={cy} y2={cy} stroke={INK} strokeWidth="2" />
        <line x1={x(box.lo)} x2={x(box.lo)} y1={cy - 8} y2={cy + 8} stroke={INK} />
        <line x1={x(box.hi)} x2={x(box.hi)} y1={cy - 8} y2={cy + 8} stroke={INK} />
        <rect data-race-grow x={x(box.q1)} y={cy - 10} width={Math.max(2, x(box.q3) - x(box.q1))} height="20"
          fill="#F2E600" stroke={INK} strokeWidth="2" />
        <line x1={x(box.median)} x2={x(box.median)} y1={cy - 10} y2={cy + 10} stroke={RED} strokeWidth="3" />
        {box.outliers.map((value, outlier) => <circle key={outlier} cx={x(value)} cy={cy} r="3" fill={RED} />)}
      </g>;
    })}
    <text x="90" y={height - 12}>{fmt(min, 1)} s</text>
    <text x="850" y={height - 12} textAnchor="end">{fmt(max, 1)} s</text>
    <text x="470" y={height - 12} textAnchor="middle" className="race-axis-title">FUEL-CORRECTED LAP TIME (s)</text>
  </svg></div>;
}

function DriverLines({ data, kind }: { data: Base & { series: Series[] }; kind: 'gap' | 'position' }) {
  const [first, setFirst] = useState(data.series[0]?.driver ?? '');
  const [second, setSecond] = useState(data.series[1]?.driver ?? '');
  const [comparing, setComparing] = useState(false);
  if (!data.series.length) return <p className="race-empty-chart">No recorded {kind} series for this selection.</p>;
  const lines = data.series.map((row, index) => ({ x: row.lap,
    y: kind === 'gap' ? row.gap_s ?? [] : row.position ?? [], label: row.driver,
    colour: DRIVER_COLOURS[index % DRIVER_COLOURS.length],
    dash: kind === 'position' ? undefined : [undefined, '8 6', '2 5'][Math.floor(index / 8) % 3] }));
  if (kind === 'position') {
    const positions = data.series.flatMap((row) => finite(row.position ?? []));
    const count = Math.max(1, Math.ceil(Math.max(...positions)));
    const ticks = Array.from({ length: count }, (_, index) => index + 1);
    const highlighted: Line[] = [first, second].filter(Boolean).map((driver, index) => {
      const line = lines.find((item) => item.label === driver)!;
      return { ...line, colour: index === 0 ? INK : RED, dash: undefined, width: 4, endLabel: true };
    });
    return <div><div className="corner-switch" role="group" aria-label="Position chart mode">
      <button type="button" aria-pressed={!comparing} onClick={() => setComparing(false)}>ALL DRIVERS</button>
      <button type="button" aria-pressed={comparing} onClick={() => setComparing(true)}>COMPARE TWO DRIVERS</button>
    </div>{comparing ? <div className="race-position-compare">
      <label><span>FOLLOW</span><select value={first} onChange={(event) => setFirst(event.target.value)}>
        {data.series.map((row) => <option key={row.driver} value={row.driver} disabled={row.driver === second}>{row.driver}</option>)}
      </select></label>
      {second && <label><span>COMPARE</span><select value={second} onChange={(event) => setSecond(event.target.value)}>
        {data.series.map((row) => <option key={row.driver} value={row.driver} disabled={row.driver === first}>{row.driver}</option>)}
      </select></label>}
      <span className="race-position-hint">Only the selected drivers are shown. Black and red lines are labelled at their last recorded lap.</span>
    </div> : <Legend rows={lines} />}<Plot lines={comparing ? highlighted : lines} xUnit="lap number" yUnit="running race position"
      reverseY limitY={[1, count]} yTicks={ticks} height={Math.max(300, count * 22 + 80)} />
      <p className="race-chart-note">Missing positions leave gaps in a line.</p></div>;
  }
  const largestGap = Math.max(1, ...lines.flatMap((line) => finite(line.y)));
  return <div><Legend rows={lines} /><Plot lines={lines} xUnit="lap number"
    yUnit="time behind race leader (s)" reverseY limitY={[0, largestGap]} />
    <p className="race-chart-note">Gaps use the recorded time behind the leader, not a sum of only matched driver laps.</p></div>;
}

function UndercutPlot({ data }: { data: Base & { laps: number[]; gain_s: Values; gap_s: number } }) {
  const threshold = data.laps.map(() => data.gap_s);
  return <div><Legend rows={[{ label: 'Cumulative fresh-tyre gain', colour: INK },
    { label: `Initial gap · ${fmt(data.gap_s, 1)} s`, colour: RED, dash: '8 6' }]} />
    <Plot lines={[{ x: data.laps, y: data.gain_s, label: 'Gain', colour: INK },
      { x: data.laps, y: threshold, label: 'Gap', colour: RED, dash: '8 6' }]}
      xUnit="laps after stop" yUnit="cumulative fresh-tyre gain (s)" />
  </div>;
}

function render(id: ChartId, value: Base): ReactNode {
  switch (id) {
    case 'degradation-scatter': return <DegradationScatter data={value as Base & { panels: Panel[] }} />;
    case 'degradation-bars': return <DegradationBars data={value as Base & { compounds: string[];
      rate: Values; lower: Values; upper: Values; n_stints: number[] }} />;
    case 'session-best': {
      const data = value as Base & { minutes: number[]; best_s: Values; lap_time_s: Values };
      return <Plot lines={[{ x: data.minutes, y: data.best_s, label: 'Session best', colour: INK }]}
        dots={[{ x: data.minutes, y: data.lap_time_s, label: 'Timed laps', colour: RED }]}
        xUnit="session time (min)" yUnit="lap time (s)" />;
    }
    case 'evolution-curve': return <EvolutionPlot data={value as Evolution} />;
    case 'evolution-temperature': return <EvolutionPlot data={value as Evolution} temperature />;
    case 'stint-chart': return <StintTimeline data={value as Base & { order: string[]; stints: Stint[] }} />;
    case 'race-pace-box': return <PaceBoxes data={value as Base & { order: string[]; boxes: Box[] }} />;
    case 'gap-chart': return <DriverLines data={value as Base & { series: Series[] }} kind="gap" />;
    case 'position-chart': return <DriverLines data={value as Base & { series: Series[] }} kind="position" />;
    case 'undercut-chart': return <UndercutPlot data={value as Base & { laps: number[]; gain_s: Values; gap_s: number }} />;
  }
}

export function RaceChart({ id, params, title }: { id: ChartId;
  params: Record<string, string | number>; title: string }) {
  const frame = useRef<HTMLElement>(null);
  const key = JSON.stringify(params);
  const state = useAsync((signal) => fetchChartData<Base>(id, params, signal), [id, key]);
  const chartId = useId();
  useLayoutEffect(() => {
    const node = frame.current;
    if (!node || !state.data) return;
    const media = gsap.matchMedia();
    media.add('(prefers-reduced-motion: no-preference)', () => {
      const context = gsap.context(() => {
        const below = node.getBoundingClientRect().top >= innerHeight * .88;
        const entrance = gsap.fromTo(node, { y: 18, opacity: .45 },
          { y: 0, opacity: 1, duration: .65, ease: 'power3.out', paused: below });
        if (below) ScrollTrigger.create({ trigger: node, start: 'top 88%', once: true,
          onEnter: () => entrance.play() });
        node.querySelectorAll<SVGSVGElement>('svg.race-plot').forEach((svg) => {
          const draw = svg.querySelector<SVGRectElement>('[data-race-draw]');
          const bars = [...svg.querySelectorAll<SVGRectElement>('[data-race-grow]')];
          if (!draw && !bars.length) return;
          const fullWidth = draw ? Number(draw.getAttribute('width')) : 0;
          if (draw) gsap.set(draw, { attr: { width: 0 } });
          bars.forEach((bar) => gsap.set(bar, { scaleX: 0,
            transformOrigin: bar.dataset.growOrigin === 'right' ? '100% 50%' : '0% 50%' }));
          const delayed = svg.getBoundingClientRect().top >= innerHeight * .88;
          const timeline = gsap.timeline({ paused: delayed });
          if (draw) timeline.to(draw, { attr: { width: fullWidth },
            duration: .85, ease: 'power2.inOut' }, 0);
          if (bars.length) timeline.to(bars, { scaleX: 1, duration: .72, ease: 'power2.out',
            stagger: { amount: Math.min(.55, bars.length * .025) } }, 0);
          if (delayed) ScrollTrigger.create({ trigger: svg, start: 'top 88%', once: true,
            onEnter: () => timeline.play() });
        });
      }, node);
      return () => context.revert();
    });
    return () => media.revert();
  }, [state.data]);
  if (state.error) return <ErrorState message={state.error} onRetry={state.retry} />;
  if (!state.data) return <Loading what={title.toLowerCase()} />;
  const withSeries = state.data as Base & { series?: Series[] };
  const finding = /\d/.test(state.data.finding) ? state.data.finding
    : `${state.data.finding} ${withSeries.series?.length ?? 0} driver series shown.`;
  return <figure className="corner-chart race-chart" aria-labelledby={chartId} ref={frame}>
    <figcaption id={chartId}><span className="race-chart-title">{title}</span>
      <span data-finding>{finding}</span><p className="race-chart-explain">{CHART_GUIDES[id]}</p></figcaption>
    <div data-chart={id}>{render(id, state.data)}</div>
  </figure>;
}
