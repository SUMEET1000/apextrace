/** Race Arc & Strategy: consolidated tyre degradation, track evolution, and
 *  race strategy analysis. */

import { useState } from 'react';
import { SessionHeader } from '../components/brand/SessionHeader';
import { PlotlyChart } from '../components/PlotlyChart';
import { SidebarSection } from '../components/Sidebar';
import { DataTable, type Column } from '../components/ui/DataTable';
import {
  Caption, Columns, Expander, Info, Kerb, Kicker, Metric, Section, Slider,
  Stack, Subheader, Success, Tabs, Verdict, Warning, MultiSelect,
} from '../components/ui/primitives';
import { Empty, ErrorState, Loading } from '../components/states';
import {
  fetchRaceArc, fetchSession, fetchUndercut, useAsync,
} from '../lib/api';
import { fmt, fmtDelta, fmtInt, fmtPercent, titleCase } from '../lib/format';
import { useQueryParams } from '../lib/router';
import { useTheme } from '../lib/theme';
import type { Selection } from '../components/SessionPicker';
import type {
  CompoundSummaryRow, RaceArcResponse, RejectionRow,
} from '../lib/types';

const VIEWS = ['Tyre Degradation', 'Track Evolution', 'Race Strategy'];

/** The 2026 regulations cut race fuel substantially. */
const RACE_FUEL_KG: Record<number, number> = { 2024: 110, 2025: 110, 2026: 70 };
const DEFAULT_RACE_FUEL_KG = 100;

export function RaceArcPage({ selection }: { selection: Selection }) {
  const { slug, meta } = selection;
  const { params, update } = useQueryParams();
  const theme = useTheme();

  const session = useAsync((s) => fetchSession(slug, s), [slug]);

  // ---- model assumptions ------------------------------------------------
  const [fuelEffect, setFuelEffect] = useState(theme.fuel_effect_s_per_kg);
  const defaultFuel = RACE_FUEL_KG[meta.year] ?? DEFAULT_RACE_FUEL_KG;
  const [fuelKg, setFuelKg] = useState(defaultFuel);

  const arc = useAsync(
    (s) => fetchRaceArc(slug, fuelEffect, fuelKg, s),
    [slug, fuelEffect, fuelKg],
  );

  const wanted = params.get('view') ?? VIEWS[0];
  const view = VIEWS.includes(wanted) ? wanted : VIEWS[0];

  const sidebar = (
    <SidebarSection>
      <Kicker>Model assumptions</Kicker>
      <Slider
        label="Fuel effect (s per kg)"
        min={0.020} max={0.045} step={0.001} value={fuelEffect}
        format={(v) => v.toFixed(3)} onChange={setFuelEffect}
        help="Lap time gained per kg of fuel burned. Community estimates sit around 0.030–0.035 and vary by circuit."
      />
      <Slider
        label="Starting fuel (kg)"
        min={40} max={120} step={5} value={fuelKg}
        format={(v) => v.toFixed(1)} onChange={setFuelKg}
        help="The 2026 regulations cut race fuel substantially."
      />
    </SidebarSection>
  );

  if (session.error) {
    return <ErrorState message={session.error} onRetry={session.retry} />;
  }
  if (!session.data) {
    return <Loading what="the session" />;
  }
  if (session.data.drivers.length === 0) {
    return <Empty>This session has no drivers stored, so there is no race to analyse.</Empty>;
  }

  const header = (
    <Section>
      <SessionHeader
        meta={meta} sessionLabel={session.data.session_label}
        pageTitle="Race Arc & Strategy" track={session.data.trackmap} showCorners
      />
    </Section>
  );

  if (arc.error) {
    return (<>{sidebar}{header}<ErrorState message={arc.error} onRetry={arc.retry} /></>);
  }
  if (!arc.data) {
    return (
      <>{sidebar}{header}<Loading what="the race analysis" /></>
    );
  }

  const chartParams = { slug, fuel_effect: fuelEffect, fuel_kg: fuelKg };

  return (
    <>
      {sidebar}
      {header}
      <Section>
        <Tabs tabs={VIEWS} active={view} onChange={(next) => update({ view: next })} />
      </Section>

      {view === VIEWS[0] && <DegradationTab arc={arc.data} chartParams={chartParams} />}
      {view === VIEWS[1] && <EvolutionTab arc={arc.data} chartParams={chartParams} />}
      {view === VIEWS[2] && <StrategyTab arc={arc.data} chartParams={chartParams} />}
    </>
  );
}

