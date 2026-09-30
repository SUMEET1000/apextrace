/** The three data states every fetching screen shows: loading, empty, error.
 *
 * `aria-busy` on the loading box is what scripts/ui/gate.py waits on.
 */

import { useEffect, useState, type ReactNode } from 'react';

/** Render's free web service sleeps after 15 idle minutes; the wake took a
 *  median 45.93 s (measured 22 Sept 2026, PROGRESS.md). Under 3 s is an awake
 *  server being slow, so the waking message waits that long. */
const WAKE_NOTICE_AFTER_S = 3;

export function Loading({ what }: { what: string }) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const start = performance.now();
    const id = setInterval(
      () => setSeconds(Math.floor((performance.now() - start) / 1000)), 250);
    return () => clearInterval(id);
  }, []);
  return (
    <div className="state tokens" role="status" aria-busy="true">
      {/* The counter is hidden from screen readers so it is not read out every second. */}
      <span className="lab">Loading {what} · <span aria-hidden="true">{seconds} s</span></span>
      {seconds >= WAKE_NOTICE_AFTER_S && (
        <p>The server is waking up. It sleeps when nobody has used it for 15 minutes,
          and takes about 46 s to start.</p>
      )}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="state tokens">
      <span className="lab">Nothing to show</span>
      <p>{children}</p>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="state tokens" role="alert">
      <span className="lab">The server answered with an error</span>
      <p>{message}</p>
      <button type="button" className="btn" onClick={onRetry}>
        <span>Retry</span><span aria-hidden="true">↻</span>
      </button>
    </div>
  );
}
