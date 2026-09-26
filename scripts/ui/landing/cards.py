"""Landing: the question cards fit under the header and fade out fully.

All cards stick at one 80 px top. Each must fit in the viewport below that
top, and once the next card has fully covered it, it must be invisible
(opacity at most 0.02). An invisible card's edge is not judged: the old
edge-only test failed on cards already at opacity 0 (once in four at 1024 on
25 Sept, once at 1920 on 26 Sept 2026), where nothing can be seen.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import Gate, landing_url, parse, viewport  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

STICKY_TOP = 80
COVERED = """()=>{const s=[...document.querySelectorAll('.sc')],v=[];let c=0;
  for(let i=0;i<s.length-1;i++){const n=s[i+1].getBoundingClientRect();
    if(Math.abs(n.top-80)<2){c++;const o=+getComputedStyle(s[i]).opacity,r=s[i].getBoundingClientRect();
      if(o>.02)v.push('card '+(i+1)+' visible at opacity '+o.toFixed(2)+(r.top<n.top-1?', edge shows '+Math.round(n.top-r.top)+'px':''))}}
  return [c,v]}"""


def main() -> None:
    args = parse(__doc__)
    gate = Gate()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in args.widths:
            vp = viewport(width)
            page = browser.new_page(viewport=vp)
            page.goto(landing_url(args.base), wait_until="load")
            page.wait_for_timeout(3500)
            heights = page.evaluate("[...document.querySelectorAll('.sc')].map(e=>Math.round(e.getBoundingClientRect().height))")
            room = vp["height"] - STICKY_TOP
            gate.check(bool(heights) and max(heights) <= room, f"{width} every card fits below the sticky top",
                       f"heights {heights}, room {room}")
            page.mouse.move(width / 2, vp["height"] / 2)
            seen: set[str] = set()
            covered = 0
            for _ in range(160):
                page.mouse.wheel(0, 150)
                page.wait_for_timeout(60)
                c, v = page.evaluate(COVERED)
                covered += c
                seen.update(v)
            gate.check(covered > 0 and not seen, f"{width} a covered card is invisible with no edge",
                       f"{covered} covered states seen; {sorted(seen)[:4] or 'no faults'}")
            page.close()
        browser.close()
    gate.exit()


if __name__ == "__main__":
    main()