type ChartParams = Record<string, string | number>;

// ==========================================================================
// TAB 1: TYRE DEGRADATION
// ==========================================================================

function DegradationTab(
  { arc, chartParams }: { arc: RaceArcResponse; chartParams: ChartParams },
) {
  if (!arc.is_race) {
    return (
      <Section>
        <Info>
          Degradation is measured over a race stint. Pick a <b>Race</b> session
          in the session picker — qualifying sessions do not contain long runs.
        </Info>
      </Section>
    );
  }

  const { summary, stints, rejections, n_prepared: nPrepared, n_all_laps: nAll,
          n_cliffs: nCliffs } = arc.degradation;

  if (nPrepared === 0) {
    return <Section><Warning>No laps survived cleaning for this session.</Warning></Section>;
  }

  const softest = summary[0];
  const hardest = summary[summary.length - 1];

  const stintColumns: Column<Record<string, unknown>>[] = [
    { key: 'Driver' },
    { key: 'Stint', numeric: true },
    { key: 'Compound', label: 'Tyre' },
    { key: 'n_laps', label: 'Laps', numeric: true },
    { key: 'deg_s_per_lap', label: 'Deg (s/lap)', numeric: true,
      render: (r) => fmt(r.deg_s_per_lap as number) },
    { key: 'ci_low', label: '95% CI low', numeric: true,
      render: (r) => fmt(r.ci_low as number) },
    { key: 'ci_high', label: '95% CI high', numeric: true,
      render: (r) => fmt(r.ci_high as number) },
    { key: 'r_squared', label: 'R²', numeric: true,
      render: (r) => fmt(r.r_squared as number, 2) },
    { key: 'has_cliff', label: 'Cliff' },
  ];

  return (
    <>
      <Section>
        <Columns>
          {summary.map((row: CompoundSummaryRow) => (
            <Metric
              key={row.Compound}
              label={`${titleCase(row.Compound)} degradation`}
              value={`${fmt(row.deg_s_per_lap)} s/lap`}
              delta={`95% CI ${fmt(row.ci_low)} – ${fmt(row.ci_high)}`}
              help={`${row.n_stints} stints, ${row.n_laps} laps.`}
            />
          ))}
          <Metric
            label="Clean laps used" value={fmtInt(nPrepared)}
            delta={`${fmtPercent(nPrepared / Math.max(nAll, 1))} of all laps`}
          />
        </Columns>
      </Section>

      {summary.length > 1 && (
        <Section>
          <Verdict>
            The <b>{softest.Compound.toLowerCase()}</b> gives up{' '}
            <b>{fmt(softest.deg_s_per_lap)} s/lap</b> and the{' '}
            <b>{hardest.Compound.toLowerCase()}</b>{' '}
            <b>{fmt(hardest.deg_s_per_lap)} s/lap</b> — a difference of{' '}
            {fmt(Math.abs(softest.deg_s_per_lap - hardest.deg_s_per_lap))} s per
            lap of stint length.
          </Verdict>
        </Section>
      )}

      <Section><Kerb /></Section>

      <Section>
        <Subheader>Pace against tyre age</Subheader>
        <PlotlyChart id="degradation-scatter" params={chartParams} height={480} />
        <Caption>
          Each point is one clean lap, fuel-corrected to end-of-race weight; the
          line is the inverse-variance weighted fit across all stints on that
          compound.
        </Caption>
      </Section>

      <Section>
        <Columns ratios={[2, 3]} gap="large">
          <Stack>
            <Subheader>Degradation rate</Subheader>
            <PlotlyChart id="degradation-bars" params={chartParams} height={340} />
            <Caption>
              Bars show the pooled rate; whiskers are 95% confidence intervals.
            </Caption>
          </Stack>
          <Stack>
            <Subheader>What was excluded, and why</Subheader>
            {rejections.length === 0 ? (
              <Success>Every lap passed the cleaning filters.</Success>
            ) : (
              <DataTable<RejectionRow>
                rows={rejections}
                columns={[
                  { key: 'reason', label: 'Reason' },
                  { key: 'count', label: 'Laps', numeric: true },
                  { key: 'pct_of_input', label: '% of all laps', numeric: true,
                    render: (r) => fmt(r.pct_of_input, 4) },
                ]}
              />
            )}
            <Caption>
              Traffic, safety cars, and pit laps are listed explicitly rather
              than filtered silently.
            </Caption>
          </Stack>
        </Columns>
      </Section>

      <Section><Kerb /></Section>

      <Section>
        <Subheader>Stint by stint</Subheader>
        {nCliffs > 0 && (
          <div style={{ color: 'var(--ink-2)' }}>
            <b style={{ color: 'var(--ink)' }}>{nCliffs}</b> of {stints.length}{' '}
            stints show a statistically better quadratic fit with upward
            curvature — degradation accelerating rather than holding a constant
            rate.
          </div>
        )}
        {stints.length === 0
          ? <Info>No stint had enough clean laps to fit.</Info>
          : <DataTable rows={stints} columns={stintColumns} height={420} />}
      </Section>
    </>
  );
}

