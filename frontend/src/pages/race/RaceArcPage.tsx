import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { RaceChart } from '../../components/charts/RaceCharts';
import { Empty, ErrorState, Loading } from '../../components/states';
import { Term } from '../../components/Term';
import { fetchRaceArc, fetchSession, fetchUndercut, useAsync } from '../../lib/api';
import { placeTurnNumbers, pointOnTrack, project, projectCornerMarks } from '../../lib/circuit';
import { fmt, fmtInt, fmtPercent, titleCase } from '../../lib/format';
import { useQueryParams } from '../../lib/router';
import type { CompoundSummaryRow, ManifestSession, RaceArcResponse, SessionResponse } from '../../lib/types';
import '../corner/corner.css';
import './race.css';

gsap.registerPlugin(ScrollTrigger);

const VIEWS = ['Tyre Degradation', 'Track Evolution', 'Race Strategy'] as const;
type View = typeof VIEWS[number];
const RACE_FUEL_KG: Record<number, number> = { 2024: 110, 2025: 110, 2026: 70 };
type Choice = { slug: string; meta: ManifestSession };

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

function ScrollProgress({ page, view }: { page: React.RefObject<HTMLElement | null>; view: View }) {
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
      const sections = [root.querySelector('.race-circuit'), ...root.querySelectorAll('.race-section')];
      sections.forEach((section, index) => {
        if (!section) return;
        const tick = document.createElement('u');
        const label = document.createElement('b');
        label.textContent = index === 0 ? 'SESSION' : section.querySelector('.corner-section-title span')?.textContent?.replace(/^\d+ \/ /, '') ?? '';
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
  }, [page, view]);
  return <div className="corner-progress" aria-hidden="true" ref={bar}><i ref={fill} /></div>;
}

function Metric({ label, value, detail }: { label: string; value: ReactNode; detail?: string }) {
  return <div><span>{label}</span><strong>{value}</strong>{detail && <small>{detail}</small>}</div>;
}

function Range({ label, value, min, max, step, unit, help, onChange }: { label: string; value: number;
  min: number; max: number; step: number; unit: string; help: string; onChange: (value: number) => void }) {
  return <label className="race-range"><span>{label}<strong>{value.toFixed(step < .01 ? 3 : step < 1 ? 2 : 0)} {unit}</strong></span>
    <input type="range" min={min} max={max} step={step} value={value}
      onChange={(event) => onChange(Number(event.target.value))} />
    <small>{help}</small></label>;
}

function Table({ rows, columns }: { rows: object[];
  columns: { key: string; label: string; format?: (value: unknown) => string }[] }) {
  if (!rows.length) return <p>No rows are available for this session.</p>;
  return <details className="corner-table-details">
    <summary>Exact values · {rows.length} rows</summary><div className="corner-table-wrap"><table>
      <thead><tr>{columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead>
      <tbody>{rows.map((item, index) => {
        const row = item as Record<string, unknown>;
        return <tr key={index}>{columns.map((column) =>
          <td key={column.key}>{column.format ? column.format(row[column.key])
            : row[column.key] === null || row[column.key] === undefined ? '—' : String(row[column.key])}</td>)}</tr>;
      })}</tbody>
    </table></div></details>;
}

function Section({ number, title, children }: { number: string; title: string; children: React.ReactNode }) {
  return <section className="corner-section race-section"><div className="corner-section-title">
    <span>{number}</span><h2 className="k">{title}</h2></div>{children}</section>;
}

function RaceView({ children }: { children: ReactNode }) {
  const content = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const node = content.current;
    if (!node) return;
    const media = gsap.matchMedia();
    media.add('(prefers-reduced-motion: no-preference)', () => {
      const context = gsap.context(() => {
        node.querySelectorAll<HTMLElement>('.corner-section-title, .race-metrics, .race-finding, .race-method, .corner-table-details, .race-drivers, .race-calculator').forEach((target) => {
          const rect = target.getBoundingClientRect();
          if (rect.bottom <= 0) return;
          const below = rect.top >= innerHeight * .88;
          const tween = gsap.fromTo(target, { y: 18, opacity: .45 },
            { y: 0, opacity: 1, duration: .65, ease: 'power3.out', paused: below });
          if (below) ScrollTrigger.create({ trigger: target, start: 'top 88%', once: true,
            onEnter: () => tween.play() });
        });
      }, node);
      return () => context.revert();
    });
    return () => media.revert();
  }, []);
  return <div className="race-view" ref={content}>{children}</div>;
}

