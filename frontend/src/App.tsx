/** The app shell: 08's header and footer around one route.
 *
 * The shell renders at once and never waits on the API: a cold Render wake
 * takes about 46 s, and the header and the waking message are what a visitor
 * sees meanwhile. The manifest, the opener and the session picker belong to the
 * two analysis routes only.
 */

import { lazy, Suspense, useCallback, useMemo, useRef, useState } from 'react';
import { Footer, Header } from './components/Shell';
import { Sidebar, SidebarSlot } from './components/Sidebar';
import { SessionPicker, type Selection } from './components/SessionPicker';
import { Empty, ErrorState, Loading } from './components/states';
import { useReveal } from './hooks/useReveal';
import { fetchManifest, fetchOpener, useAsync } from './lib/api';
import { Landing } from './landing/Landing';
import { useLocation } from './lib/router';
const CornerPage = lazy(() => import('./pages/corner/CornerPage').then(({ CornerPage }) => ({ default: CornerPage })));
const RaceArcPage = lazy(() => import('./pages/RaceArc').then(({ RaceArcPage }) => ({ default: RaceArcPage })));

/** Which session type each route wants to open on when the URL says nothing. */
const PREFERRED: Record<string, string[]> = {
  '/race-arc': ['R', 'Sprint'],
};

export function App() {
  const { pathname, search } = useLocation();
  const analysis = pathname === '/corner-analysis' || pathname === '/race-arc';
  return (
    <>
      <Header />
      {analysis
        ? <main className="shell-main"><Analysis pathname={pathname} search={search} /></main>
        : <Landing />}
      <Footer />
    </>
  );
}

/** The analysis routes share session discovery; Race Arc keeps its legacy page until Step 6. */
function Analysis({ pathname, search }: { pathname: string; search: string }) {
  const [selection, setSelection] = useState<Selection | null>(null);
  // Open on a desktop, closed on a phone — below 900px the rail is an overlay
  // drawer and would otherwise cover the page it is meant to control.
  const [sidebarOpen, setSidebarOpen] = useState(
    () => typeof window === 'undefined' || window.innerWidth > 900);
  const [slot, setSlot] = useState<HTMLDivElement | null>(null);

  const main = useRef<HTMLDivElement | null>(null);
  // A route change replaces every block, so the reveal has to re-scan; the
  // selected session changes their contents, which is enough to re-run too.
  useReveal(main, `${pathname}|${selection?.slug ?? ''}`);

  const manifest = useAsync((signal) => fetchManifest(signal), []);

  const prefer = useMemo(() => PREFERRED[pathname] ?? [], [pathname]);
  const opener = useAsync(
    (signal) => fetchOpener(prefer, signal), [prefer.join(',')]);

  const slotRef = useCallback((element: HTMLDivElement | null) => {
    setSlot(element);
  }, []);

  if (manifest.loading || opener.loading) {
    return <Loading what="the session list" />;
  }
  if (manifest.error || !manifest.data) {
    return <ErrorState message={manifest.error ?? 'No answer'} onRetry={manifest.retry} />;
  }

  const { sessions, years } = manifest.data;
  if (sessions.length === 0) {
    return <Empty>No sessions have been built yet, so there is nothing to analyse.</Empty>;
  }

  if (pathname === '/corner-analysis') {
    return <div className="pw-main"><Suspense fallback={<Loading what="the charts" />}>
      <CornerPage sessions={sessions} years={years} openerSlug={opener.data?.slug} />
    </Suspense></div>;
  }

  let page = null;
  if (selection) {
    page = <RaceArcPage selection={selection} />;
  }

  return (
    <SidebarSlot.Provider value={slot}>
      <div className="pw-legacy">
        <div className="pw-app">
          <Sidebar
            search={search} slotRef={slotRef}
            open={sidebarOpen} onToggle={() => setSidebarOpen((v) => !v)}
          >
            <SessionPicker
              sessions={sessions} years={years}
              openerSlug={opener.data?.slug}
              onChange={setSelection}
            />
          </Sidebar>

          <div className="pw-content">
            <div className="pw-block-container">
              <div className="pw-main" ref={main}><Suspense fallback={<Loading what="the charts" />}>{page}</Suspense></div>
            </div>
          </div>
        </div>
      </div>
    </SidebarSlot.Provider>
  );
}