// ==========================================================================
// TAB 2: TRACK EVOLUTION
// ==========================================================================

function EvolutionTab(
  { arc, chartParams }: { arc: RaceArcResponse; chartParams: ChartParams },
) {
  const why = (
    <Section>
      <Expander label="Why track evolution needs a model, not a trend line">
        <div>
          <p style={{ marginTop: 0 }}>
            Within a single stint, tyre age and session time are collinear.
            Across the field, staggered pit stops decorrelate tyre age from
            session time:
          </p>
          <pre style={{
            background: 'rgba(0,0,0,.35)', borderRadius: '.35rem',
            padding: '.7rem .9rem', overflowX: 'auto', fontSize: '.85rem',
          }}>
            corrected_laptime ~ C(Driver) + C(Compound):TyreLife + spline(progress)
          </pre>
          <ul style={{ margin: '.6rem 0 0', paddingLeft: '1.2rem' }}>
            <li><code>C(Driver)</code> absorbs raw pace differences between cars</li>
            <li><code>C(Compound):TyreLife</code> absorbs degradation per compound</li>
            <li><code>spline(progress)</code> isolates track rubbering-in</li>
          </ul>
        </div>
      </Expander>
    </Section>
  );

  if (!arc.is_race) {
    return (
      <>
        {why}
        <Section>
          <Subheader>Session best over time</Subheader>
          {!arc.evolution.has_progression ? (
            <Info>No timing data to plot.</Info>
          ) : (
            <>
              <PlotlyChart id="session-best" params={{ slug: chartParams.slug }} height={440} />
              <Caption>
                The session best improved by{' '}
                {fmt(arc.evolution.session_best_gain ?? null)} s during the
                qualifying session.
              </Caption>
            </>
          )}
        </Section>
      </>
    );
  }

  if (arc.degradation.n_prepared === 0) {
    return (
      <>{why}
        <Section><Warning>Not enough clean laps to fit track evolution model.</Warning></Section>
      </>
    );
  }

  const { result, naive_gain: naiveGain } = arc.evolution;
  if (!result) {
    return (
      <>{why}
        <Section>
          <Warning>
            This session does not support the pooled model — it needs at least
            40 clean laps across 4 drivers with varied stint timing.
          </Warning>
        </Section>
      </>
    );
  }

  const gain = result.total_gain_s;
  const naive = naiveGain ?? NaN;
  const wrongDirection = (naive < 0) !== (gain < 0);

  const degColumns: Column<Record<string, unknown>>[] = [
    { key: 'Compound' },
    { key: 'deg_s_per_lap', label: 'Deg (s/lap)', numeric: true,
      render: (r) => fmt(r.deg_s_per_lap as number) },
    { key: 'ci_low', label: '95% CI low', numeric: true,
      render: (r) => fmt(r.ci_low as number) },
    { key: 'ci_high', label: '95% CI high', numeric: true,
      render: (r) => fmt(r.ci_high as number) },
  ];

  return (
    <>
      {why}

      <Section>
        <Columns>
          <Metric
            label="Track evolution" value={fmtDelta(gain, '')}
            delta={gain > 0 ? 'faster by end' : 'slower by end'}
          />
          <Metric
            label="Naive estimate" value={fmtDelta(naive, '')}
            delta={wrongDirection
              ? 'wrong direction'
              : `off by ${fmt(Math.abs(naive - gain))} s`}
          />
          <Metric
            label="Model fit" value={`R² ${fmt(result.r_squared)}`}
            delta={`${fmtInt(result.n_laps)} laps · ${result.n_drivers} drivers`}
          />
          <Metric label="Spline knots" value="4 bends" delta="cubic spline" />
        </Columns>
      </Section>

      <Section>
        <Verdict>
          With tyre age and fuel accounted for, the circuit itself was worth{' '}
          <b>{fmt(Math.abs(gain))} s</b> of lap time by the end of the race. A
          naive trend through the same laps reports{' '}
          <b>{fmtDelta(naive, '')}</b> —{' '}
          {wrongDirection
            ? 'the opposite direction. Degradation dominates raw lap times.'
            : 'a different figure due to tyre wear and fuel burn.'}
        </Verdict>
      </Section>

      <Section><Kerb /></Section>

      <Section>
        <Subheader>Evolution curve</Subheader>
        <PlotlyChart id="evolution-curve" params={chartParams} height={420} />
        <Caption>Falling line indicates rubbering-in. Dashed line is naive trend.</Caption>
      </Section>

      <Section><Kerb /></Section>

      <Section>
        <Columns ratios={[3, 2]} gap="large">
          <Stack>
            <Subheader>Evolution against track temperature</Subheader>
            <PlotlyChart id="evolution-temperature" params={chartParams} height={520} />
            <Caption>
              Stacked panels sharing an x-axis prevent dual-axis scaling
              distortions.
            </Caption>
          </Stack>
          <Stack>
            <Subheader>Degradation implied by model</Subheader>
            {result.degradation.length === 0
              ? <Info>No compound terms estimated.</Info>
              : <DataTable rows={result.degradation} columns={degColumns} />}
          </Stack>
        </Columns>
      </Section>
    </>
  );
}