function Circuit({ session }: { session: SessionResponse }) {
  const circuit = useRef<SVGSVGElement>(null);
  useLayoutEffect(() => {
    const node = circuit.current;
    const line = node?.querySelector('polyline');
    if (!node || !line) return;
    const media = gsap.matchMedia();
    media.add('(prefers-reduced-motion: no-preference)', () => {
      const length = line.getTotalLength();
      const context = gsap.context(() => {
        gsap.set(line, { strokeDasharray: length, strokeDashoffset: length });
        const marks = node.querySelectorAll('rect, g');
        gsap.set(marks, { opacity: 0 });
        const below = node.getBoundingClientRect().top >= innerHeight * .85;
        const timeline = gsap.timeline({ paused: below })
          .to(line, { strokeDashoffset: 0, duration: 1.1, ease: 'power2.inOut' })
          .to(marks, { opacity: 1, duration: .3 }, .78);
        if (below) ScrollTrigger.create({ trigger: node, start: 'top 88%', once: true,
          onEnter: () => timeline.play() });
      }, node);
      return () => context.revert();
    });
    return () => media.revert();
  }, [session]);
  const track = project(session.trackmap, 400, 260, 24);
  if (!track) return null;
  const source = session.trackmap.corners;
  const marks = source ? projectCornerMarks(session.trackmap, 400, 260, source, 24) : [];
  const labels = placeTurnNumbers(track, marks, 400, 260);
  const [sx, sy] = pointOnTrack(track, 0);
  return <svg viewBox="0 0 400 260" role="img" aria-label={`${session.meta.event_name} circuit and turns`} ref={circuit}>
    <polyline points={track.x.map((x, index) => `${x},${track.y[index]}`).join(' ')}
      fill="none" stroke="#131313" strokeWidth="5" strokeLinejoin="round" />
    <rect x={sx - 4} y={sy - 4} width="8" height="8" fill="#F2E600" stroke="#131313" strokeWidth="2" />
    {marks.map((mark, index) => <g key={index}><title>Turn {mark.label}</title>
      <line x1={mark.x} y1={mark.y} x2={labels[index].x} y2={labels[index].y}
        stroke="#131313" strokeWidth=".8" opacity=".6" />
      <circle cx={mark.x} cy={mark.y} r="2.5" fill="#F2E600" stroke="#131313" strokeWidth="1" />
      <text x={labels[index].x} y={labels[index].y + 4} textAnchor="middle" fontSize="10"
        stroke="#F2E600" strokeWidth="3" paintOrder="stroke"
        fontWeight="700" fill="#131313">{mark.label}</text></g>)}
  </svg>;
}

