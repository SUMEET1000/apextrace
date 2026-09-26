/** 08's header and footer, shared by every route.
 *
 * The header renders at once and never waits on the API. Its engine chip asks
 * `/api/manifest` on the same origin, so the web service starts waking while
 * the visitor reads, and reports how long the wake took.
 */

import { useEffect, useState } from 'react';
import { Link, NavLink } from '../lib/router';

const ROUTES = [
  { to: '/corner-analysis', label: 'Corners' },
  { to: '/race-arc', label: 'Race arc' },
];

function useEngine(): { text: string; live: boolean } {
  const [state, setState] = useState({ text: 'SERVER WAKING UP · ~46 S', live: false });
  useEffect(() => {
    const controller = new AbortController();
    const start = performance.now();
    fetch('/api/manifest', { signal: controller.signal }).then(
      (response) => {
        const seconds = ((performance.now() - start) / 1000).toFixed(1);
        setState(response.ok
          ? { text: `SERVER READY · ${seconds} S`, live: true }
          : { text: 'SERVER OFFLINE', live: false });
      },
      () => {
        if (!controller.signal.aborted) setState({ text: 'SERVER OFFLINE', live: false });
      },
    );
    return () => controller.abort();
  }, []);
  return state;
}

export function Header() {
  const engine = useEngine();
  return (
    <header>
      <Link to="/" className="k">Apex<span className="wg">Trace</span></Link>
      <nav className="lab" aria-label="Pages">
        {ROUTES.map((route) => (
          <NavLink key={route.to} to={route.to}>{route.label}</NavLink>
        ))}
      </nav>
      <span className="hdr-r">
        <span className={engine.live ? 'lab eng live' : 'lab eng'} role="status">{engine.text}</span>
      </span>
    </header>
  );
}

export function Footer() {
  return (
    <footer className="lab">
      <span>UNOFFICIAL. NOT ASSOCIATED WITH FORMULA 1. F1 AND FORMULA ONE ARE TRADEMARKS OF
        FORMULA ONE LICENSING B.V. DATA: FASTF1.</span>
      <span>2026</span>
    </footer>
  );
}
