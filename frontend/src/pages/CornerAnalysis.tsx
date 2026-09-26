/** Corner-by-corner comparison of two drivers - the flagship view. */

import { useMemo, useState } from 'react';
import { SessionHeader } from '../components/brand/SessionHeader';
import { GhostReplay } from '../components/brand/CircuitArt';
import { PlotlyChart } from '../components/PlotlyChart';
import { SidebarSection } from '../components/Sidebar';
import {
  DataTable, timingCell, timingStates, timingStyle, type Column,
} from '../components/ui/DataTable';
import {
  Caption, Columns, Expander, Info, Kerb, Kicker, Metric, Section, Select,
  Subheader, Success, RadioGroup, Toggle, Warning,
} from '../components/ui/primitives';
import { Empty, ErrorState, Loading } from '../components/states';
import { fetchCornerAnalysis, fetchSession, useAsync } from '../lib/api';
import {
  article, fmt, fmtDelta, fmtLaptime, joinProse,
} from '../lib/format';
import { useQueryParams } from '../lib/router';
import { useTheme } from '../lib/theme';
import type { Selection } from '../components/SessionPicker';
import type { DriverLap, RejectionRow, SegmentRow } from '../lib/types';

/** How each partial lap kind is described. A lap that does not cover the whole
 *  track has to say so at the point of choosing it, not after the charts have
 *  already been read. */
const KIND_LABEL: Record<string, string> = {
  start: 'grid start', in: 'in-lap', out: 'out-lap',
};
const KIND_SHORT: Record<string, string> = { start: 'grid', in: 'in', out: 'out' };

/** Below this, the shortfall is large enough to change what the reader should
 *  conclude from the lap list, so it is stated up front rather than folded
 *  away. */
const COVERAGE_WARN_BELOW = 0.90;