export function RaceArcPage({ sessions, years, openerSlug }: { sessions: ManifestSession[];
  years: number[]; openerSlug?: string | null }) {
  const page = useRef<HTMLElement>(null);
  const { params, update } = useQueryParams();
  const opener = sessions.find((item) => item.slug === openerSlug);
  const wantYear = Number(params.get('year'));
  const year = years.includes(wantYear) ? wantYear : opener?.year ?? years[0];
  const events = useMemo(() => {
    const unique = new Map<number, string>();
    sessions.filter((item) => item.year === year).forEach((item) => unique.set(item.round, item.event_name));
    return [...unique].sort((a, b) => a[0] - b[0]);
  }, [sessions, year]);
  const wantRound = Number(params.get('round'));
  const round = events.some(([number]) => number === wantRound) ? wantRound
    : opener?.year === year && events.some(([number]) => number === opener.round)
      ? opener.round : events[0]?.[0];
  const available = sessions.filter((item) => item.year === year && item.round === round);
  const chosen = available.find((item) => item.session === params.get('session'))
    ?? available.find((item) => item.slug === openerSlug) ?? available[0];
  const choice: Choice | null = chosen ? { slug: chosen.slug, meta: chosen } : null;
  const wantedView = params.get('view');
  const view: View = VIEWS.find((item) => item === wantedView) ?? VIEWS[0];
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
        gsap.fromTo('.corner-picker', { y: 20, autoAlpha: 0 },
          { y: 0, autoAlpha: 1, duration: .7, delay: .55, ease: 'power3.out',
            scrollTrigger: { trigger: '.corner-picker', start: 'top 90%', once: true } });
      }, page);
      return () => context.revert();
    });
    return () => media.revert();
  }, [choice?.slug]);
  if (!choice) return <Empty>Nothing to show for this session.</Empty>;

  return <article className="corner-page race-page" data-slug={choice.slug} ref={page}>
    <ScrollProgress page={page} view={view} />
    <div className="corner-mast"><span className="lab">APEXTRACE / ANALYSIS 02</span>
      <span className="lab">REAL TIMING DATA · {choice.meta.year}</span></div>
    <div className="corner-title"><div><span className="lab">{choice.meta.event_name} · {choice.meta.session}</span>
      <h1 className="k">THE RACE<br /><em>HAS AN ARC.</em></h1>
      <p>Measure tyre wear, the track itself, and the cost of a strategy call from recorded laps.</p></div>
      <div className="corner-title-stamp"><span>02 / 02</span><strong>RACE<br />ARC</strong><span>{choice.slug}</span></div>
    </div>
    <div className="corner-picker" role="group" aria-label="Choose session">
      <label>SEASON<select value={year} onChange={(event) => update({ year: event.target.value, round: null, session: null })}>
        {years.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
      <label>EVENT<select value={round} onChange={(event) => update({ round: event.target.value, session: null })}>
        {events.map(([number, name]) => <option key={number} value={number}>R{String(number).padStart(2, '0')} · {name}</option>)}</select></label>
      <label>SESSION<select value={choice.meta.session} onChange={(event) => update({ session: event.target.value })}>
        {available.map((item) => <option key={item.session} value={item.session}>{item.session}</option>)}</select></label>
    </div>
    <RaceSession key={choice.slug} choice={choice} view={view} onView={(next) => update({ view: next })} />
  </article>;
}

