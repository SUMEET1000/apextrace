/** 08's loader with a fixed 2.6 s hold, requested 26 Sept 2026.
 *
 * The loader is in index.html so it covers the page before any script runs.
 * On `/` it holds even on cached visits; it never waits on the API.
 * Anywhere else, and with reduced motion, it goes at once.
 * `lifting` resolves when it starts to slide up (the hero enters
 * 450 ms later, as in 08). The guide car starts after the hero entrance.
 */

export const HERO_IMAGE = '/img/sensor.png';
const HOLD_MS = 2600;
const LIFT_MS = 900;   // the .done transition in landing.css

declare global {
  interface Window {
    __loaderLifting?: number;
    __loaderLifted?: number;
    __onLoaderLifting?: (at: number) => void;
  }
}

let resolveLifting: (at: number) => void;
export const lifting = new Promise<number>((resolve) => { resolveLifting = resolve; });

export function startLoader(): void {
  const loader = document.getElementById('loader');
  const done = (at = performance.now()) => {
    loader?.remove();
    resolveLifting(at);
  };
  if (!loader || location.pathname !== '/' || matchMedia('(prefers-reduced-motion: reduce)').matches) {
    done();
    return;
  }

  if (window.__loaderLifted) {
    done(window.__loaderLifted);
    return;
  }
  if (window.__loaderLifting) {
    resolveLifting(window.__loaderLifting);
    return;
  }

  window.__onLoaderLifting = (at) => resolveLifting(at);

  const bar = loader.querySelector<HTMLElement>('[data-bar]');
  const pct = loader.querySelector<HTMLElement>('[data-pct]');
  const step = (now: number) => {
    if (loader.classList.contains('done') || !loader.isConnected) return;
    const k = Math.min(1, now / HOLD_MS);
    const eased = 1 - (1 - k) ** 3;
    if (bar) bar.style.transform = `scaleX(${eased})`;
    if (pct) pct.textContent = String(Math.round(eased * 100)).padStart(3, '0');
    if (k < 1) { requestAnimationFrame(step); return; }
    loader.classList.add('done');
    const at = performance.now();
    window.__loaderLifting = at;
    resolveLifting(at);
    setTimeout(() => {
      const atLifted = performance.now();
      window.__loaderLifted = atLifted;
      loader.remove();
    }, LIFT_MS);
  };
  requestAnimationFrame(step);
}