export function CornerAnalysisPage({ selection }: { selection: Selection }) {
  const { slug, meta } = selection;
  const { params, update } = useQueryParams();
  const theme = useTheme();

  const session = useAsync((s) => fetchSession(slug, s), [slug]);
  const data = session.data;
  const isRace = data?.is_race ?? false;
  const drivers = data?.drivers ?? [];

  // ---- selection ------------------------------------------------------

  const preset = (params.get('drivers') ?? '')
    .split(',').filter((d) => drivers.includes(d));
  const nameA = preset[0] ?? drivers[0] ?? '';
  const nameB = preset[1] ?? (drivers.length > 1 ? drivers[1] : drivers[0]) ?? '';

  const [compoundFilter, setCompoundFilter] = useState('All compounds');

  const compounds = useMemo(() => {
    const found = new Set<string>();
    for (const driver of [nameA, nameB]) {
      for (const lap of data?.driver_laps[driver] ?? []) {
        if (lap.compound) found.add(lap.compound);
      }
    }
    found.delete('UNKNOWN'); found.delete('nan'); found.delete('');
    return [...found].sort();
  }, [data, nameA, nameB]);

  const activeCompound = isRace && compoundFilter !== 'All compounds'
    ? compoundFilter : null;

  const lapsFor = (driver: string): DriverLap[] => {
    const all = data?.driver_laps[driver] ?? [];
    return activeCompound ? all.filter((l) => l.compound === activeCompound) : all;
  };

  const presetLaps = (params.get('laps') ?? '').split(',').filter(Boolean);
  const pick = (driver: string, wanted: string | undefined): number | null => {
    const laps = lapsFor(driver);
    if (laps.length === 0) return null;
    const found = laps.find((l) => String(l.lap) === wanted);
    return (found ?? laps[0]).lap;
  };
  const lapA = pick(nameA, presetLaps[0]);
  const lapB = pick(nameB, presetLaps[1]);

  const analysis = useAsync(
    nameA && nameB && lapA !== null && lapB !== null
      ? (s) => fetchCornerAnalysis(slug, nameA, nameB, lapA, lapB, s)
      : null,
    [slug, nameA, nameB, lapA, lapB],
  );

  const setDrivers = (a: string, b: string) =>
    update({ drivers: `${a},${b}`, laps: null });
  const setLaps = (a: number | null, b: number | null) =>
    update({ laps: a !== null && b !== null ? `${a},${b}` : null });

  const chartParams = {
    slug, driver1: nameA, driver2: nameB, lap1: lapA, lap2: lapB,
  };

  // ---- sidebar --------------------------------------------------------

  const sidebar = (
    <SidebarSection>
      <Kicker>Comparison</Kicker>
      <Select
        label="Reference" options={drivers} value={nameA}
        onChange={(next) => setDrivers(next, nameB)}
      />
      <Select
        label="Compare" options={drivers} value={nameB}
        onChange={(next) => setDrivers(nameA, next)}
      />
      {isRace && compounds.length > 0 && (
        <Select
          label="Filter by compound"
          options={['All compounds', ...compounds]}
          value={compoundFilter}
          onChange={setCompoundFilter}
          help="Narrow the lap list to a specific tyre compound."
        />
      )}
      <LapSelect
        driver={nameA} laps={lapsFor(nameA)} value={lapA} isRace={isRace}
        compound={activeCompound}
        onChange={(next) => setLaps(next, lapB)}
      />
      <LapSelect
        driver={nameB} laps={lapsFor(nameB)} value={lapB} isRace={isRace}
        compound={activeCompound}
        onChange={(next) => setLaps(lapA, next)}
      />
    </SidebarSection>
  );

  // ---- guards ---------------------------------------------------------

  if (session.error) {
    return <ErrorState message={session.error} onRetry={session.retry} />;
  }
  if (!data) {
    return <Loading what="the session" />;
  }

  const header = (
    <Section>
      <SessionHeader
        meta={meta} sessionLabel={data.session_label}
        pageTitle="Corner Analysis" track={data.trackmap}
      />
    </Section>
  );

  if (!data.has_telemetry) {
    return (<>{header}<Empty>No telemetry is stored for this session.</Empty></>);
  }
  if (drivers.length < 2) {
    return (
      <>{header}
        <Empty>This session has fewer than two drivers with telemetry, so there is nothing to compare.</Empty>
      </>
    );
  }
  if (lapA === null || lapB === null) {
    return (
      <>{sidebar}{header}
        <Section><Warning>One of the selected laps has no stored telemetry.</Warning></Section>
      </>
    );
  }
  if (analysis.error) {
    return (
      <>{sidebar}{header}
        <ErrorState message={analysis.error} onRetry={analysis.retry} />
      </>
    );
  }
  if (!analysis.data) {
    return (
      <>{sidebar}{header}<Loading what="the comparison" /></>
    );
  }

  const a = analysis.data;
  const { summary } = a;
  const coverage = summary.coverage ?? 1;
  const isPartial = coverage < 0.999;

  // A lap the source feed gave no time for — a grid start, or a lap the car
  // did not finish — has no overall gap to report. Without the `has_gap`
  // guard, `gap` is NaN, which renders as "+nan s" and, worse, makes the
  // `gap > 0` test name the *comparison* driver faster on no evidence at all.
  // The corner-by-corner deltas are still real and are still shown; only the
  // total is unknown.
  const gap = a.gap ?? NaN;
  const [faster] = gap > 0
    ? [a.display_a, a.display_b] : [a.display_b, a.display_a];

  const nA = lapsFor(nameA).length;
  const nB = lapsFor(nameB).length;

  const avail = data.availability.summary;
  // Never round an incomplete session up to "100%" while printing the counts
  // that contradict it — 959 of 960 is not 100%.
  const pct = avail.n_missing === 0
    ? '100%' : `${Math.min(avail.coverage * 100, 99.9).toFixed(1)}%`;
  const availHeadline = (
    <><b>{avail.n_stored} of {avail.n_laps}</b> laps driven in this session
      can be compared corner-by-corner ({pct}).</>
  );

  const lapSpread = Math.abs(a.lap_a - a.lap_b);

  return (
    <>
      {sidebar}
      {header}

      {/* ------------------------------------------------------- headline */}
      <Section>
        <Columns>
          <Metric
            label={nameA !== nameB ? `${a.display_a} · lap ${a.lap_a}` : a.display_a}
            value={fmtLaptime(a.time_a)}
          />
          <Metric
            label={nameA !== nameB ? `${a.display_b} · lap ${a.lap_b}` : a.display_b}
            value={fmtLaptime(a.time_b)}
            delta={a.has_gap ? fmtDelta(gap) : undefined}
            deltaColor="inverse"
          />
          <Metric
            label="Gained in corners" value={fmtDelta(summary.corner_delta_s)}
            help={`Total time ${a.display_b} gains (−) or loses (+) inside the corner windows.`}
          />
          <Metric
            label="Gained on straights" value={fmtDelta(summary.straight_delta_s)}
            help="The remainder of the lap: power, drag and slipstream effects."
          />
        </Columns>
      </Section>

      <Section>
        <div className="pw-headline-panel">
          {a.has_gap ? (
            <>
              <b>{faster}</b> is <b>{fmt(Math.abs(gap))} s</b> faster overall.{' '}
            </>
          ) : (
            <>
              The lap that has no time recorded against it —{' '}
              <b>{a.time_a === null ? a.display_a : a.display_b}</b> — leaves
              the overall gap unknown, so no lap is called faster here.{' '}
            </>
          )}
          {isPartial
            ? `Over the ${(coverage * 100).toFixed(0)}% of the lap both cars recorded, the `
            : 'The '}
          corners account for <b>{fmtDelta(summary.corner_delta_s, '')}</b> s and
          the straights for <b>{fmtDelta(summary.straight_delta_s, '')}</b> s.
        </div>
      </Section>

      {/* A partial lap is usable but it is not a like-for-like lap, and the
          reader has to be told which part of the track is simply absent — the
          segment deltas below cannot sum to the lap-time gap when a piece of
          the lap is missing from one of the two traces. */}
      {isPartial && (
        <Section>
          <PartialWarning
            summary={summary}
            parts={[[nameA, a.lap_a], [nameB, a.lap_b]].flatMap(([name, lap]) => {
              const found = (data.driver_laps[name as string] ?? [])
                .find((l) => l.lap === lap);
              if (!found || !KIND_LABEL[found.kind]) return [];
              const cov = (found.cov_end - found.cov_start) * 100;
              return [{
                name: name as string, lap: lap as number,
                kind: KIND_LABEL[found.kind], cov,
              }];
            })}
          />
        </Section>
      )}

      {/* Which lap this is has to be stated, not inferred: get_lap silently
          defaults to a driver's fastest stored lap. */}
      <Section>
        <Caption>
          {nameA} lap {a.lap_a} against {nameB} lap {a.lap_b}.{' '}
          {Math.max(nA, nB) > 1
            ? `${nA} laps stored for ${nameA}, ${nB} for ${nameB} — pick another in the sidebar.`
            : 'Only one lap stored per driver in this session.'}
        </Caption>
      </Section>

      {/* --------------------------------------------- lap availability
          The selector can only offer laps that made it into the telemetry
          artefact, while the lap table holds every lap driven. Where those
          disagree the page has to say so and why: a lap absent from a dropdown
          is otherwise indistinguishable from a lap that was never driven,
          which is the silent-filtering failure the rest of this app is built
          to avoid. */}
      {avail.n_laps > 0 && (
        <Section>
          {/* Only a session that asked for *every* lap has anything to
              apologise for. Qualifying keeps a driver's fastest few by design,
              so its low number is the stated intent rather than a fault, and
              must not be flagged as one. */}
          {avail.stores_all_laps && avail.coverage < COVERAGE_WARN_BELOW && (
            <Warning>
              {availHeadline} This session type stores a trace for every valid
              lap, so the shortfall is missing or unusable telemetry in the
              source feed rather than a choice this tool made — expand below
              for the breakdown.
            </Warning>
          )}
          <Expander label={`Lap availability — ${avail.n_stored} of ${avail.n_laps} laps selectable`}>
            {data.availability.reasons.length === 0 ? (
              <Success>
                Every lap driven in this session has stored telemetry and can be
                selected above.
              </Success>
            ) : (
              <>
                <div>{availHeadline}</div>
                <DataTable<RejectionRow>
                  rows={data.availability.reasons}
                  columns={[
                    { key: 'reason', label: 'Reason' },
                    { key: 'count', label: 'Laps', numeric: true },
                    {
                      key: 'pct_of_input', label: '% of session laps', numeric: true,
                      render: (row) => fmt(row.pct_of_input, 4),
                    },
                  ]}
                />
              </>
            )}
            <Caption>
              Races and sprints store a telemetry trace for every valid lap, so
              a gap here is a gap in the source feed rather than a choice this
              tool made. Qualifying deliberately keeps only each driver's
              fastest few runs. Either way the reason is listed rather than
              left silent.
            </Caption>
          </Expander>
        </Section>
      )}

      {/* When comparing laps far apart, fuel and tyre conditions differ
          significantly. The corner deltas are still real, but they are not a
          like-for-like read on pace, and that has to be said rather than left
          for the reader to notice. */}
      {isRace && lapSpread >= 10 && (
        <Section>
          <Info>
            These laps are <b>{lapSpread} laps apart</b> ({nameA} on lap{' '}
            {a.lap_a}, {nameB} on lap {a.lap_b}). Fuel load and tyre age will
            differ — this is expected for cross-stint comparisons. Use the
            compound filter to compare laps on the same tyre.
          </Info>
        </Section>
      )}

      <Section><Kerb /></Section>

      {/* --------------------------------------- map + biggest swings
          First thing after the headline, and full width: this is the view that
          turns the gap in those metrics into a place on the circuit, and it is
          what a reader who knows the track can answer the whole page from at a
          glance. */}
      <Section>
        <Subheader>Where the time changes hands</Subheader>
        <MapSection
          chartParams={chartParams}
          displayA={a.display_a} displayB={a.display_b}
        />
        <GhostReplay
          track={data.trackmap} tA={a.ghost.t_a} tB={a.ghost.t_b}
          nameA={a.display_a} nameB={a.display_b}
        />
        <Caption>
          The same two laps, replayed against each other. {a.display_a} is the
          ring, {a.display_b} the dot, and each is where that car actually was
          at that moment of its own lap — which is why they sit on top of each
          other: a few tenths is under half a percent of a lap. The leader is
          drawn bright and the car behind dimmed, and the bar below prints the
          interval between them as it stands at that moment of the lap. A glow
          lights on whichever car is taking time out of the other right then, so
          a car can be gaining while still behind. Fullscreen redraws the same
          replay at the height of the screen, where a gap that was four pixels
          becomes one you can see.
        </Caption>
      </Section>

      <Section>
        {/* Same two hues as the track map above — blue where the compared
            driver is gaining, red where the reference is — so the list and the
            map can be read against each other without relearning the colours. */}
        <Columns gap="large">
          <SwingList
            title={`${a.display_b} gains most`}
            items={summary.biggest_gains} colour={theme.series[0]}
          />
          <SwingList
            title={`${a.display_b} loses most`}
            items={summary.biggest_losses} colour={theme.series[7]}
          />
        </Columns>
      </Section>

      <Section><Kerb /></Section>

      {/* ----------------------------------------------------- lap by lap */}
      <Section>
        <Subheader>Lap by lap</Subheader>
        {nameA === nameB ? (
          <Info>
            Lap by lap session comparison is not applicable when comparing a
            driver against themselves.
          </Info>
        ) : a.head_to_head.length === 0 ? (
          <Info>
            No lap table is stored for this session, so there is nothing to
            compare lap by lap.
          </Info>
        ) : (
          <LapByLap analysis={a} nameA={nameA} nameB={nameB} slug={slug} />
        )}
      </Section>

      <Section><Kerb /></Section>

      {/* -------------------------------------------------------- traces */}
      <Section>
        <Subheader>Telemetry</Subheader>
        <PlotlyChart id="trace-panel" params={chartParams} height={820} />
        <Caption>
          {a.display_a} solid, {a.display_b} dashed — the line style carries the
          identity as well as the colour. Dotted verticals mark corner apexes;
          the red bands are {a.display_a}'s braking zones, and the brake panel
          shows both drivers' pedal on/off so an earlier brake release reads as
          a step to the left. In the bottom panel a falling line means{' '}
          {a.display_b} is gaining.
        </Caption>
      </Section>

      <Section><Kerb /></Section>

      {/* ---------------------------------------------- per-corner table */}
      <Section>
        <Subheader>Corner by corner</Subheader>
        <CornerSegments
          chartParams={chartParams} segments={a.segments}
          displayA={a.display_a} displayB={a.display_b} isPartial={isPartial}
        />
        <Caption>
          A positive Δ brake means the compared driver braked later. Blanks are
          corners taken flat — no braking event to report.
        </Caption>
      </Section>
    </>
  );
}