function RaceSession({ choice, view, onView }: { choice: Choice; view: View; onView: (view: View) => void }) {
  const { slug, meta } = choice;
  const circuitFrame = useRef<HTMLDivElement>(null);
  const assumptions = useRef<HTMLDivElement>(null);
  const tabs = useRef<HTMLDivElement>(null);
  const session = useAsync((signal) => fetchSession(slug, signal), [slug]);
  const [fuelEffect, setFuelEffect] = useState(.032);
  const [fuelKg, setFuelKg] = useState(RACE_FUEL_KG[meta.year] ?? 100);
  const arc = useAsync((signal) => fetchRaceArc(slug, fuelEffect, fuelKg, signal), [slug, fuelEffect, fuelKg]);
  useLayoutEffect(() => {
    if (!session.data) return;
    const media = gsap.matchMedia();
    media.add('(prefers-reduced-motion: no-preference)', () => {
      const context = gsap.context(() => {
        [circuitFrame.current, assumptions.current].forEach((target) => {
          if (!target) return;
          const below = target.getBoundingClientRect().top >= innerHeight * .88;
          const tween = gsap.fromTo(target, { y: 18, opacity: .45 },
            { y: 0, opacity: 1, duration: .65, ease: 'power3.out', paused: below });
          if (below) ScrollTrigger.create({ trigger: target, start: 'top 88%', once: true,
            onEnter: () => tween.play() });
        });
      });
      return () => context.revert();
    });
    return () => media.revert();
  }, [session.data]);
  useLayoutEffect(() => {
    const node = tabs.current;
    if (!node || !arc.data) return;
    const media = gsap.matchMedia();
    media.add('(prefers-reduced-motion: no-preference)', () => {
      const below = node.getBoundingClientRect().top >= innerHeight * .88;
      const tween = gsap.fromTo(node, { y: 16, opacity: .45 },
        { y: 0, opacity: 1, duration: .55, ease: 'power3.out', paused: below });
      const trigger = below ? ScrollTrigger.create({ trigger: node, start: 'top 88%', once: true,
        onEnter: () => tween.play() }) : null;
      return () => { trigger?.kill(); tween.kill(); };
    });
    return () => media.revert();
  }, [Boolean(arc.data)]);
  if (session.error) return <ErrorState message={session.error} onRetry={session.retry} />;
  if (!session.data) return <Loading what="the session" />;
  if (!session.data.drivers.length) return <Empty>Nothing to show: this session has no stored drivers.</Empty>;
  const chartParams = { slug, fuel_effect: fuelEffect, fuel_kg: fuelKg };

  return <>
    <div className="race-circuit" ref={circuitFrame}><div><span className="lab">THE MEASURED SESSION / {meta.event_name.toUpperCase()}</span>
      <h2 className="k">{meta.location.toUpperCase()}.</h2><p>{meta.country} · {session.data.session_label}
        {session.data.is_race ? ' · Recorded race laps' : ' · Timed session laps'}</p></div>
      <Circuit session={session.data} /></div>
    {!session.data.is_race && <p className="corner-definition"><Term id="qualifying" /></p>}
    <div className="race-assumptions" ref={assumptions}><div><span className="lab">MODEL INPUTS / ADJUST THE ASSUMPTIONS</span>
      <p>Fuel correction changes the estimates below; the selected values are sent with each calculation.</p></div>
      <Range label="FUEL EFFECT" value={fuelEffect} min={.020} max={.045} step={.001} unit="s/kg"
        help="Estimated lap time gained per kilogram of fuel burned." onChange={setFuelEffect} />
      <Range label="STARTING FUEL" value={fuelKg} min={40} max={120} step={5} unit="kg"
        help="Starting race fuel used by the correction." onChange={setFuelKg} />
    </div>
    {arc.error && <ErrorState message={arc.error} onRetry={arc.retry} />}
    {!arc.data && !arc.error && <Loading what="the race analysis" />}
    {arc.data && <>
      <div className="race-tabs" role="group" aria-label="Race analysis view" ref={tabs}>
        {VIEWS.map((item, index) => <button key={item} type="button" aria-pressed={view === item}
          onClick={() => onView(item)}><span>0{index + 1} /</span>{item.toUpperCase()}</button>)}
      </div>
      <p className="race-glossary"><Term id="degradation" /> <Term id="track-evolution" />
        {' '}<Term id="fuel-corrected" /></p>
      {arc.fetching && <p className="race-updating" aria-live="polite">Updating the measured estimates…</p>}
      <RaceView key={view}>
        {view === 'Tyre Degradation' && <Degradation arc={arc.data} params={chartParams} />}
        {view === 'Track Evolution' && <Evolution arc={arc.data} params={chartParams} />}
        {view === 'Race Strategy' && <Strategy arc={arc.data} params={chartParams} />}
      </RaceView>
    </>}
  </>;
}

