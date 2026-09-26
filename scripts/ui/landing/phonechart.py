"""Landing on a phone: the question-card charts stay readable.

At 390 px no two chart labels overlap, no chart text renders under 12 px
tall, and the page logs no console errors.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import Gate, landing_url, parse, viewport, watch_errors  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

OVERLAPS = """()=>{const o=[];document.querySelectorAll('.qc svg').forEach((s,k)=>{
  const t=[...s.querySelectorAll('text')].map(e=>[e.textContent,e.getBoundingClientRect()]);
  for(let i=0;i<t.length;i++)for(let j=i+1;j<t.length;j++){const a=t[i][1],c=t[j][1];
    if(!(a.right<=c.left||c.right<=a.left||a.bottom<=c.top||c.bottom<=a.top))o.push(k+': '+t[i][0]+' x '+t[j][0])}});
  return o}"""
MIN_TEXT_PX = 12


def main() -> None:
    args = parse(__doc__, widths=(390,))
    gate = Gate()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in args.widths:
            page = browser.new_page(viewport=viewport(width), has_touch=True, is_mobile=True)
            errors = watch_errors(page)
            page.goto(landing_url(args.base), wait_until="load")
            page.wait_for_timeout(3500)
            sizes = page.evaluate("[...document.querySelectorAll('.qc text')].map(t=>t.getBoundingClientRect().height)")
            overlaps = page.evaluate(OVERLAPS)
            gate.check(bool(sizes), f"{width} question-card charts are drawn", f"{len(sizes)} labels")
            gate.check(not overlaps, f"{width} no chart labels overlap", overlaps[:4])
            gate.check(bool(sizes) and min(sizes) >= MIN_TEXT_PX, f"{width} chart text at least {MIN_TEXT_PX}px",
                       f"smallest {min(sizes):.1f}px" if sizes else "")
            gate.check(not errors, f"{width} console errors", errors[:3])
            page.close()
        browser.close()
    gate.exit()


if __name__ == "__main__":
    main()
