import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { CornerBars, LapChart, MapRibbon, SectorCircuit, TracePanel,
  type CornerBarData, type LapData, type MapData, type TraceData } from '../../components/charts/CornerCharts';
import { Empty, ErrorState, Loading } from '../../components/states';
import { Term } from '../../components/Term';
import { fetchChartData, fetchCornerAnalysis, fetchSession, useAsync } from '../../lib/api';
import { fmt, fmtDelta, fmtLaptime } from '../../lib/format';
import { project } from '../../lib/circuit';
import { useQueryParams } from '../../lib/router';
import type { CornerAnalysisResponse, DriverLap, ManifestSession, SessionResponse } from '../../lib/types';
import { Replay } from './Replay';
import './corner.css';

gsap.registerPlugin(ScrollTrigger);

type Choice = { slug: string; meta: ManifestSession };

function driverLabel(data: SessionResponse, code: string): string {
  const name = data.results.find((row) => row.Abbreviation === code)?.FullName;
  return typeof name === 'string' && name ? `${name} (${code})` : code;
}

function driverSurname(data: SessionResponse, code: string): string {
  const name = data.results.find((row) => row.Abbreviation === code)?.FullName;
  return typeof name === 'string' && name ? name.split(' ').at(-1) ?? code : code;
}

function ScrollNumber({ value, format }: { value: number | null; format: (value: number) => string }) {
  const display = useRef<HTMLSpanElement>(null);
  const final = value === null || !Number.isFinite(value) ? '—' : format(value);
  useLayoutEffect(() => {
    const node = display.current;
    if (!node || value === null || !Number.isFinite(value)) return;
    const media = gsap.matchMedia();
    media.add('(prefers-reduced-motion: no-preference)', () => {
      const show = (progress: number) => { node.textContent = format(value * progress); };
      show(0);
      const below = node.getBoundingClientRect().top >= innerHeight * .85;
      const state = { progress: 0 };
      const tween = gsap.to(state, { progress: 1, duration: 1.05, ease: 'power2.out',
        onUpdate: () => show(state.progress), paused: below });
      const trigger = below ? ScrollTrigger.create({ trigger: node, start: 'top 88%', once: true,
        onEnter: () => tween.play() }) : null;
      return () => { trigger?.kill(); tween.kill(); node.textContent = final; };
    });
    return () => media.revert();
  }, [value, final]);
  return <span className="corner-number"><span className="sr">{final}</span><span aria-hidden="true" ref={display}>{final}</span></span>;
}

function ScrollProgress({ page }: { page: React.RefObject<HTMLElement | null> }) {
  const bar = useRef<HTMLDivElement>(null);
  const fill = useRef<HTMLElement>(null);
  useEffect(() => {
    const root = page.current;
    const track = bar.current;
    const line = fill.current;
    if (!root || !track || !line) return;
    const update = () => {
      const max = Math.max(1, document.documentElement.scrollHeight - innerHeight);
      line.style.width = `${Math.min(100, scrollY / max * 100)}%`;
    };
    const place = () => {
      const max = Math.max(1, document.documentElement.scrollHeight - innerHeight);
      track.querySelectorAll('u').forEach((tick) => tick.remove());
      const sections = [root.querySelector('.corner-verdict'), ...root.querySelectorAll('.corner-section')];
      sections.forEach((section, index) => {
        if (!section) return;
        const tick = document.createElement('u');
        const label = document.createElement('b');
        label.textContent = index === 0 ? 'ANSWER' : section.querySelector('.corner-section-title span')?.textContent?.replace(/^\d+ \/ /, '') ?? '';
        tick.style.left = `${Math.min(100, (section.getBoundingClientRect().top + scrollY) / max * 100)}%`;
        tick.append(label);
        track.append(tick);
      });
      update();
    };
    const observer = new ResizeObserver(place);
    observer.observe(root);
    window.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', place);
    place();
    return () => {
      observer.disconnect();
      window.removeEventListener('scroll', update);
      window.removeEventListener('resize', place);
    };
  }, [page]);
  return <div className="corner-progress" aria-hidden="true" ref={bar}><i ref={fill} /></div>;
}