function Degradation({ arc, params }: { arc: RaceArcResponse; params: Record<string, string | number> }) {
  if (!arc.is_race) return <Section number="01 / TYRE DEGRADATION" title="RACE STINTS ONLY.">
    <p>This estimate needs long race runs. Choose a Race session to measure how tyres wear.</p>
    <p className="corner-definition"><Term id="degradation" /> <Term id="stint" /></p></Section>;
  const { summary, stints, rejections, n_prepared: prepared, n_all_laps: all, n_cliffs: cliffs } = arc.degradation;
  if (!prepared) return <Section number="01 / TYRE DEGRADATION" title="NO CLEAN LAPS.">
    <p>No laps survived the cleaning filters for this race.</p><Term id="degradation" /></Section>;
  const first = summary[0]; const last = summary[summary.length - 1];
  return <>
    <Section number="01 / THE MEASURE" title="HOW TYRES FADE.">
      <p className="race-lead"><Term id="degradation" /> <Term id="stint" /> <Term id="compound" /></p>
      <div className="corner-stat-strip race-metrics">{summary.map((row: CompoundSummaryRow) =>
        <Metric key={row.Compound} label={`${titleCase(row.Compound)} degradation`}
          value={<><ScrollNumber value={row.deg_s_per_lap} format={(n) => fmt(n)} /> s/lap</>}
          detail={`95% CI ${fmt(row.ci_low)}–${fmt(row.ci_high)} · ${row.n_stints} stints`} />)}
        <Metric label="CLEAN LAPS USED" value={<ScrollNumber value={prepared} format={(n) => fmtInt(Math.round(n))} />}
          detail={`${fmtPercent(prepared / Math.max(all, 1))} of all laps`} />
      </div>
      {first && last && first !== last && <p className="race-finding">The {first.Compound.toLowerCase()} estimate is
        {' '}{fmt(first.deg_s_per_lap)} s/lap; the {last.Compound.toLowerCase()} estimate is
        {' '}{fmt(last.deg_s_per_lap)} s/lap. These pooled rates summarize the recorded clean stints.</p>}
      <p className="corner-definition"><Term id="fuel-corrected" /></p>
    </Section>
    <Section number="02 / THE FIT" title="EVERY CLEAN LAP.">
      <RaceChart id="degradation-scatter" params={params} title="PACE AGAINST TYRE AGE" />
      <RaceChart id="degradation-bars" params={params} title="POOLED WEAR RATE" />
    </Section>
    <Section number="03 / THE FILTER" title="WHAT WAS LEFT OUT.">
      <p>Traffic, safety cars, and pit laps are listed rather than silently discarded.</p>
      <Table rows={rejections} columns={[{ key: 'reason', label: 'REASON' },
        { key: 'count', label: 'LAPS' }, { key: 'pct_of_input', label: 'SHARE OF INPUT',
          format: (value) => fmt(Number(value), 1) + '%' }]} />
      {cliffs > 0 && <p>{cliffs} of {stints.length} stints have a better quadratic fit with upward curvature.</p>}
      <Table rows={stints} columns={[{ key: 'Driver', label: 'DRIVER' }, { key: 'Stint', label: 'STINT' },
        { key: 'Compound', label: 'TYRE' }, { key: 'n_laps', label: 'LAPS' },
        { key: 'deg_s_per_lap', label: 'WEAR · s/lap', format: (value) => fmt(Number(value)) },
        { key: 'ci_low', label: '95% LOW', format: (value) => fmt(Number(value)) },
        { key: 'ci_high', label: '95% HIGH', format: (value) => fmt(Number(value)) }]} />
    </Section>
  </>;
}

