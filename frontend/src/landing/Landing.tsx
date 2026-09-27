/** The landing at `/`: landings/08-finished.html, ported.
 *
 * The markup is 08's. Every sentence that states a number or a position is a
 * template over facts.json (Phase 2B D3), and "pole" is attached only to the
 * driver in P1 - 08 called the gap to Verstappen a pole margin, but Verstappen
 * qualified 4th and a pole margin is measured to P2. The motion is 08's own code, run by
 * boot.ts; the guide car loads only at >= 860 px without reduced motion.
 */

import { useEffect, useRef, type CSSProperties } from 'react';
import { Term } from '../components/Term';
import { Link } from '../lib/router';
import { boot } from './boot';
import F from './facts.json';
import { HERO_IMAGE } from './loader';
import './landing.css';

const s3 = (v: number) => v.toFixed(3);
const s1 = (v: number) => v.toFixed(1);
const signed = (v: number) => (v < 0 ? '−' : '+') + s3(Math.abs(v));
const surname = (name: string) => name.split(' ').slice(-1)[0];
const ordinal = (n: number) => n + (['th', 'st', 'nd', 'rd'][n % 100 > 10 && n % 100 < 14 ? 0 : n % 10] ?? 'th');

const A = surname(F.lap.a.name), B = surname(F.lap.b.name);
const AU = A.toUpperCase(), BU = B.toUpperCase();
const CORNERS = F.track.corners.length;
const GAP = s3(F.lap.gap_s), IN_CORNERS = s3(F.lap.corner_s);
// "Russell took pole" is only true while the first driver is P1; landing_facts.py refuses otherwise.
const ON_POLE = F.lap.a.position === 1 && F.pole.code === F.lap.a.code;
const NAMES = Object.fromEntries(F.corners.map((c) => [c.n, c.name]));
const TOP = F.faster.b_top.map((n) => NAMES[n]);

const [SEASON, ROUND_SESSION] = F.source.slug.split('/');
const [ROUND, SESSION] = ROUND_SESSION.split('_');
const [RACE_SEASON, RACE_ROUND_SESSION] = F.source.race_slug.split('/');
const [RACE_ROUND, RACE_SESSION] = RACE_ROUND_SESSION.split('_');
const race = (view: string) =>
  `/race-arc?year=${RACE_SEASON}&round=${Number(RACE_ROUND)}&session=${RACE_SESSION}&view=${encodeURIComponent(view)}`;
const LINKS = {
  corners: `/corner-analysis?year=${SEASON}&round=${Number(ROUND)}&session=${SESSION}&drivers=${F.lap.a.code},${F.lap.b.code}`,
  tyres: race('Tyre Degradation'),
  track: race('Track Evolution'),
  undercut: race('Race Strategy'),
};

function barRow(bar: (typeof F.count_bars)[number], i: number) {
  let title: string, note: string;
  if (bar.label.endsWith('_corners')) {
    title = `${A}'s corners`;
    note = `${bar.turns.length} CORNERS WHERE ${AU} WAS FASTER`;
  } else if (bar.label.endsWith('_other')) {
    title = `${B}'s other ${bar.turns.length}`;
    note = `TURNS ${[...bar.turns].sort((a, b) => a - b).join(', ')} · ALL ${CORNERS} CORNERS NOW ADDED: ${IN_CORNERS} S`;
  } else if (bar.label === 'straights') {
    title = 'Straights';
    note = `${'count' in bar ? bar.count : ''} STRAIGHTS · FINAL TOTAL, THE GAP: ${GAP} S`;
  } else {
    title = 'name' in bar && bar.name ? bar.name : bar.label;
    note = `TURN ${bar.turns[0]} · ${i === 1 ? `${BU}'S BIGGEST GAIN` : `${BU} FASTER`}`;
  }
  return (
    <li key={bar.label} data-v={bar.value}>
      <span>{title}<small>{note}</small></span><span>{signed(bar.value)}</span>
    </li>
  );
}