// ==========================================================================
// TAB 3: RACE STRATEGY
// ==========================================================================

function StrategyTab(
  { arc, chartParams }: { arc: RaceArcResponse; chartParams: ChartParams },
) {
  if (!arc.is_race) {
    return <Section><Info>Strategy analysis requires a <b>Race</b> session.</Info></Section>;
  }

  const s = arc.strategy;
  const loss = s.pit_loss ?? {};
  const pace = s.pace_display ?? [];
  const gapDrivers = s.gap_drivers ?? [];

  return (
    <>
      <Section>
        <Columns>
          <Metric
            label="Pit loss" value={`${fmt(loss.pit_loss_s ?? null, 1)} s`}
            delta={`in-lap ${fmt(loss.in_lap_s ?? 0, 1)}s + out-lap ${fmt(loss.out_lap_s ?? 0, 1)}s`}
          />
          <Metric label="Pit stops" value={String(loss.n_stops ?? 0)} />
          {pace.length > 0 && (
            <Metric
              label="Best race pace" value={String(pace[0].Driver)}
              delta={`${pace[0].Median} median`}
            />
          )}
          <Metric label="Stints" value={String(s.n_stints ?? 0)} />
        </Columns>
      </Section>

      <Section><Kerb /></Section>

      <Section>
        <Subheader>Stint timeline</Subheader>
        <PlotlyChart id="stint-chart" params={{ slug: chartParams.slug }} height={640} />
        <Caption>Each bar represents a stint, ordered by distance completed.</Caption>
      </Section>

      <Section><Kerb /></Section>

      <Section>
        <Columns ratios={[3, 2]} gap="large">
          <Stack>
            <Subheader>Race pace distribution</Subheader>
            <PlotlyChart id="race-pace-box" params={chartParams} height={520} />
            <Caption>
              Fuel-corrected clean lap time distributions, ordered by median pace.
            </Caption>
          </Stack>
          <Stack>
            <Subheader>Pace ranking</Subheader>
            {pace.length === 0 ? (
              <Info>Not enough clean laps.</Info>
            ) : (
              <DataTable
                rows={pace} height={380}
                columns={[
                  { key: 'Driver' },
                  { key: 'Laps', numeric: true },
                  { key: 'Median', numeric: true },
                  { key: 'Gap', numeric: true },
                ]}
              />
            )}
          </Stack>
        </Columns>
      </Section>

      <Section><Kerb /></Section>

      <Section>
        <Subheader>Gap to leader</Subheader>
        <GapSection slug={String(chartParams.slug)} drivers={gapDrivers} />
        <Caption>
          Cumulative time behind the race leader throughout the race.
        </Caption>
      </Section>

      <Section><Kerb /></Section>

      <Section>
        <Subheader>Position changes</Subheader>
        <PlotlyChart id="position-chart" params={{ slug: chartParams.slug }} height={560} />
        <Caption>Track position lap by lap.</Caption>
      </Section>

      <Section><Kerb /></Section>

      <Section>
        <Subheader>Undercut calculator</Subheader>
        <Verdict>
          <b>Pit loss cancels out in an undercut comparison.</b> Both drivers
          pay the same pit stop penalty; what decides the undercut is the fresh
          tyre delta accrued on the in-lap, out-lap, and push lap.
        </Verdict>
        <UndercutSection
          defaultDeg={s.default_deg_rate ?? 0.10}
          defaultAdvantage={s.default_advantage ?? 0.8}
        />
        <Caption>
          The per-lap gain decays as the fresh tyre ages. Where the curve
          crosses the gap line, the undercut succeeds.
        </Caption>
      </Section>
    </>
  );
}