function Evolution({ arc, params }: { arc: RaceArcResponse; params: Record<string, string | number> }) {
  const result = arc.evolution.result;
  const gain = result?.total_gain_s;
  const naive = arc.evolution.naive_gain;
  return <>
    <Section number="01 / THE QUESTION" title="TRACK OR TYRES?">
      <p className="race-lead"><Term id="track-evolution" /> <Term id="degradation" /></p>
      <details className="race-method"><summary>Why a straight trend line is misleading</summary>
        <p>Within one <Term id="stint" />, tyre age and session time rise together. Drivers pit at different
        times. Fuel correction is applied first; their combined laps let the model separate tyre age,
        car pace and track change.</p>
        <code>corrected lap time ~ driver + compound × tyre age + spline(session progress)</code>
      </details>
    </Section>
    {!arc.is_race ? <Section number="02 / TIMED SESSION" title="THE BEST LAP FELL.">
      {arc.evolution.has_progression ? <RaceChart id="session-best" params={{ slug: params.slug }}
        title="SESSION BEST OVER TIME" />
        : <p>No timed progression is stored for this session.</p>}
    </Section> : !arc.degradation.n_prepared || !result || gain === undefined
      ? <Section number="02 / THE MODEL" title="NO SUPPORTED FIT.">
          <p>The pooled model needs at least 40 clean laps across four drivers with varied stint timing.
            This session does not support that estimate.</p></Section>
      : <>
        <Section number="02 / THE ANSWER" title="A DIFFERENT CURVE.">
          <div className="corner-stat-strip race-metrics">
            <Metric label="MODELLED TRACK CHANGE" value={<><ScrollNumber value={Math.abs(gain)} format={(n) => fmt(n)} /> s</>}
              detail={gain >= 0 ? 'faster by race end' : 'slower by race end'} />
            <Metric label="SIMPLE LAP-TREND GAIN" value={<><ScrollNumber value={naive} format={(n) => fmt(n, 3, { sign: true })} /> s</>}
              detail={naive === null ? 'unavailable' : `${naive < 0 ? 'negative = slower' : 'positive = faster'} · still mixes drivers and tyres`} />
            <Metric label="MODEL FIT" value={<>R² <ScrollNumber value={result.r_squared} format={(n) => fmt(n)} /></>}
              detail={`${fmtInt(result.n_laps)} laps · ${result.n_drivers} drivers`} />
          </div>
          <p className="race-finding">After fuel correction and adjustment for driver and tyre age, the model
            estimates the track became {gain >= 0 ? ' faster' : ' slower'} by {fmt(Math.abs(gain))} s of lap time.
            {naive === null ? ' The simple fuel-corrected lap trend is unavailable.'
              : ` The simple fuel-corrected lap trend points ${naive < 0 ? 'slower' : 'faster'} by ${fmt(Math.abs(naive))} s; it still mixes drivers and tyres.`}</p>
          <p className="corner-definition"><Term id="fuel-corrected" /></p>
        </Section>
        <Section number="03 / THE EVIDENCE" title="THE TRACK ITSELF.">
          <RaceChart id="evolution-curve" params={params} title="ADJUSTED TRACK CHANGE VS LAP TREND" />
          <RaceChart id="evolution-temperature" params={params} title="TRACK CHANGE AND TRACK TEMPERATURE" />
          <Table rows={result.degradation} columns={[{ key: 'Compound', label: 'COMPOUND' },
            { key: 'deg_s_per_lap', label: 'WEAR · s/lap', format: (value) => fmt(Number(value)) },
            { key: 'ci_low', label: '95% LOW', format: (value) => fmt(Number(value)) },
            { key: 'ci_high', label: '95% HIGH', format: (value) => fmt(Number(value)) }]} />
          <p className="corner-definition"><Term id="compound" /></p>
        </Section>
      </>}
  </>;
}

function Strategy({ arc, params }: { arc: RaceArcResponse; params: Record<string, string | number> }) {
  if (!arc.is_race) return <Section number="01 / RACE STRATEGY" title="RACE SESSION ONLY.">
    <p>Strategy measures pit stops, stints and race positions. Choose a Race session.</p>
    <p className="corner-definition"><Term id="stint" /></p></Section>;
  const strategy = arc.strategy;
  const loss = strategy.pit_loss ?? {};
  const pace = strategy.pace_display ?? [];
  const gapDrivers = strategy.gap_drivers ?? [];
  return <>
    <Section number="01 / THE COST" title="PITS CHANGE PACE.">
      <p className="race-lead"><Term id="pit-loss" /> <Term id="stint" /></p>
      <div className="corner-stat-strip race-metrics">
        <Metric label="PIT LOSS" value={<><ScrollNumber value={loss.pit_loss_s ?? null} format={(n) => fmt(n, 1)} /> s</>}
          detail={`${fmt(loss.in_lap_s, 1)} s in-lap + ${fmt(loss.out_lap_s, 1)} s out-lap`} />
        <Metric label="PIT STOPS" value={<ScrollNumber value={loss.n_stops ?? 0} format={(n) => String(Math.round(n))} />} />
        <Metric label="STINTS" value={<ScrollNumber value={strategy.n_stints ?? 0} format={(n) => String(Math.round(n))} />} />
        {pace.length > 0 && <Metric label="BEST MEDIAN PACE" value={String(pace[0].Driver)}
          detail={`${pace[0].Median} median clean lap`} />}
      </div>
    </Section>
    <Section number="02 / THE FIELD" title="WHO HAD THE PACE?">
      <RaceChart id="stint-chart" params={{ slug: params.slug }} title="TYRE STINT TIMELINE" />
      <RaceChart id="race-pace-box" params={params} title="RACE PACE DISTRIBUTION" />
      <p className="corner-definition"><Term id="compound" /> <Term id="fuel-corrected" /></p>
      <Table rows={pace} columns={[{ key: 'Driver', label: 'DRIVER' }, { key: 'Laps', label: 'LAPS' },
        { key: 'Median', label: 'MEDIAN LAP · m:ss.sss' }, { key: 'Gap', label: 'GAP · s' }]} />
    </Section>
    <Section number="03 / THE ORDER" title="GAPS AND PLACES.">
      <GapChart slug={String(params.slug)} drivers={gapDrivers} />
      <RaceChart id="position-chart" params={{ slug: params.slug }} title="TRACK POSITION BY LAP" />
    </Section>
    <Section number="04 / THE CALL" title="DOES THE UNDERCUT WORK?">
      <p className="race-lead"><Term id="undercut" /> Both drivers pay the same pit loss, so this
        comparison tracks the fresh tyre gain against the initial gap.</p>
      <Undercut defaultDeg={strategy.default_deg_rate ?? .10}
        defaultAdvantage={strategy.default_advantage ?? .8} />
    </Section>
  </>;
}