// --------------------------------------------------------------------------
// Lap selector
// --------------------------------------------------------------------------

/**
 * Always render the selector, even when only one lap is stored.
 *
 * `store.get_lap` silently falls back to the driver's fastest lap, so hiding
 * this control left the reader unable to tell which lap they were looking at.
 * A single-lap session shows a disabled control rather than no control at all —
 * the answer to "which lap?" must always be on screen.
 */
function LapSelect(
  { driver, laps, value, isRace, compound, onChange }: {
    driver: string; laps: DriverLap[]; value: number | null;
    isRace: boolean; compound: string | null;
    onChange: (lap: number) => void;
  },
) {
  if (laps.length === 0) {
    return compound
      ? <Info>No {compound} laps stored for {driver}.</Info>
      : null;
  }

  const nPartial = laps.filter((l) => l.kind !== 'flying').length;
  const orderHint = isRace ? 'chronological order' : 'fastest first';
  const partialHint = nPartial
    ? ` ${nPartial} of them are partial (grid start, in- or out-lap) and cover only part of the track.`
    : '';

  const format = (lap: number) => {
    const found = laps.find((l) => l.lap === lap);
    if (!found) return `Lap ${lap}`;
    const compoundTag = found.compound ? ` [${found.compound}]` : '';
    // Kept terse: the sidebar select truncates, and this tag has to survive
    // that. The full wording is in the banner above the charts.
    const short = KIND_SHORT[found.kind];
    const kindTag = short
      ? ` · ${short} ${((found.cov_end - found.cov_start) * 100).toFixed(0)}%`
      : '';
    return `Lap ${lap} — ${fmtLaptime(found.time_s)}${compoundTag}${kindTag}`;
  };

  return (
    <Select
      label={`${driver} lap`}
      options={laps.map((l) => l.lap)}
      value={value ?? laps[0].lap}
      format={format}
      disabled={laps.length === 1}
      help={laps.length === 1
        ? 'Only one lap is stored for this driver in this session.'
        : `${laps.length} laps stored, ${orderHint}.${partialHint}`}
      onChange={onChange}
    />
  );
}