export function Landing() {
  const root = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const node = root.current!;
    let stopCar: (() => void) | null = null, gone = false;
    const stop = boot(node, F, () => {
      if (innerWidth >= 860 && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
        import('./car').then((car) => { if (!gone) stopCar = car.startCar(node); });
      }
    });
    return () => { gone = true; stopCar?.(); stop(); };
  }, []);

  return (
    <main className="landing" ref={root}>
      <section className="hero">
        <div className="photo"><canvas data-src={HERO_IMAGE} data-cell="6" data-ink="#131313"></canvas></div>
        <div className="cross"><i className="h" style={{ top: '62%' }}></i><i className="h" style={{ top: '84%' }}></i><i className="v" style={{ left: '40vw' }}></i><i className="v" style={{ left: '70vw' }}></i></div>
        <div className="panel acc">
          <div className="top lab"><span>{F.source.location.toUpperCase()} CIRCUIT</span><span>{F.source.event.replace('Grand Prix', 'GP').toUpperCase()} {F.source.year}</span><div className="bc"></div></div>
          <div className="strip lab"><span>F1 DATA ANALYSIS</span><span>UNOFFICIAL</span></div>
          <div className="hz" style={{ height: 16, width: 160, margin: '10px 12px 0' }}></div><h1 className="k">Apex<span className="wg">Trace</span></h1>
          <div className="strip lab"><span>{AU} VS {BU}</span><span>{F.source.session.toUpperCase()}</span></div>
          <div className="foot">
            <p style={{ marginBottom: 14 }}><strong>Formula 1 telemetry analysis</strong>
              <span data-answer>{ON_POLE ? `${A} took pole. ` : ''}He was {GAP} s faster than {B}, who
                qualified {ordinal(F.lap.b.position)}; {IN_CORNERS} s of it came in the corners.</span></p>
            <Link className="btn" to={LINKS.corners}><span>Open the analysis</span><span>↗</span></Link>
          </div>
        </div>
        <div className="stage"><svg id="trk" role="img" aria-label={`${F.source.location} circuit with ${A}'s and ${B}'s ${F.source.session.toLowerCase()} laps replayed`} preserveAspectRatio="xMidYMid meet"></svg></div>
        <div className="ann lab" style={{ left: '2vw', bottom: '14vh' }}>LAP LENGTH<b>{F.track.length_km.toFixed(3)} KM</b></div>
        <div className="ann lab" style={{ left: '14vw', bottom: '14vh' }}>CORNERS<b>{CORNERS}</b></div>
        <div className="ann lab" style={{ left: '26vw', bottom: '14vh' }}>GAP TO {BU}<b>{GAP} S</b></div>
        <div className="ann lab" style={{ left: '2vw', bottom: '4vh' }}>LAP REPLAY<b>● {AU} &nbsp;○ {BU}</b></div>
      </section>

      <section className="sheet count" id="count">
        <div>
          <span className="lab">THE ANSWER · {AU} WAS {GAP} S FASTER THAN {BU} · SCROLL TO ADD IT UP</span>
          <div className="big"><span id="sum">0.000</span><small> S</small></div>
          <p style={{ marginTop: 14 }}><Term id="pole" /> <Term id="qualifying" /> At {F.source.location} {F.source.year} {A}{ON_POLE ? ' took pole' : ' set the faster lap'}. {B} qualified {ordinal(F.lap.b.position)}, {GAP} s slower, and the total above adds that gap up one piece at a time. {B} was faster in {F.faster.b} of the {CORNERS} corners, most of all at {TOP.slice(0, -1).join(', ')} and {TOP[TOP.length - 1]}. It was not enough.</p>
          <p className="lab" style={{ marginTop: 14, textTransform: 'none', letterSpacing: 0 }}>+ = time {A} gained · − = time {B} gained · rows rounded to 0.001 s; the total uses unrounded values.</p>
        </div>
        <ol id="parts">{F.count_bars.map(barRow)}</ol>
      </section>

      <section className="sheet" id="grid">
        <span className="lab">ALL {CORNERS} CORNERS · WHO WAS FASTER IN EACH, AND BY HOW MANY SECONDS</span>
        <div data-corner-grid style={{ marginTop: '4vh' }}></div>
        <div className="legend lab"><span><i className="acc"></i>{AU} FASTER</span><span><i className="ver"></i>{BU} FASTER</span><span>SECONDS GAINED IN EACH CORNER · {F.source.year} DATA FROM THE APEXTRACE API</span></div>
      </section>

      <section id="questions" className="sheet">
        <span className="lab">FOUR QUESTIONS THE DATA ANSWERS · EACH CARD OPENS THE LIVE TOOL</span>
        <h2 className="k" data-split style={{ fontSize: 'clamp(60px,9vw,170px)', marginTop: 14 }}>Ask the data</h2>
        {/* The cards' terms are explained here, not inside the cards: each card has to fit
            under the 80 px sticky top on a phone (cards.py). */}
        <p style={{ maxWidth: '60ch', marginTop: 14 }}><Term id="stint" /> <Term id="pit-loss" /> <Term id="undercut" /></p>
        <div className="stack">
          <Link className="sc acc" data-q="corners" to={LINKS.corners}>
            <div className="l"><span className="lab">QUESTION 1 · CORNERS ↗</span><h3>{s1(F.lap.gap_s)} seconds quicker. Where?</h3></div>
            <div className="r"><div className="v">{IN_CORNERS} S</div><p>of {A}'s {GAP} s came from corners. For each corner: where he braked, his slowest speed through it, and when he got back on the throttle.</p></div>
          </Link>
          <Link className="sc" data-q="tyres" to={LINKS.tyres} style={{ background: 'var(--paper)' }}>
            <div className="l"><span className="lab">QUESTION 2 · TYRES ↗</span><h3>How fast is the tyre going?</h3></div>
            <div className="r acc"><div className="v">{s3(F.tyres.SOFT.s_per_lap)}</div><p>seconds lost per lap as the soft tyre wears, Bahrain {F.source.year}. 95% confidence interval {s3(F.tyres.SOFT.ci_low)}–{s3(F.tyres.SOFT.ci_high)}, from {F.tyres.SOFT.stints} stints. The hard tyre: {s3(F.tyres.HARD.s_per_lap)} s per lap, {F.tyres.HARD.stints} stints.</p></div>
          </Link>
          <Link className="sc acc" data-q="track" to={LINKS.track}>
            <div className="l"><span className="lab">QUESTION 3 · TRACK ↗</span><h3>How much was the track?</h3></div>
            <div className="r"><div className="v">3 EFFECTS</div><p>Laps get faster as the track gains grip and fuel burns off, and slower as tyres wear. All three happen at once; the model pulls out the track's share alone.</p></div>
          </Link>
          <Link className="sc" data-q="undercut" to={LINKS.undercut} style={{ background: 'var(--paper)' }}>
            <div className="l"><span className="lab">QUESTION 4 · STRATEGY ↗</span><h3>Does the undercut work?</h3></div>
            <div className="r acc"><div className="v">{s1(F.pit_loss.total_s)} S</div><p>lost to a pit stop, Bahrain {F.source.year}: {s1(F.pit_loss.in_s)} s on the lap into the pits, {s1(F.pit_loss.out_s)} s on the lap out. This loss and how fast the tyres wear decide if the undercut works.</p></div>
          </Link>
        </div>
      </section>

      <section id="method" className="sheet">
        <span className="lab">METHOD · HOW EACH NUMBER IS WORKED OUT</span>
        <h2 className="k" data-split style={{ fontSize: 'clamp(60px,9vw,170px)', marginTop: 14 }}>How it knows</h2>
        <div className="tl">
          <div className="st" data-n="1" data-reveal><h3>Corner segmentation</h3><div className="eq">Δt = Σ<sub>segments</sub> (t<sub>{F.lap.b.code}</sub> − t<sub>{F.lap.a.code}</sub>)</div><p>The lap is cut into {CORNERS} corners and the straights between them. Δt, the gap between the two drivers, is the sum of the gaps in every piece, so each hundredth of a second lands in exactly one piece.</p></div>
          <div className="st" data-n="2" data-reveal><h3>Inverse-variance pooling</h3><div className="eq">β̂ = Σ w<sub>i</sub>β<sub>i</sub> / Σ w<sub>i</sub>,&nbsp; w<sub>i</sub> = 1/σ<sub>i</sub>²</div><p>Each stint gives one slope: seconds lost per lap as the tyre wears, after removing the gain from fuel burning off. The slopes are averaged across all drivers, and a stint with a more certain slope (smaller σ) counts for more. The 95% confidence interval is always shown.</p></div>
          <div className="st" data-n="3" data-reveal><h3>Collinearity, argued</h3><div className="eq">lap time ~ track + tyre age + fuel</div><p>Track grip, tyre age and fuel load all change lap by lap, together, so their effects are tangled (the statistical name is collinear). The model says when they can be separated, and says so when they cannot.</p></div>
        </div>
      </section>

      <section id="proof" className="sheet">
        <span className="lab">THE DATA · WHAT THE ANALYSIS IS BUILT ON</span>
        <p style={{ maxWidth: '60ch', marginTop: 14 }}><Term id="telemetry" /></p>
        <div className="spec" data-reveal>
          <div className="sp"><b>{F.spec.sessions}</b><span>Sessions</span><p>F1 practice, qualifying, sprint and race sessions, each with lap times and car telemetry.</p></div>
          <div className="sp"><b>{F.spec.seasons}</b><span>Seasons</span><p>{F.spec.years.join(', ')}. Latest stored season through round {F.spec.latest_round}.</p></div>
          <div className="sp"><b>{F.spec.tests}</b><span>Tests</span><p>Automated checks on the analysis and the API. They run on every code change.</p></div>
          <div className="sp"><b>{F.spec.data_mib}</b><span>MiB of data</span><p>Cleaned F1 timing data from the FastF1 library, stored as Parquet files.</p></div>
        </div>
      </section>

      <section id="author" className="sheet credits">
        <span className="lab">WHO BUILT IT</span><span className="lab">ANALYSIS, CODE, DESIGN</span><div className="k" data-reveal>Sumeet</div><span className="lab">FINAL-YEAR COMPUTER SCIENCE STUDENT · DATA PIPELINE, ANALYSIS, API AND THIS SITE</span>
        <nav><a href="https://github.com/SUMEET1000" target="_blank" rel="noopener">GitHub ↗</a><a href="#">LinkedIn ↗</a><a href="#">Case study ↗</a></nav>
        <Link className="btn" to={LINKS.corners}><span>Open the analysis</span><span>↗</span></Link>
        <span className="lab">DATA: FASTF1, WHICH READS THE OFFICIAL F1 TIMING FEED · {F.spec.years[0]}–{F.spec.years[F.spec.years.length - 1]}</span>
      </section>

      <section id="sig" className="sheet sig" aria-label="End of sheet" style={{ '--sig-h': '55vh', '--sig-d': '19px' } as CSSProperties}>
        <div className="sig-strip lab"><span>END OF PAGE</span><span className="bc" aria-hidden="true"></span><span>DRAWN FROM THE TIMING DATA</span></div>
        <div className="sig-stage"><i className="reg" style={{ left: 0, top: 8 }}></i><i className="reg" style={{ right: 0, top: 8 }}></i><i className="reg" style={{ left: 0, bottom: 8 }}></i><i className="reg" style={{ right: 0, bottom: 8 }}></i>
          <svg className="sig-svg" role="img" aria-label={`${F.source.location} circuit, ${CORNERS} corners`} preserveAspectRatio="xMidYMid meet"></svg></div>
        <div className="sig-col"><span className="k sig-name">Apex<span className="wg">Trace</span></span>
          <div className="lab sig-facts"><span>{F.source.location.toUpperCase()} · {F.track.length_km.toFixed(3)} KM</span><span>{CORNERS} CORNERS</span><span>POLE · {F.pole.code === F.lap.a.code ? AU : F.pole.code} {F.pole.time}</span><span>GAP · {GAP} S</span><span>DATA · FASTF1</span></div></div>
        <div className="sig-chq" aria-hidden="true"></div>
      </section>
    </main>
  );
}