export function CornerPage({ sessions, years, openerSlug }: {
  sessions: ManifestSession[]; years: number[]; openerSlug?: string | null;
}) {
  const page = useRef<HTMLElement>(null);
  const { params, update } = useQueryParams();
  const opener = sessions.find((s) => s.slug === openerSlug);
  const wantYear = Number(params.get('year'));
  const year = years.includes(wantYear) ? wantYear : opener?.year ?? years[0];
  const events = useMemo(() => {
    const seen = new Map<number, string>();
    sessions.filter((s) => s.year === year).forEach((s) => seen.set(s.round, s.event_name));
    return [...seen].sort((a, b) => a[0] - b[0]);
  }, [sessions, year]);
  const wantRound = Number(params.get('round'));
  const round = events.some(([r]) => r === wantRound) ? wantRound
    : opener?.year === year && events.some(([r]) => r === opener.round) ? opener.round : events[0]?.[0];
  const available = sessions.filter((s) => s.year === year && s.round === round);
  const wantedSession = params.get('session');
  const chosen = available.find((s) => s.session === wantedSession)
    ?? available.find((s) => s.slug === openerSlug) ?? available[0];
  const choice: Choice | null = chosen ? { slug: chosen.slug, meta: chosen } : null;
  useEffect(() => {
    if (choice) update({ year: String(year), round: String(round), session: choice.meta.session });
  }, [choice?.slug, year, round, update]);
  useLayoutEffect(() => {
    if (!page.current || !choice) return;
    const media = gsap.matchMedia();
    media.add('(prefers-reduced-motion: no-preference)', () => {
      const context = gsap.context(() => {
        gsap.timeline({ defaults: { ease: 'power3.out' } })
          .from('.corner-mast', { y: -12, autoAlpha: 0, duration: .5 })
          .from('.corner-title > div:first-child > .lab', { y: 14, autoAlpha: 0, duration: .45 }, .12)
          .from('.corner-title h1', { y: 40, autoAlpha: 0, duration: .85 }, .2)
          .from('.corner-title p', { y: 16, autoAlpha: 0, duration: .55 }, .48)
          .from('.corner-title-stamp', { y: 24, autoAlpha: 0, duration: .7 }, .32);
        gsap.fromTo('.corner-picker:not(.corner-picker-laps)', { y: 20, autoAlpha: 0 },
          { y: 0, autoAlpha: 1, duration: .7, delay: .55, ease: 'power3.out',
            scrollTrigger: { trigger: '.corner-picker:not(.corner-picker-laps)', start: 'top 90%', once: true } });
      }, page);
      return () => context.revert();
    });
    return () => media.revert();
  }, [Boolean(choice)]);
  if (!choice) return <Empty>Nothing to show for this session.</Empty>;

  return <article className="corner-page" data-slug={choice.slug} ref={page}>
    <ScrollProgress page={page} />
    <div className="corner-mast"><span className="lab">APEXTRACE / ANALYSIS 01</span>
      <span className="lab">REAL TIMING DATA · {choice.meta.year}</span></div>
    <div className="corner-title"><div><span className="lab">{choice.meta.event_name} · {choice.meta.session}</span>
      <h1 className="k">WHERE THE TIME<br /><em>CHANGES HANDS.</em></h1>
      <p>Compare two laps corner by corner. See where each driver found time and what the car did there.</p></div>
      <div className="corner-title-stamp"><span>01 / 02</span><strong>CORNER<br />ANALYSIS</strong><span>{choice.slug}</span></div>
    </div>
    <div className="corner-picker" aria-label="Choose session">
      <label>SEASON<select value={year} onChange={(e) => update({ year: e.target.value, round: null, session: null, laps: null })}>
        {years.map((value) => <option key={value} value={value}>{value}</option>)}
      </select></label>
      <label>EVENT<select value={round} onChange={(e) => update({ round: e.target.value, session: null, laps: null })}>
        {events.map(([value, name]) => <option key={value} value={value}>R{String(value).padStart(2, '0')} · {name}</option>)}
      </select></label>
      <label>SESSION<select value={choice.meta.session} onChange={(e) => update({ session: e.target.value, laps: null })}>
        {available.map((item) => <option key={item.session} value={item.session}>{item.session}</option>)}
      </select></label>
    </div>
    <SessionDetail key={choice.slug} choice={choice} />
  </article>;
}