// --------------------------------------------------------------------------

function PartialWarning(
  { summary, parts }: {
    summary: SegmentRow extends never ? never : {
      n_comparable: number; n_segments: number; uncomparable_labels: string[];
    };
    parts: { name: string; lap: number; kind: string; cov: number }[];
  },
) {
  const missing = summary.uncomparable_labels ?? [];
  return (
    <Warning>
      {parts.length > 0
        ? parts.map((p, i) => (
            <span key={p.name + p.lap}>
              {i > 0 && ' and '}
              <b>{p.name} lap {p.lap}</b> is {article(p.kind)} {p.kind} covering{' '}
              {p.cov.toFixed(0)}% of the track
            </span>
          ))
        : 'One of these laps is partial'}
      {'. Comparison runs over the '}
      <b>{summary.n_comparable} of {summary.n_segments} segments</b>
      {' where both cars have telemetry'}
      {missing.length > 0 ? ` — no data for ${missing.join(', ')}.` : '.'}
      {' The segment deltas therefore do '}<b>not</b>{' sum to the lap-time gap.'}
    </Warning>
  );
}

function MapSection(
  { chartParams, displayA, displayB }: {
    chartParams: Record<string, string | number | null>;
    displayA: string; displayB: string;
  },
) {
  const options = [
    'Time delta map', `Speed map (${displayA})`, `Speed map (${displayB})`,
  ];
  const [view, setView] = useState(options[0]);
  const active = options.includes(view) ? view : options[0];

  return (
    <>
      <RadioGroup label="Map view" options={options} value={active} onChange={setView} />
      {active === options[0] ? (
        <>
          <PlotlyChart id="speed-delta-map" params={chartParams} height={620} />
          <Caption>
            The racing line, split into mini-sectors and coloured by which
            driver is pulling away in each. Grey means neither driver is
            gaining.
          </Caption>
        </>
      ) : (
        <>
          <PlotlyChart
            id="speed-map" height={620}
            params={{ ...chartParams, which: active === options[1] ? 'a' : 'b' }}
          />
          <Caption>
            Circuit outline coloured by absolute speed for{' '}
            {active === options[1] ? displayA : displayB}.
          </Caption>
        </>
      )}
    </>
  );
}

