"""Page gate: every route, at every width, with and without reduced motion.

For each case it fails on any of: console or page errors; sideways overflow;
axe-core colour-contrast violations; a chart without a finding sentence above
it that states a number; a glossary term on the page without its explanation
visible on the page; content ending more than a viewport above the bottom of
the page; a page whose data-slug is not the session its URL names; and, with
reduced motion set at load, anything that still moves.

    "$PY" scripts/ui/gate.py --base http://127.0.0.1:4173 / "/corner-analysis?year=2024&round=12&session=Q&drivers=RUS,VER"

Page contract the checks read:
  [data-chart]           a chart; its <figure> holds a [data-finding] before it
  [data-term-def="id"]   the visible explanation of glossary entry "id"
  [data-slug]            the session the page resolved
  [aria-busy="true"]     still loading; the gate waits until none is left
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import GL_ARGS, REPO, Gate, parse, viewport, watch_errors  # noqa: E402
from playwright.sync_api import Error as PlaywrightError, sync_playwright  # noqa: E402

AXE = REPO / "frontend" / "node_modules" / "axe-core" / "axe.min.js"
GLOSSARY = json.loads((REPO / "frontend" / "src" / "lib" / "glossary.json").read_text(encoding="utf-8"))

VISIBLE = """e=>{for(let n=e;n&&n.nodeType===1;n=n.parentElement){const s=getComputedStyle(n);
  if(s.display==='none'||s.visibility==='hidden')return false}const r=e.getBoundingClientRect();return r.width>0&&r.height>0}"""

FINDINGS = f"""()=>{{const vis={VISIBLE};return [...document.querySelectorAll('[data-chart]')].filter(vis).map(c=>{{
  const id=c.dataset.chart||c.tagName, f=c.closest('figure'), n=f&&f.querySelector('[data-finding]');
  if(!n)return id+': no [data-finding] in its figure';
  if(!(n.compareDocumentPosition(c)&Node.DOCUMENT_POSITION_FOLLOWING))return id+': finding is not above the chart';
  if(!vis(n))return id+': finding is hidden';
  if(!/\\d/.test(n.textContent))return id+': finding states no number';return null}}).filter(Boolean)}}"""

DEFS = f"""()=>{{const vis={VISIBLE};return [...document.querySelectorAll('[data-term-def]')].filter(vis).map(e=>e.dataset.termDef)}}"""

TAIL = f"""()=>{{const vis={VISIBLE},media=/^(svg|canvas|img|video|input|select|button)$/i;let b=0;
  for(const e of document.body.querySelectorAll('*')){{
    if(e.children.length&&!media.test(e.tagName))continue;
    if(e.closest('svg')&&e.tagName.toLowerCase()!=='svg')continue;
    if(!(media.test(e.tagName)||e.textContent.trim())||!vis(e))continue;
    b=Math.max(b,e.getBoundingClientRect().bottom+scrollY)}}
  return [document.documentElement.scrollHeight,Math.round(b),innerHeight]}}"""

# Everything that can move without input: computed transforms and opacity of
# every element, the geometry attributes of every SVG element, and a hash of
# every canvas's pixels. Sampled twice, 1.5 s apart, under reduced motion.
SNAPSHOT = """()=>{const o=[],A=['cx','cy','r','x','y','x1','y1','x2','y2','d','points','transform','width','height','offset'];
  const h=s=>{let x=5381;for(let i=0;i<s.length;i+=7)x=(x*33^s.charCodeAt(i))>>>0;return x};
  for(const e of document.body.querySelectorAll('*')){const s=getComputedStyle(e),
    id=e.tagName.toLowerCase()+(e.id?'#'+e.id:'')+(typeof e.className==='string'&&e.className?'.'+e.className.trim().split(/\\s+/)[0]:'');
    let v=[s.transform,s.opacity,s.translate,s.scale,s.rotate,s.strokeDashoffset].join(' ');
    if(e instanceof SVGElement)v+=' '+A.map(a=>e.getAttribute(a)).join(',');
    if(e.tagName==='CANVAS'){try{v+=' px'+h(e.toDataURL())}catch(err){v+=' canvas-unreadable:'+err.name}}
    o.push([id,v])}return o}"""

MOTION = """()=>({car:!!document.getElementById('car'),lenis:document.documentElement.classList.contains('lenis'),
  running:document.getAnimations().filter(a=>a.playState==='running').map(a=>(a.animationName||a.constructor.name)+' on '+(a.effect&&a.effect.target&&a.effect.target.tagName))})"""


def expected_slug(route: str) -> str | None:
    q = parse_qs(urlsplit(route).query)
    if not {"year", "round", "session"} <= q.keys():
        return None
    return f"{int(q['year'][0])}/{int(q['round'][0]):02d}_{q['session'][0]}"


def term_patterns(entry: dict) -> re.Pattern:
    words = "|".join(re.escape(w) for w in entry["words"])
    return re.compile(rf"(?<![\w-])(?:{words})(?![\w-])", re.I)


def settle(page) -> str | None:
    """Wait for the network, the loader and every aria-busy region. Returns why it could not."""
    try:
        page.wait_for_load_state("networkidle", timeout=90_000)
        page.wait_for_function("!document.getElementById('loader')&&!document.querySelector('[aria-busy=\"true\"]')",
                               timeout=90_000)
    except PlaywrightError as exc:
        return f"page never settled: {str(exc).splitlines()[0]}"
    page.wait_for_timeout(2000)
    return None


def run_case(browser, base: str, route: str, width: int, mode: str) -> list[str]:
    fails: list[str] = []
    ctx = browser.new_context(viewport=viewport(width), reduced_motion=mode)
    page = ctx.new_page()
    errors = watch_errors(page)
    page.goto(base.rstrip("/") + "/" + route.lstrip("/"), wait_until="load", timeout=90_000)
    why = settle(page)
    if why:
        fails.append(why)

    if mode == "reduce":
        state = page.evaluate(MOTION)
        if state["car"]:
            fails.append("reduced motion: the guide car canvas exists")
        if state["lenis"]:
            fails.append("reduced motion: Lenis smooth scroll is running")
        if state["running"]:
            fails.append(f"reduced motion: animations running {state['running'][:3]}")
        first = page.evaluate(SNAPSHOT)
        page.wait_for_timeout(1500)
        second = page.evaluate(SNAPSHOT)
        if len(first) != len(second):
            fails.append(f"reduced motion: element count changed {len(first)} -> {len(second)}")
        else:
            moved = [a[0] for a, b in zip(first, second) if a != b]
            if moved:
                fails.append(f"reduced motion: {len(moved)} elements moved, e.g. {moved[:3]}")

    # Scroll the whole page once so scroll-triggered reveals have run before
    # contrast and visibility are judged.
    height = page.evaluate("document.documentElement.scrollHeight")
    for y in range(0, height, int(viewport(width)["height"] * 0.8)):
        page.evaluate(f"scrollTo(0,{y})")
        page.wait_for_timeout(200)
    page.evaluate("scrollTo(0,0)")
    page.wait_for_timeout(800)

    overflow = page.evaluate("document.documentElement.scrollWidth-innerWidth")
    if overflow > 0:
        fails.append(f"sideways overflow {overflow}px")

    page.add_script_tag(path=str(AXE))
    contrast = page.evaluate("""async()=>{const r=await axe.run(document,{runOnly:{type:'rule',values:['color-contrast']},resultTypes:['violations']});
      return r.violations.flatMap(v=>v.nodes.map(n=>n.target.join(' ')))}""")
    if contrast:
        fails.append(f"{len(contrast)} contrast violations, e.g. {contrast[:3]}")

    findings = page.evaluate(FINDINGS)
    if findings:
        fails.append(f"charts without a finding: {findings[:3]}")

    text = page.evaluate("document.body.innerText")
    shown = set(page.evaluate(DEFS))
    unexplained = [e["id"] for e in GLOSSARY if term_patterns(e).search(text) and e["id"] not in shown]
    if unexplained:
        fails.append(f"terms without an explanation on the page: {unexplained}")

    scroll_h, bottom, inner_h = page.evaluate(TAIL)
    if scroll_h - bottom > inner_h:
        fails.append(f"empty tail: content ends at {bottom}px of {scroll_h}px")

    want = expected_slug(route)
    if want:
        got = page.evaluate("(document.querySelector('[data-slug]')||{}).dataset?.slug||null")
        if got != want:
            fails.append(f"data-slug is {got!r}, the URL names {want!r}")

    if errors:
        fails.append(f"console errors: {errors[:3]}")
    ctx.close()
    return fails


def main() -> None:
    args = parse(__doc__, extra=lambda p: p.add_argument("routes", nargs="+"))
    # Git Bash rewrites a bare "/" argument into its install path (measured 26 Sept 2026:
    # "/" arrived as "C:/Program Files/Git/"), which still loads the SPA and hides the mistake.
    mangled = [r for r in args.routes if re.match(r"^[A-Za-z]:[/\\]", r)]
    if mangled:
        sys.exit(f"routes {mangled} look like Windows paths: run with MSYS_NO_PATHCONV=1 in Git Bash")
    if not AXE.exists():
        sys.exit(f"{AXE} is missing: run `npm ci` in frontend/")
    gate = Gate()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=GL_ARGS)
        for route in args.routes:
            for width in args.widths:
                for mode in ("no-preference", "reduce"):
                    fails = run_case(browser, args.base, route, width, mode)
                    gate.check(not fails, f"{route} {width} {mode}", "; ".join(fails))
        browser.close()
    gate.exit()


if __name__ == "__main__":
    main()