function SessionDetail({ choice }: { choice: Choice }) {
  const { slug, meta } = choice;
  const lapPicker = useRef<HTMLDivElement>(null);
  const { params, update } = useQueryParams();
  const session = useAsync((signal) => fetchSession(slug, signal), [slug]);
  const [compound, setCompound] = useState('ALL');
  useLayoutEffect(() => {
    const node = lapPicker.current;
    if (!session.data || !node) return;
    const media = gsap.matchMedia();
    media.add('(prefers-reduced-motion: no-preference)', () => {
      const visible = node.getBoundingClientRect().top < innerHeight * .9;
      const context = gsap.context(() => {
        gsap.fromTo(node, { y: 18, autoAlpha: 0 },
          { y: 0, autoAlpha: 1, duration: .65, delay: visible ? .85 : 0, ease: 'power3.out',
            scrollTrigger: { trigger: node, start: 'top 90%', once: true } });
      }, node);
      return () => context.revert();
    });
    return () => media.revert();
  }, [session.data]);
  if (session.error) return <ErrorState message={session.error} onRetry={session.retry} />;
  if (!session.data) return <Loading what="the session" />;
  const data = session.data;
  if (!data.has_telemetry || data.drivers.length < 2) return <Empty>Nothing to show: this session has fewer than two drivers with stored telemetry.</Empty>;
  const preset = (params.get('drivers') ?? '').split(',');
  const nameA = data.drivers.includes(preset[0]) ? preset[0] : data.drivers[0];
  const nameB = data.drivers.includes(preset[1]) ? preset[1] : data.drivers.find((d) => d !== nameA) ?? nameA;
  const compounds = [...new Set([...(data.driver_laps[nameA] ?? []), ...(data.driver_laps[nameB] ?? [])]
    .map((lap) => lap.compound).filter((v): v is string => !!v && v !== 'UNKNOWN'))].sort();
  const lapsFor = (name: string) => (data.driver_laps[name] ?? []).filter((lap) =>
    !data.is_race || compound === 'ALL' || lap.compound === compound);
  const presetLaps = (params.get('laps') ?? '').split(',');
  const pick = (name: string, wanted?: string) => {
    const laps = lapsFor(name);
    return laps.find((lap) => String(lap.lap) === wanted)?.lap
      ?? laps.find((lap) => lap.kind === 'flying' && lap.time_s !== null)?.lap
      ?? laps[0]?.lap ?? null;
  };
  const lapA = pick(nameA, presetLaps[0]); const lapB = pick(nameB, presetLaps[1]);
  const setDrivers = (a: string, b: string) => update({ drivers: `${a},${b}`, laps: null });
  const setLaps = (a: number | null, b: number | null) => update({ laps: a !== null && b !== null ? `${a},${b}` : null });

  return <>
    <div className="corner-picker corner-picker-laps" aria-label="Choose comparison" ref={lapPicker}>
      <label>REFERENCE<select value={nameA} onChange={(e) => setDrivers(e.target.value, nameB)}>
        {data.drivers.map((driver) => <option key={driver} value={driver}>{driverLabel(data, driver)}</option>)}</select></label>
      <label>COMPARE<select value={nameB} onChange={(e) => setDrivers(nameA, e.target.value)}>
        {data.drivers.map((driver) => <option key={driver} value={driver}>{driverLabel(data, driver)}</option>)}</select></label>
      {data.is_race && compounds.length > 0 && <label>TYRE COMPOUND
        <select value={compound} onChange={(e) => setCompound(e.target.value)}>
          <option value="ALL">ALL COMPOUNDS</option>{compounds.map((item) => <option key={item}>{item}</option>)}
        </select></label>}
      <LapPicker name={nameA} laps={lapsFor(nameA)} value={lapA} onChange={(n) => setLaps(n, lapB)} />
      <LapPicker name={nameB} laps={lapsFor(nameB)} value={lapB} onChange={(n) => setLaps(lapA, n)} />
    </div>
    {data.session_label.toLowerCase().includes('qualifying') && <p className="corner-definition"><Term id="qualifying" /></p>}
    {data.is_race && compounds.length > 0 && <p className="corner-definition"><Term id="compound" /></p>}
    {data.availability.summary.n_laps > 0 && <details className="corner-availability"><summary>Lap availability · {data.availability.summary.n_stored} of {data.availability.summary.n_laps} selectable</summary>
      <p>Only laps with stored car data can be compared. {data.availability.summary.stores_all_laps && data.availability.summary.coverage < .9
        ? 'Some telemetry is missing or unusable in the source feed.' : 'The session list reflects the laps this tool stores.'}</p>
      {data.availability.reasons.map((row) => <p key={row.reason}>{row.reason}: {row.count} laps</p>)}
    </details>}
    {lapA === null || lapB === null
      ? <Empty>Nothing to show for this tyre selection: one driver has no stored lap.</Empty>
      : <Comparison key={`${slug}-${nameA}-${nameB}-${lapA}-${lapB}`} data={data} meta={meta}
          nameA={nameA} nameB={nameB} lapA={lapA} lapB={lapB} />}
  </>;
}