function SwingList(
  { title, items, colour }: {
    title: string; items: { label: string; delta_s: number }[]; colour: string;
  },
) {
  return (
    <div>
      <Kicker>{title}</Kicker>
      {items.length === 0 && (
        <div style={{ color: 'var(--ink-3)' }}>—</div>
      )}
      {items.map((item) => (
        <div className="pw-row" key={item.label}>
          <span className="pw-row-label" style={{ color: 'var(--ink)' }}>
            {item.label}
          </span>
          <span className="pw-row-value" style={{ color: colour }}>
            {fmtDelta(item.delta_s)}
          </span>
        </div>
      ))}
    </div>
  );
}

// --------------------------------------------------------------------------

function LapByLap(
  { analysis, nameA, nameB, slug }: {
    analysis: { head_to_head: Record<string, unknown>[] };
    nameA: string; nameB: string; slug: string;
  },
) {
  const h2h = analysis.head_to_head as {
    LapNumber: number; LapTime_s_a: number | null; LapTime_s_b: number | null;
    Compound_a: string | null; Compound_b: string | null;
    delta_s: number | null; cumulative_s: number | null;
  }[];

  const nCommon = h2h.filter((r) => r.delta_s !== null).length;
  const wonA = h2h.filter((r) => (r.delta_s ?? 0) > 0).length;

  // Live-timing colours down the two lap-time columns, read in lap order.
  const states = timingStates(h2h.map((r) => [r.LapTime_s_a, r.LapTime_s_b]));

  const rows = h2h.map((row, i) => ({
    ...row,
    _stateA: states[i][0],
    _stateB: states[i][1],
  }));

  const columns: Column<(typeof rows)[number]>[] = [
    { key: 'LapNumber', label: 'Lap', numeric: true },
    {
      key: 'LapTime_s_a', label: `${nameA} (s)`, numeric: true,
      render: (row) => timingCell(row.LapTime_s_a, row._stateA),
      style: (row) => timingStyle(row._stateA),
    },
    {
      key: 'LapTime_s_b', label: `${nameB} (s)`, numeric: true,
      render: (row) => timingCell(row.LapTime_s_b, row._stateB),
      style: (row) => timingStyle(row._stateB),
    },
    {
      key: 'delta_s', label: 'Δ (s)', numeric: true, gradient: true,
      render: (row) => fmt(row.delta_s),
    },
    {
      key: 'cumulative_s', label: 'Running (s)', numeric: true,
      render: (row) => fmt(row.cumulative_s),
    },
    { key: 'Compound_a', label: `${nameA} tyre` },
    { key: 'Compound_b', label: `${nameB} tyre` },
  ];

  return (
    <>
      <PlotlyChart
        id="lap-by-lap" height={700}
        params={{ slug, driver1: nameA, driver2: nameB }}
      />
      <Caption>
        Every lap both drivers ran — not just the one analysed above. {nameA}{' '}
        solid, {nameB} dashed; triangles mark pit laps. In the middle panel a
        bar above the line is a lap {nameA} won, below one {nameB} won. Where
        the running total steps sharply, look for a pit marker or a safety car
        before reading it as pace.
      </Caption>

      <Columns>
        <Metric label="Laps compared" value={String(nCommon)} />
        {nCommon > 0 && <Metric label={`Laps ${nameA} quicker`} value={String(wonA)} />}
        {nCommon > 0 && (
          <Metric label={`Laps ${nameB} quicker`} value={String(nCommon - wonA)} />
        )}
      </Columns>

      <DataTable rows={rows} columns={columns} height={380} />
      <Caption>
        <b>SB</b> in purple is the quickest lap either driver had set at that
        point; <b>PB</b> in green is a driver's own best so far; yellow is a lap
        slower than their own best — the television timing convention, with the
        letters there so the colour never has to carry it alone. A blank means
        only one of them completed that lap, so it scores no delta. This table
        covers the whole session, while the corner-level analysis above is
        limited to the laps that have stored telemetry.
      </Caption>
    </>
  );
}

