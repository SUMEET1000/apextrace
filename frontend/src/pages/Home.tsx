/** ApexTrace — product-led home page and selected-session overview. */

import { useMemo } from 'react';
import { CircuitReel, CircuitSvg } from '../components/brand/CircuitArt';
import { DataTable, type Column } from '../components/ui/DataTable';
import {
  Caption, Columns, FlagStrip, Info, Kerb, Kicker, Metric, Section,
  SectionIntro, Stack,
} from '../components/ui/primitives';
import { useMetaTags } from '../hooks/useMetaTags';
import { fetchCircuits, fetchHome, fetchSession, useAsync } from '../lib/api';
import { fmtInt } from '../lib/format';
import { Link, withParams } from '../lib/router';
import type { Selection } from '../components/SessionPicker';
import type { FeaturedSession } from '../lib/types';

/** The four workflows, as the questions they answer. */
const CARDS = [
  ['01', 'Where was the lap time won?',
    'Compare two drivers on the same lap and see segment deltas, braking ' +
    'points, apex speed, throttle trace, and whether the corners or ' +
    'straights made the difference.'],
  ['02', 'How fast is each compound fading?',
    'Estimate fuel-corrected degradation by stint and compound, with ' +
    'confidence intervals that show whether a trend is signal or noise.'],
  ['03', 'What pace came from the circuit?',
    'Separate tyre wear and fuel burn from the track rubbering in, using ' +
    'the staggered pit stops that make the effects identifiable.'],
  ['04', 'When does the undercut work?',
    'Combine measured pit loss, compound offsets, stint pace, and tyre age ' +
    'to test the strategic window instead of guessing from lap charts.'],
] as const;

const PROOFS = (gridPoints: number) => [
  ['Official feed',
    'FastF1 wraps the Formula 1 timing feed: laps, sectors, tyres, ' +
    'positions, and telemetry.'],
  ['Distance grid',
    `Telemetry is resampled to ${gridPoints} points per lap so driver ` +
    'traces align by track position.'],
  ['Timing validation',
    'The pipeline is checked against official sector times, with ' +
    'sector-line agreement reported to within metres.'],
  ['Visible assumptions',
    'Fuel correction, rejected laps, pit loss, and tyre-age effects are ' +
    'exposed rather than hidden inside charts.'],
] as const;

const ArrowIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);

