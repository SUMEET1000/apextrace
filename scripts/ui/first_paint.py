"""First paint: a fixed 2.6 s loader hold, independent of API and cache state.

Pending part, every /api/* request held for the whole run:
  (a) the loader starts its 0.9 s exit after the 2.6 s hold;
  (b) once it is gone, the answer sentence and its 0.384 and 0.326 figures are
      on top - elementFromPoint at each one's centre lands inside the answer;
  (c) holding the hero image does not extend that sequence.
Cache part, no routing at all (Playwright's route turns the HTTP cache off):
  two visits in one context; on the second, the hero image and the font files
  come from the browser cache - no body transferred: transferSize is 0, or a
  header-only 304 below the body size where the server says revalidate - and
  the loader still holds for 2.6 s (Sumeet's override, 26 Sept 2026).
  Measured 26 Sept 2026: vite preview
  sends no-cache and the live static site max-age=0 for every file, so the
  hero image is always revalidated there.

    "$PY" scripts/ui/first_paint.py --base http://127.0.0.1:4173
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Gate, facts, parse, viewport, watch_errors  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

# Times, from navigation start, when the loader starts to lift and when it is removed.
WATCH = """window.__lf={};new MutationObserver(()=>{const L=document.getElementById('loader');
  if(L){__lf.seen=true;if(L.classList.contains('done')&&!__lf.lift)__lf.lift=performance.now()}
  else if(__lf.seen&&!__lf.gone)__lf.gone=performance.now()})
  .observe(document,{subtree:true,childList:true,attributes:true,attributeFilter:['class']})"""

# For each line of the answer and each figure in it: does a hit test at its centre land
# inside the answer? Per line, because a wrapped sentence's box centre can fall between words.
ON_TOP = """nums=>{const a=document.querySelector('[data-answer]');if(!a)return {answer:false};
  const hit=r=>{const e=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return !!e&&a.contains(e)};
  const all=document.createRange();all.selectNodeContents(a);
  const out={answer:[...all.getClientRects()].filter(q=>q.width>4).every(hit)};
  for(const n of nums){const i=a.textContent.indexOf(n);if(i<0){out[n]=false;continue}
    const w=document.createTreeWalker(a,NodeFilter.SHOW_TEXT);let t,k=i;
    while((t=w.nextNode())&&k>=t.length)k-=t.length;
    const r=document.createRange();r.setStart(t,k);r.setEnd(t,k+n.length);out[n]=hit(r.getBoundingClientRect())}
  return out}"""

HERO = "**/img/sensor.png"
ENTRIES = """()=>performance.getEntriesByType('resource').filter(e=>/sensor\\.png|fonts\\.gstatic\\.com/.test(e.name))
  .map(e=>[e.name.split('/').pop().slice(0,40),e.transferSize,e.encodedBodySize])"""


def fresh(entry) -> bool:
    """The body came over the network. A cache hit sends 0 bytes; a 304 sends headers
    only, and Chrome reports its body size as 0 (measured 26 Sept 2026)."""
    _, sent, body = entry
    return body > 0 and sent >= body


def times(page) -> dict:
    return page.evaluate("window.__lf")


def pending(gate: Gate, browser, base: str, width: int, hold_image: bool) -> None:
    ctx = browser.new_context(viewport=viewport(width))
    ctx.add_init_script(WATCH)
    held: list = []
    ctx.route("**/api/**", lambda r: held.append(r))
    if hold_image:
        ctx.route(HERO, lambda r: held.append(r))
    page = ctx.new_page()
    errors = watch_errors(page)
    page.goto(base.rstrip("/") + "/", wait_until="domcontentloaded")
    tag = f"{width}{' image held' if hold_image else ''}"
    page.wait_for_function("performance.now()>2400")
    early = times(page).get("lift")
    page.wait_for_function("performance.now()>3700")
    lift, gone = times(page).get("lift"), times(page).get("gone")
    gate.check(early is None and lift is not None and 2550 <= lift <= 2800,
               f"{tag} loader holds for 2.6 s", f"lift at {lift and round(lift)} ms")
    gate.check(gone is not None and lift is not None and 850 <= gone - lift <= 1100,
               f"{tag} original 0.9 s exit completes", f"removed at {gone and round(gone)} ms")
    f = facts()["lap"]
    wanted = [f"{f['gap_s']:.3f}", f"{f['corner_s']:.3f}"]
    top = page.evaluate(ON_TOP, wanted)
    gate.check(all(top.get(k) for k in ["answer", *wanted]), f"{tag} (b) answer and figures on top once the loader is gone", top)
    gate.check(not errors, f"{tag} console errors", errors[:3])
    for route in held:
        route.abort()
    page.unroute_all(behavior="ignoreErrors")
    ctx.close()


def cached(gate: Gate, browser, base: str, width: int) -> None:
    ctx = browser.new_context(viewport=viewport(width))
    ctx.add_init_script(WATCH)
    page = ctx.new_page()
    url = base.rstrip("/") + "/"
    page.goto(url, wait_until="load")
    page.wait_for_function("window.__lf&&window.__lf.gone", timeout=10_000)
    first = [e for e in page.evaluate(ENTRIES) if e[0].startswith("sensor")]
    # The control: on the first visit the same predicate must call the image fresh.
    gate.check(bool(first) and all(fresh(e) for e in first), f"{width} cache: first visit downloads the hero image", first)
    page.goto(url, wait_until="load")
    page.wait_for_function("window.__lf&&window.__lf.gone", timeout=10_000)
    lift, gone = times(page)["lift"], times(page)["gone"]
    entries = page.evaluate(ENTRIES)
    image = [e for e in entries if e[0].startswith("sensor")]
    fonts = [e for e in entries if not e[0].startswith("sensor")]
    downloaded = [e for e in entries if fresh(e)]
    gate.check(bool(image) and bool(fonts) and not downloaded, f"{width} cache: hero image and fonts from cache on the second visit",
               f"image {image}, fonts {fonts}")
    gate.check(2550 <= lift <= 2800 and 850 <= gone - lift <= 1100,
               f"{width} cache: same 2.6 s hold and 0.9 s exit", f"lift {round(lift)}, removed {round(gone)} ms")
    ctx.close()


def main() -> None:
    args = parse(__doc__, widths=(1440, 390))
    gate = Gate()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in args.widths:
            pending(gate, browser, args.base, width, hold_image=False)
        pending(gate, browser, args.base, args.widths[0], hold_image=True)
        cached(gate, browser, args.base, args.widths[0])
        browser.close()
    gate.exit()


if __name__ == "__main__":
    main()
