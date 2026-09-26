/** 08's loader, lifted by the page's real load instead of a fixed 2.4 s.
 *
 * The loader is in index.html so it covers the page before any script runs.
 * On `/` it stays until `document.fonts.ready` and the hero image have both
 * settled, or for 2.6 s at most (his answer to review finding R1, 26 Sept
 * 2026); it never waits on the API. Anywhere else, and with reduced motion, it
 * goes at once. `lifting` resolves when it starts to slide up (the hero enters
 * 450 ms later, as in 08) and `lifted` when it is removed (the guide car drives
 * in then).
 */

export const HERO_IMAGE = '/img/sensor.png';
const CAP_MS = 2600;
const LIFT_MS = 150;   // the .done transition in landing.css

let resolveLifting: (at: number) => void;
let resolveLifted: (at: number) => void;
export const lifting = new Promise<number>((resolve) => { resolveLifting = resolve; });
export const lifted = new Promise<number>((resolve) => { resolveLifted = resolve; });

export function startLoader(): void {
  const loader = document.getElementById('loader');
  const done = () => { loader?.remove(); resolveLifting(performance.now()); resolveLifted(performance.now()); };
  if (!loader || location.pathname !== '/' || matchMedia('(prefers-reduced-motion: reduce)').matches) {
    done();
    return;
  }
  const bar = loader.querySelector<HTMLElement>('[data-bar]');
  const pct = loader.querySelector<HTMLElement>('[data-pct]');
  const image = new Image();
  image.src = HERO_IMAGE;
  let ready = false;
  Promise.all([
    document.fonts.ready,
    image.complete ? null : new Promise((settle) => { image.onload = image.onerror = settle; }),
  ]).then(() => { ready = true; });

  // performance.now() counts from navigation start, so the cap holds for the
  // whole page, script download included.
  const step = (now: number) => {
    const k = ready ? 1 : Math.min(1, now / CAP_MS);
    const eased = 1 - (1 - k) ** 3;
    if (bar) bar.style.transform = `scaleX(${eased})`;
    if (pct) pct.textContent = String(Math.round(eased * 100)).padStart(3, '0');
    if (k < 1) { requestAnimationFrame(step); return; }
    loader.classList.add('done');
    resolveLifting(performance.now());
    setTimeout(done, Math.max(0, Math.min(LIFT_MS, CAP_MS - performance.now())));
  };
  requestAnimationFrame(step);
}