function LapPicker({ name, laps, value, onChange }: { name: string; laps: DriverLap[];
  value: number | null; onChange: (lap: number) => void }) {
  return <label>{name} LAP<select value={value ?? ''} disabled={laps.length < 2} onChange={(e) => onChange(Number(e.target.value))}>
    {laps.length === 0 && <option value="">NO STORED LAPS</option>}
    {laps.map((lap) => <option key={lap.lap} value={lap.lap}>L{lap.lap} · {fmtLaptime(lap.time_s)}
      {lap.compound ? ` · ${lap.compound}` : ''}{lap.kind !== 'flying' ? ` · ${lap.kind} ${Math.round((lap.cov_end - lap.cov_start) * 100)}%` : ''}</option>)}
  </select></label>;
}

function Comparison({ data, meta, nameA, nameB, lapA, lapB }: { data: SessionResponse; meta: ManifestSession;
  nameA: string; nameB: string; lapA: number; lapB: number }) {
  const content = useRef<HTMLDivElement>(null);
  const slug = data.slug;
  const analysis = useAsync((signal) => fetchCornerAnalysis(slug, nameA, nameB, lapA, lapB, signal),
    [slug, nameA, nameB, lapA, lapB]);
  const params = { slug, driver1: nameA, driver2: nameB, lap1: lapA, lap2: lapB };
  const map = useAsync((signal) => fetchChartData<MapData>('speed-delta-map', params, signal), [slug, nameA, nameB, lapA, lapB]);
  const speedA = useAsync((signal) => fetchChartData<MapData>('speed-map', { ...params, which: 'a' }, signal), [slug, nameA, nameB, lapA, lapB]);
  const speedB = useAsync((signal) => fetchChartData<MapData>('speed-map', { ...params, which: 'b' }, signal), [slug, nameA, nameB, lapA, lapB]);
  const traces = useAsync((signal) => fetchChartData<TraceData>('trace-panel', params, signal), [slug, nameA, nameB, lapA, lapB]);
  const bars = useAsync((signal) => fetchChartData<CornerBarData>('corner-delta-bars', params, signal), [slug, nameA, nameB, lapA, lapB]);
  const laps = useAsync((signal) => fetchChartData<LapData>('lap-by-lap', params, signal), [slug, nameA, nameB, lapA, lapB]);
  const [view, setView] = useState<'delta' | 'a' | 'b'>('delta');
  const ready = Boolean(analysis.data && map.data && speedA.data && speedB.data && traces.data && bars.data && laps.data);
  useLayoutEffect(() => {
    const node = content.current;
    if (!ready || !node) return;
    const media = gsap.matchMedia();
    media.add('(prefers-reduced-motion: no-preference)', () => {
      const context = gsap.context(() => {
        const targets = node.querySelectorAll<HTMLElement>('.corner-intro, .corner-section-title, .corner-chart, .corner-replay, .corner-table-details');
        targets.forEach((target) => {
          if (target.getBoundingClientRect().top < innerHeight * .88) return;
          gsap.fromTo(target, { y: 20, opacity: .45 }, { y: 0, opacity: 1, duration: .65,
            ease: 'power3.out', scrollTrigger: { trigger: target, start: 'top 88%', once: true } });
        });
      }, node);
      return () => context.revert();
    });
    return () => media.revert();
  }, [ready]);
  if (analysis.error) return <ErrorState message={analysis.error} onRetry={analysis.retry} />;
  if (!analysis.data) return <Loading what="the comparison" />;
  const result: CornerAnalysisResponse = analysis.data;
  const otherError = [map, speedA, speedB, traces, bars, laps].find((item) => item.error);
  if (otherError) return <ErrorState message={otherError.error ?? 'Chart data unavailable'} onRetry={otherError.retry} />;
  if (!map.data || !speedA.data || !speedB.data || !traces.data || !bars.data || !laps.data) return <Loading what="the charts" />;
  const selected = view === 'delta' ? map.data : view === 'a' ? speedA.data : speedB.data;
  const projected = project(data.trackmap, 400, 260, 20);
  const gap = result.gap;
  const faster = gap === null ? null : nameA === nameB ? (gap > 0 ? result.display_a : result.display_b)
    : driverSurname(data, gap > 0 ? nameA : nameB);
  const partial = (result.summary.coverage ?? 1) < .999;
  const showTables = !window.matchMedia('(max-width: 600px)').matches;
  return <div className="corner-comparison" ref={content}>
    <div className="corner-verdict">
      <div><span className="lab">THE ANSWER / {meta.event_name.toUpperCase()}</span>
        <h2 className="k">{gap === null ? 'NO LAP GAP' : <>{faster} GAINS <ScrollNumber value={Math.abs(gap)} format={(value) => `${value.toFixed(3)} S`} /></>}</h2>
        <p>{gap === null ? 'One lap has no recorded total. The comparable segments still show where time changed hands.'
          : `Reference: ${driverLabel(data, nameA)} lap ${result.lap_a}. Compare: ${driverLabel(data, nameB)} lap ${result.lap_b}.`}</p>
        <p><b>{fmtDelta(result.summary.corner_delta_s)}</b> in corners · <b>{fmtDelta(result.summary.straight_delta_s)}</b> on straights.</p>
      </div>
      <div className="corner-verdict-circuit">
        <svg viewBox="0 0 400 260" role="img" aria-label={`${meta.event_name} circuit with three measured sectors`}>
          {projected && <SectorCircuit track={projected} sectorFractions={result.sector_fractions} strokeWidth={8} />}
        </svg>
        <div className="corner-sector-key"><span><i />Sector 1</span><span><i />Sector 2</span><span><i />Sector 3</span><span>▦ Start / finish</span></div>
      </div>
    </div>
    <div className="corner-stat-strip">
      <div><span>{result.display_a} · LAP {result.lap_a}</span><strong><ScrollNumber value={result.time_a} format={fmtLaptime} /></strong></div>
      <div><span>{result.display_b} · LAP {result.lap_b}</span><strong><ScrollNumber value={result.time_b} format={fmtLaptime} /></strong></div>
      <div><span>CORNER DELTA · S</span><strong>{result.summary.corner_delta_s < 0 ? '-' : '+'}<ScrollNumber value={Math.abs(result.summary.corner_delta_s)} format={(value) => value.toFixed(3)} /> s</strong></div>
      <div><span>STRAIGHT DELTA · S</span><strong>{result.summary.straight_delta_s < 0 ? '-' : '+'}<ScrollNumber value={Math.abs(result.summary.straight_delta_s)} format={(value) => value.toFixed(3)} /> s</strong></div>
    </div>
    {partial && <p className="corner-warning">Partial lap: {result.summary.n_comparable} of {result.summary.n_segments} segments have data for both drivers.
      Segment totals do not equal the full-lap gap. {result.summary.uncomparable_labels.join(', ')}</p>}
    <div className="corner-intro"><span className="lab">READ THE LAP / 01</span><p><Term id="delta" /> The map and replay use these exact two laps.</p></div>
    <section className="corner-section"><div className="corner-section-title"><span>01 / THE CIRCUIT</span><h2 className="k">WHERE TIME MOVES.</h2></div>
      <div className="corner-switch" role="group" aria-label="Map view">
        <button type="button" aria-pressed={view === 'delta'} onClick={() => setView('delta')}>TIME DELTA</button>
        <button type="button" aria-pressed={view === 'a'} onClick={() => setView('a')}>{result.display_a} SPEED</button>
        <button type="button" aria-pressed={view === 'b'} onClick={() => setView('b')}>{result.display_b} SPEED</button>
      </div>
      <MapRibbon data={selected} id={view === 'delta' ? 'speed-delta-map' : 'speed-map'}
        label={view === 'delta' ? 'LOCAL TIME CHANGE' : `${view === 'a' ? result.display_a : result.display_b} · SPEED (km/h)`}
        sectorFractions={result.sector_fractions} nameA={result.display_a} nameB={result.display_b} />
      <Replay track={data.trackmap} tA={result.ghost.t_a} tB={result.ghost.t_b} nameA={result.display_a} nameB={result.display_b}
        sectorFractions={result.sector_fractions} />
    </section>
    <section className="corner-section"><div className="corner-section-title"><span>02 / THE INPUTS</span><h2 className="k">WHAT THE CAR DID.</h2></div>
      <p className="corner-definition"><Term id="telemetry" /></p>
      <TracePanel data={traces.data} />
    </section>
    <section className="corner-section"><div className="corner-section-title"><span>03 / THE VERDICT</span><h2 className="k">CORNER BY CORNER.</h2></div>
      <CornerBars data={bars.data} />
      <details className="corner-table-details" open={showTables}><summary>Exact segment values · {result.segments.length} rows</summary>
      <div className="corner-table-wrap"><table><thead><tr><th>SEGMENT</th><th>TYPE</th><th>Δ TIME · S</th><th>{result.display_a} APEX · KM/H</th><th>{result.display_b} APEX · KM/H</th></tr></thead>
        <tbody>{result.segments.map((row, i) => <tr key={`${row.label}-${i}`}><th>{row.label}</th><td>{row.kind}</td>
          <td>{row.delta_s === null ? '—' : fmtDelta(row.delta_s)}</td><td>{row.v_min_a === null ? '—' : fmt(row.v_min_a)}</td>
          <td>{row.v_min_b === null ? '—' : fmt(row.v_min_b)}</td></tr>)}</tbody></table></div></details>
    </section>
    {nameA !== nameB && result.head_to_head.length > 0 && <section className="corner-section"><div className="corner-section-title"><span>04 / THE SESSION</span><h2 className="k">LAP BY LAP.</h2></div>
      <LapChart data={laps.data} />
      <details className="corner-table-details" open={showTables}><summary>Exact lap values · {result.head_to_head.length} laps</summary>
      <div className="corner-table-wrap"><table><thead><tr><th>LAP</th><th>{nameA} · S</th><th>{nameB} · S</th><th>DELTA · S</th><th>RUNNING · S</th></tr></thead>
        <tbody>{result.head_to_head.map((row) => <tr key={row.LapNumber}><th>{row.LapNumber}</th>
          <td>{row.LapTime_s_a === null ? '—' : fmt(row.LapTime_s_a)}</td><td>{row.LapTime_s_b === null ? '—' : fmt(row.LapTime_s_b)}</td>
          <td>{row.delta_s === null ? '—' : fmtDelta(row.delta_s)}</td><td>{row.cumulative_s === null ? '—' : fmtDelta(row.cumulative_s)}</td></tr>)}</tbody></table></div></details>
    </section>}
  </div>;
}
