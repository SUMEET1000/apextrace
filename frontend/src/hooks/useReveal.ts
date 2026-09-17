/** Reveal-on-scroll for the top-level blocks of a page.
 *
 * Ported from `REVEAL_JS` in `app/brand.py`. Each top-level block rises into
 * place as it enters the viewport, rather than the whole page appearing at
 * once, so a long analysis page reads as a sequence instead of a wall.
 *
 * The ordering below is load-bearing. The CSS that hides these blocks is gated
 * behind `html.pw-js`, and this hook is the only thing that sets that class —
 * so if it bails out (reduced motion, no IntersectionObserver) the rules never
 * match and the page renders fully visible. Hiding content in CSS and relying
 * on script to bring it back is how an analysis page ends up permanently
 * blank.
 */

import { useEffect } from 'react';

const STAGGER_MS = 70;  // gap between neighbours revealing
const MAX_STEPS = 4;    // cap, so a tall page never queues a long wait
const FOLD = 0.92;      // fraction of the viewport counted as "already on screen"

/**
 * @param root      the container whose direct children are revealed
 * @param signature changes whenever the page's blocks are replaced, so a
 *                  route change re-scans instead of leaving new blocks hidden
 */
export function useReveal(
  root: React.RefObject<HTMLElement | null>, signature: unknown,
): void {
  useEffect(() => {
    const host = root.current;
    if (!host) return;

    // Two reasons to do nothing at all, both of which must leave the page
    // fully visible.
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    if (reduced || !('IntersectionObserver' in window)) return;

    document.documentElement.classList.add('pw-js');

    let pending: HTMLElement[] = [];
    let frame: number | null = null;

    const flush = () => {
      frame = null;
      // Document order, so a row of metric cards lights up left-to-right
      // regardless of the order the observer happened to report them in.
      pending.sort((a, b) =>
        a.getBoundingClientRect().top - b.getBoundingClientRect().top);
      pending.forEach((element, i) => {
        element.style.setProperty(
          '--pw-delay', `${Math.min(i, MAX_STEPS) * STAGGER_MS}ms`);
        element.classList.add('pw-in');
      });
      pending = [];
    };

    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        observer.unobserve(entry.target);  // one-shot: never re-hide
        pending.push(entry.target as HTMLElement);
        if (frame === null) frame = requestAnimationFrame(flush);
      }
      // The bottom margin is positive on purpose: it extends the observed area
      // *below* the fold so a block starts fading in before it is scrolled to,
      // and has finished by the time it is actually being read. A negative
      // margin here — the intuitive "wait until it is properly on screen" —
      // means a quick scroll lands on a block that is still transparent.
    }, { rootMargin: '0px 0px 18% 0px', threshold: 0 });

    const scan = () => {
      const viewport = window.innerHeight || document.documentElement.clientHeight;
      for (const child of Array.from(host.children)) {
        const element = child as HTMLElement;
        if (!element.classList.contains('pw-reveal')) continue;
        // Gate on the revealed class, not on a "already handled" flag. This
        // effect re-runs whenever the route or session changes, and its
        // cleanup disconnects the observer — so any block that had been
        // observed but not yet scrolled to would lose its only route to
        // visibility and stay transparent for good. Re-observing an element
        // is a no-op, so re-checking every unrevealed block each scan is both
        // cheap and the thing that makes this recoverable.
        if (element.classList.contains('pw-in')) continue;

        // Anything the reader can already see is shown at once. Holding
        // above-fold blocks on a fresh page too would wait on an observer
        // callback and then a stagger — up to ~800ms before content was fully
        // visible with the data already in hand. A tool whose whole claim is
        // that it is quick must not spend most of a second animating an answer
        // it already has. Only genuinely below-fold blocks wait to be scrolled
        // to, which is where the reveal earns its keep.
        if (element.getBoundingClientRect().top < viewport * FOLD) {
          element.classList.add('pw-in');
        } else {
          observer.observe(element);
        }
      }
    };

    // Sections arrive as their data resolves, so a single pass at mount would
    // only ever catch whatever existed at that instant. Watching the subtree
    // is what makes this work for a page that fills in piece by piece.
    let scanFrame: number | null = null;
    const queueScan = () => {
      // Plotly mutates its own subtree constantly while drawing, and a scroll
      // fires far faster than a frame; coalescing to one scan per frame keeps
      // this off the critical path.
      if (scanFrame !== null) return;
      scanFrame = requestAnimationFrame(() => { scanFrame = null; scan(); });
    };

    const mutations = new MutationObserver(queueScan);
    mutations.observe(host, { childList: true, subtree: true });

    // An IntersectionObserver only reports a *change* in intersection, so a
    // jump — End, an anchor, a scrollbar drag — sails past whole sections
    // without ever intersecting them, and they stay transparent for the rest
    // of the visit. `scan` reveals anything at or above the fold, which
    // includes everything already scrolled past, so re-running it on scroll is
    // what makes that unrecoverable case impossible.
    window.addEventListener('scroll', queueScan, { passive: true });
    window.addEventListener('resize', queueScan, { passive: true });

    scan();

    return () => {
      mutations.disconnect();
      observer.disconnect();
      window.removeEventListener('scroll', queueScan);
      window.removeEventListener('resize', queueScan);
      if (frame !== null) cancelAnimationFrame(frame);
      if (scanFrame !== null) cancelAnimationFrame(scanFrame);
    };
  }, [root, signature]);
}