export function HomePage(
  { selection, featured }:
  { selection: Selection; featured: FeaturedSession[]; search: string },
) {
  const { slug, meta } = selection;

  const home = useAsync((s) => fetchHome(slug, s), [slug]);
  const session = useAsync((s) => fetchSession(slug, s), [slug]);
  const circuits = useAsync((s) => fetchCircuits(s), []);

  useMetaTags(
    'ApexTrace — F1 telemetry, made readable',
    'Corner-by-corner driver comparison, tyre degradation with confidence ' +
    'intervals, and track evolution separated from the tyre and fuel effects ' +
    'it is normally confounded with. Built on the official F1 timing feed.',
  );

  const queryParams = {
    year: String(meta.year),
    round: String(meta.round),
    session: meta.session,
  };

  // The hero art cycles through every circuit in the dataset, leading with the
  // one currently selected in the sidebar so the page still opens on the
  // session it is describing. Falls back to the single static outline if the
  // manifest only knows one circuit.
  const reel = useMemo(() => {
    const all = circuits.data?.circuits ?? [];
    const lead = home.data?.circuit_lead;
    if (!lead) return all;
    const first = all.filter((c) => c.name === lead);
    return [...first, ...all.filter((c) => c.name !== lead)];
  }, [circuits.data, home.data?.circuit_lead]);

  const label = home.data?.session_label ?? meta.session;

  return (
    <>
      {/* ------------------------------------------------------------ hero */}
      <Section>
        <div className="pw-hero pw-home-hero">
          <div className="pw-hero-text">
            <div className="pw-kicker">Formula 1 timing feed, made readable</div>
            <h1>ApexTrace</h1>
            <div className="pw-home-copy">
              Find where a lap was won, how quickly tyres fade, how much the
              track came in, and whether the strategy call is worth the risk.
              ApexTrace turns official F1 telemetry into race-engineering
              answers a fan, analyst, or team-side storyteller can use
              immediately.
            </div>
            <div className="pw-home-session">
              <span className="pw-home-pill">Now viewing</span>
              <span>{meta.event_name}</span>
              <span>{label} - {meta.location}, {meta.country}</span>
              <span>{meta.year}</span>
            </div>
          </div>
          {/* After the copy in the DOM as well as on screen: the outline is
              labelled artwork, so reading order and visual order should agree
              rather than being swapped back with `order`. */}
          <div className="pw-hero-art">
            {reel.length > 0
              ? <CircuitReel circuits={reel} width={430} height={280} />
              : <CircuitSvg track={session.data?.trackmap} width={430} height={280} />}
          </div>
        </div>
      </Section>

      <Section>
        <div className="pw-home-actions" />
        <Columns>
          <Link to={withParams('/corner-analysis', queryParams)} className="pw-page-link">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 3v18h18M7 15l3-4 3 3 5-7" />
            </svg>
            Corner Analysis
          </Link>
          <Link to={withParams('/race-arc', queryParams)} className="pw-page-link">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 12h4l3 8 4-16 3 8h4" />
            </svg>
            Race Arc &amp; Strategy
          </Link>
        </Columns>
      </Section>

      {/* ------------------------------------------------------ proof strip */}
      <Section>
        <Columns>
          <Metric
            label="Fastest lap"
            value={home.data?.fastest?.lap_time ?? '-'}
            delta={home.data?.fastest?.driver}
          />
          <Metric label="Drivers" value={fmtInt(meta.n_drivers)} />
          <Metric label="Laps recorded" value={fmtInt(meta.n_laps)} />
          {home.data?.track_temp ? (
            <Metric
              label="Track temp"
              value={`${home.data.track_temp.mean.toFixed(1)}C`}
              delta={`${home.data.track_temp.swing >= 0 ? '+' : '-'}${
                Math.abs(home.data.track_temp.swing).toFixed(1)}C over session`}
            />
          ) : (
            <Metric label="Track temp" value="-" />
          )}
        </Columns>
      </Section>

      <Section><Kerb /></Section>

      {/* -------------------------------------------------------- workflows */}
      <Section>
        <Kicker>Choose an analysis workflow</Kicker>
        <SectionIntro>
          Start with the question you are trying to answer. Each workflow keeps
          the current session from the sidebar, so the same event context
          follows you through the app.
        </SectionIntro>
        <Columns>
          {CARDS.map(([num, title, body]) => (
            <div className="pw-feature-card" key={num}>
              <div className="pw-card-num">{num}</div>
              <div className="pw-feature-question">{title}</div>
              <div className="pw-card-body">{body}</div>
            </div>
          ))}
        </Columns>
      </Section>

      <Section><Kerb /></Section>

      {/* ---------------------------------------------- featured comparisons
          Worked examples that used to exist only in the README, where a reader
          with a browser open never saw them. Each link is an ordinary deep
          link — the same query string the sidebar writes — so it lands on the
          page with the session and the drivers already chosen. */}
      {featured.length > 0 && (
        <>
          <Section>
            <Kicker>Featured comparisons</Kicker>
            <SectionIntro>
              Three sessions where the analysis has a visible answer, if you
              would rather start from a result than from a session picker.
            </SectionIntro>
            <Columns>
              {featured.map((item, i) => {
                const [year, rest] = item.slug.split('/');
                const [round, sessionType] = rest.split('_');
                return (
                  <Stack key={`${item.slug}-${i}`}>
                    <div className="pw-feature-card" style={{ minHeight: 150 }}>
                      <div className="pw-feature-question">{item.title}</div>
                      <div className="pw-card-body">{item.blurb}</div>
                    </div>
                    <Link
                      className="pw-page-link"
                      to={withParams(item.route, {
                        year: String(Number(year)),
                        round: String(Number(round)),
                        session: sessionType,
                        ...item.params,
                      })}
                    >
                      Open this analysis <ArrowIcon />
                    </Link>
                  </Stack>
                );
              })}
            </Columns>
          </Section>
          <Section><Kerb /></Section>
        </>
      )}

      {/* -------------------------------------------------- session snapshot */}
      <Section>
        <Kicker>Selected session snapshot</Kicker>
        <SectionIntro>
          A quick read on the session currently loaded from the sidebar. These
          tables are proof that the homepage is using real race data, not
          static marketing copy.
        </SectionIntro>
        <Columns ratios={[3, 2]} gap="large">
          <Stack>
            <Kicker muted>Classification</Kicker>
            <Classification home={home.data} />
          </Stack>
          <Stack>
            <Kicker muted>Fastest lap per driver</Kicker>
            <FastestPerDriver home={home.data} />
          </Stack>
        </Columns>
      </Section>

      {/* ------------------------------------------------------- trust band */}
      <Section>
        <Kicker>Why the numbers are trustworthy</Kicker>
        <div className="pw-proof-band">
          {PROOFS(meta.grid_points).map(([title, body]) => (
            <div className="pw-proof" key={title}>
              <div className="pw-proof-title">{title}</div>
              <div className="pw-proof-body">{body}</div>
            </div>
          ))}
        </div>
      </Section>

      <Section><FlagStrip /></Section>
    </>
  );
}

// --------------------------------------------------------------------------

type HomeData = ReturnType<typeof useAsync<Awaited<ReturnType<typeof fetchHome>>>>['data'];

function Classification({ home }: { home: HomeData }) {
  if (!home) return <div className="pw-chart-skeleton" style={{ height: 360 }} />;
  if (home.classification.length === 0) {
    return <Info>No results available for this session.</Info>;
  }
  const columns: Column<Record<string, unknown>>[] = home.classification_columns
    .map((key) => ({
      key,
      numeric: key === 'Pos' || key === 'Points',
    }));
  return <DataTable rows={home.classification} columns={columns} height={360} />;
}

function FastestPerDriver({ home }: { home: HomeData }) {
  if (!home) return <div className="pw-chart-skeleton" style={{ height: 360 }} />;
  if (home.fastest_per_driver.length === 0) return <Info>No lap data.</Info>;

  // Broadcast timing colours: purple for the session best, green for a
  // personal best. Every row here *is* a driver's own best lap, so the top row
  // is the only purple one — which is exactly what a timing screen shows. The
  // status is spelled out in its own column as well, because two saturated
  // hues are not an encoding on their own.
  const ink = (_row: Record<string, string>, index: number) =>
    index === 0
      ? { color: 'var(--timing-session-best)', fontWeight: 600 }
      : { color: 'var(--timing-personal-best)' };

  const columns: Column<Record<string, string>>[] = [
    { key: 'Driver' },
    { key: 'Lap time', numeric: true, style: ink },
    { key: 'Gap', numeric: true },
    { key: 'Tyre' },
    { key: 'Status', style: ink },
  ];

  return (
    <>
      <DataTable rows={home.fastest_per_driver} columns={columns} height={360} />
      <Caption>
        Purple is the fastest lap of the session, green a driver's own best —
        the same convention as the television timing screen, with the status
        written out beside it rather than left to the colour. Tyre compound is
        shown as text too, because official compound colours collapse for some
        colour-vision conditions.
      </Caption>
    </>
  );
}