function GapChart({ slug, drivers }: { slug: string; drivers: string[] }) {
  const [chosen, setChosen] = useState(() => drivers.slice(0, 5));
  const selected = chosen.filter((driver) => drivers.includes(driver));
  return <><fieldset className="race-drivers"><legend>DRIVERS TO COMPARE · {selected.length} SELECTED</legend>
    <div className="race-driver-actions"><div className="corner-switch" role="group" aria-label="Driver selection">
      <button type="button" onClick={() => setChosen(drivers)}>ALL</button>
      <button type="button" onClick={() => setChosen([])}>CLEAR</button>
    </div></div>
    {drivers.map((driver) => <label key={driver}><input type="checkbox" checked={selected.includes(driver)}
      onChange={(event) => setChosen((current) => event.target.checked
        ? [...current, driver] : current.filter((name) => name !== driver))} />{driver}</label>)}
  </fieldset><RaceChart id="gap-chart" params={{ slug, drivers: selected.join(',') }}
    title="GAP TO THE LEADER" /></>;
}

function Undercut({ defaultDeg, defaultAdvantage }: { defaultDeg: number; defaultAdvantage: number }) {
  const [gap, setGap] = useState(1.5);
  const [advantage, setAdvantage] = useState(Number(defaultAdvantage.toFixed(2)));
  const [deg, setDeg] = useState(Number(defaultDeg.toFixed(2)));
  const result = useAsync((signal) => fetchUndercut(gap, advantage, deg, signal), [gap, advantage, deg]);
  return <><div className="race-calculator">
    <Range label="GAP TO RIVAL" value={gap} min={0} max={8} step={.1} unit="s"
      help="How far behind before stopping." onChange={setGap} />
    <Range label="FRESH TYRE ADVANTAGE" value={advantage} min={.1} max={2.5} step={.01} unit="s/lap"
      help="Pace gain on the first fresh-tyre lap." onChange={setAdvantage} />
    <Range label="DEGRADATION" value={deg} min={.01} max={.40} step={.01} unit="s/lap"
      help={`Default measured from this race: ${fmt(defaultDeg)} s/lap.`} onChange={setDeg} />
  </div>
    {result.error && <ErrorState message={result.error} onRetry={result.retry} />}
    {!result.data && !result.error && <Loading what="the undercut" />}
    {result.data && <p className="race-finding">{result.data.breakeven_lap
      ? `The model closes a ${gap.toFixed(1)} s gap after ${result.data.breakeven_lap} laps; maximum gain is ${fmt(result.data.max_gain, 2)} s.`
      : `The model does not close a ${gap.toFixed(1)} s gap within this window; maximum gain is ${fmt(result.data.max_gain, 2)} s.`}</p>}
    <RaceChart id="undercut-chart" params={{ gap_s: gap, advantage, deg_rate: deg }} title="FRESH TYRE GAIN AGAINST THE GAP" />
  </>;
}
