/** The app shell: 08's header and footer around one route.
 *
 * The shell renders at once and never waits on the API: a cold Render wake
 * takes about 46 s, and the header and the waking message are what a visitor
 * sees meanwhile. The manifest, the opener and the session picker belong to the
 * two analysis routes only.
 */

import { lazy, Suspense, useMemo } from 'react';
import { Footer, Header } from './components/Shell';
import { Empty, ErrorState, Loading } from './components/states';
import { fetchManifest, fetchOpener, useAsync } from './lib/api';
import { Landing } from './landing/Landing';
import { useLocation } from './lib/router';
const CornerPage = lazy(() => import('./pages/corner/CornerPage').then(({ CornerPage }) => ({ default: CornerPage })));
const RaceArcPage = lazy(() => import('./pages/race/RaceArcPage').then(({ RaceArcPage }) => ({ default: RaceArcPage })));

/** Which session type each route wants to open on when the URL says nothing. */
const PREFERRED: Record<string, string[]> = {
  '/race-arc': ['R', 'Sprint'],
};

export function App() {
  const { pathname } = useLocation();
  const analysis = pathname === '/corner-analysis' || pathname === '/race-arc';
  return (
    <>
      <Header />
      {analysis
        ? <main className="shell-main"><Analysis pathname={pathname} /></main>
        : <Landing />}
      <Footer />
    </>
  );
}

/** The analysis routes share session discovery and their chosen session in the URL. */
function Analysis({ pathname }: { pathname: string }) {
  const manifest = useAsync((signal) => fetchManifest(signal), []);
  const prefer = useMemo(() => PREFERRED[pathname] ?? [], [pathname]);
  const opener = useAsync(
    (signal) => fetchOpener(prefer, signal), [prefer.join(',')]);

  if (manifest.loading || opener.loading) return <Loading what="the session list" />;
  if (manifest.error || !manifest.data) {
    return <ErrorState message={manifest.error ?? 'No answer'} onRetry={manifest.retry} />;
  }
  const { sessions, years } = manifest.data;
  if (!sessions.length) return <Empty>No sessions have been built yet, so there is nothing to analyse.</Empty>;

  return <div className="pw-main"><Suspense fallback={<Loading what="the charts" />}>
    {pathname === '/corner-analysis'
      ? <CornerPage sessions={sessions} years={years} openerSlug={opener.data?.slug} />
      : <RaceArcPage sessions={sessions} years={years} openerSlug={opener.data?.slug} />}
  </Suspense></div>;
}
