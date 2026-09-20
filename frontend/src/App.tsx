/** The app shell: sidebar, session picker, and the three routes.
 *
 * The manifest and the session picker live here rather than in each page,
 * because the picker is shared by all three and the selected session has to
 * survive navigation — exactly as it did when Streamlit ran `session_picker`
 * at the top of every script.
 */

import { useCallback, useMemo, useRef, useState } from 'react';
import { Sidebar, SidebarSlot } from './components/Sidebar';
import { SessionPicker, type Selection } from './components/SessionPicker';
import { ErrorBox } from './components/ui/primitives';
import { useReveal } from './hooks/useReveal';
import { fetchManifest, fetchOpener, useAsync } from './lib/api';
import { useLocation } from './lib/router';
import { HomePage } from './pages/Home';
import { CornerAnalysisPage } from './pages/CornerAnalysis';
import { RaceArcPage } from './pages/RaceArc';

/** Which session type each route wants to open on when the URL says nothing. */
const PREFERRED: Record<string, string[]> = {
  '/race-arc': ['R', 'Sprint'],
};

export function App() {
  const { pathname, search } = useLocation();
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
    return <div className="pw-boot">Loading the session manifest…</div>;
  }

  if (manifest.error || !manifest.data) {
    return (
      <div className="pw-boot">
        <ErrorBox>
          <p><b>Could not reach the ApexTrace API.</b> {manifest.error}</p>
          <p>Start it with:</p>
          <pre>.venv/Scripts/python scripts/run_dev.py</pre>
        </ErrorBox>
      </div>
    );
  }

  const { sessions, years, featured } = manifest.data;

  let page = null;
  if (selection) {
    if (pathname === '/corner-analysis') {
      page = <CornerAnalysisPage selection={selection} />;
    } else if (pathname === '/race-arc') {
      page = <RaceArcPage selection={selection} />;
    } else {
      page = <HomePage selection={selection} featured={featured} search={search} />;
    }
  }

  return (
    <SidebarSlot.Provider value={slot}>
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
            <div className="pw-main" ref={main}>{page}</div>
          </div>
        </div>
      </div>
    </SidebarSlot.Provider>
  );
}