/** Streamlit ran this in an `@st.fragment` so a driver change redrew only the
 *  chart. Local state does the same. */
function GapSection({ slug, drivers }: { slug: string; drivers: string[] }) {
  const [chosen, setChosen] = useState<string[]>(() => drivers.slice(0, 5));
  return (
    <>
      <MultiSelect
        label="Drivers to compare" options={drivers}
        value={chosen.filter((d) => drivers.includes(d))} onChange={setChosen}
      />
      <PlotlyChart
        id="gap-chart" height={480}
        params={{ slug, drivers: chosen.join(',') }}
      />
    </>
  );
}

function UndercutSection(
  { defaultDeg, defaultAdvantage }:
  { defaultDeg: number; defaultAdvantage: number },
) {
  const [gapS, setGapS] = useState(1.5);
  const [advantage, setAdvantage] = useState(
    () => Number(defaultAdvantage.toFixed(2)));
  const [degRate, setDegRate] = useState(() => Number(defaultDeg.toFixed(2)));

  const result = useAsync(
    (s) => fetchUndercut(gapS, advantage, degRate, s),
    [gapS, advantage, degRate],
  );

  if (result.error) {
    return <ErrorState message={result.error} onRetry={result.retry} />;
  }
  const breakeven = result.data?.breakeven_lap ?? null;
  const maxGain = result.data?.max_gain ?? 0;

  return (
    <>
      <Columns>
        <Slider
          label="Gap to rival (s)" min={0} max={8} step={0.1} value={gapS}
          format={(v) => v.toFixed(1)} onChange={setGapS}
          help="How far behind you are before stopping."
        />
        <Slider
          label="Fresh-tyre advantage (s/lap)" min={0.1} max={2.5} step={0.1}
          value={advantage} format={(v) => v.toFixed(2)} onChange={setAdvantage}
          help="Estimated fresh tyre pace gain (default derived from compound fits)."
        />
        <Slider
          label="Degradation (s/lap)" min={0.01} max={0.40} step={0.01}
          value={degRate} format={(v) => v.toFixed(2)} onChange={setDegRate}
          help={`Defaults to race measured mean of ${fmt(defaultDeg)} s/lap.`}
        />
      </Columns>

      <Columns ratios={[1, 2]}>
        <Stack>
          {breakeven ? (
            <Metric
              label="Undercut works after" value={`${breakeven} laps`}
              delta={`max gain ${fmt(maxGain, 2)} s`}
            />
          ) : (
            <Metric
              label="Undercut works after" value="never"
              delta={`max gain ${fmt(maxGain, 2)} s < ${gapS.toFixed(1)} s gap`}
            />
          )}
        </Stack>
        <PlotlyChart
          id="undercut-chart" height={400}
          params={{ gap_s: gapS, advantage, deg_rate: degRate }}
        />
      </Columns>
    </>
  );
}