// --------------------------------------------------------------------------

function CornerSegments(
  { chartParams, segments, displayA, displayB, isPartial }: {
    chartParams: Record<string, string | number | null>;
    segments: SegmentRow[];
    displayA: string; displayB: string; isPartial: boolean;
  },
) {
  const [onlyCorners, setOnlyCorners] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);

  const view = onlyCorners ? segments.filter((s) => s.kind === 'corner') : segments;

  const columns: Column<SegmentRow>[] = [
    { key: 'label', label: 'Segment' },
    {
      key: 'delta_s', label: 'Δ time (s)', numeric: true, gradient: true,
      render: (row) => fmt(row.delta_s),
    },
    {
      key: 'cum_delta_s', label: 'Cum Δ (s)', numeric: true,
      render: (row) => fmt(row.cum_delta_s),
    },
    {
      key: 'v_min_a', label: `Min speed ${displayA}`, numeric: true,
      render: (row) => fmt(row.v_min_a, 0),
    },
    {
      key: 'v_min_b', label: `Min speed ${displayB}`, numeric: true,
      render: (row) => fmt(row.v_min_b, 0),
    },
    {
      key: 'v_min_diff', label: 'Δ min speed', numeric: true,
      render: (row) => fmt(row.v_min_diff, 1),
    },
    {
      key: 'brake_m_a', label: `Brake point ${displayA} (m)`, numeric: true,
      render: (row) => fmt(row.brake_m_a, 0),
    },
    {
      key: 'brake_m_b', label: `Brake point ${displayB} (m)`, numeric: true,
      render: (row) => fmt(row.brake_m_b, 0),
    },
    {
      key: 'brake_m_diff', label: 'Δ brake (m)', numeric: true,
      render: (row) => fmt(row.brake_m_diff, 0),
    },
  ];

  return (
    <>
      <PlotlyChart
        id="corner-delta-bars" params={chartParams} height={460}
        onPointClick={(event) => {
          const labels = event.points
            .map((p) => (p.y ?? p.x))
            .filter((v): v is string => typeof v === 'string');
          setSelected(labels.length ? joinProse(labels, 'and') : null);
        }}
      />
      {selected && <Info>Selected segment: <b>{selected}</b></Info>}

      <Caption>
        {isPartial
          ? 'Time won or lost in every segment where both cars have telemetry.'
          : 'Time won or lost in every segment of the lap. Click bars to inspect segment detail.'}
      </Caption>

      <Toggle label="Corners only" value={onlyCorners} onChange={setOnlyCorners} />
      <DataTable rows={view} columns={columns} height={560} />
    </>
  );
}
