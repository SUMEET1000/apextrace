"""Landing: numbers, layout and wording, in both motion modes at every width.

Fails on console errors, sideways overflow, the hero panel covering the
circuit, a headline number or spec figure that differs from facts.json, or
"pole" beside a margin that is not measured to P2. Ported from the 25 Sept
check.py; the expected numbers now come from facts.json, which
scripts/landing_facts.py --check keeps equal to the API.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import GL_ARGS, Gate, facts, landing_url, parse, viewport, watch_errors  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

LAYOUT = """()=>{const a=document.querySelector('.panel').getBoundingClientRect(),c=document.getElementById('trk').getBoundingClientRect();
  return {sx:document.documentElement.scrollWidth-innerWidth,
          overlap:!(a.right<=c.left||c.right<=a.left||a.bottom<=c.top||c.bottom<=a.top)}}"""
# The rolled spec digits keep the plain number in a screen-reader span.
SPEC = """()=>[...document.querySelectorAll('.sp b')].map(b=>(b.querySelector('.sr')||b).textContent.trim())"""
# A margin is one digit, three decimals, and not the seconds of a m:ss.sss lap time.
POLE = re.compile(r"\bpole\b[^.]{0,30}?(?<![:\d])(\d\.\d{3})", re.I)


def main() -> None:
    args = parse(__doc__)
    f = facts()
    lap, spec = f["lap"], f["spec"]
    numbers = [f"{lap['gap_s']:.3f}", f"{lap['corner_s']:.3f}", f"{lap['straight_s']:.3f}"]
    want_spec = [str(spec["sessions"]), str(spec["seasons"]), str(spec["tests"]), str(spec["data_mib"])]
    pole_margin = f"{f['pole']['margin_s']:.3f}"
    gate = Gate()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=GL_ARGS)
        for mode in ("no-preference", "reduce"):
            for width in args.widths:
                page = browser.new_page(viewport=viewport(width), reduced_motion=mode)
                errors = watch_errors(page)
                page.goto(landing_url(args.base), wait_until="load")
                page.wait_for_timeout(4500)
                page.mouse.move(width / 2, 400)
                for _ in range(160):   # the whole page, so every reveal and roll has run
                    page.mouse.wheel(0, 150)
                    page.wait_for_timeout(60)
                page.wait_for_timeout(1500)
                layout = page.evaluate(LAYOUT)
                text = page.evaluate("document.body.innerText")
                shown = page.evaluate(SPEC)
                case = f"{mode} {width}"
                gate.check(not errors, f"{case} console errors", errors[:3])
                gate.check(layout["sx"] <= 0, f"{case} no sideways overflow", f"{layout['sx']}px")
                gate.check(not layout["overlap"], f"{case} hero panel clear of the circuit")
                missing = [n for n in numbers if n not in text]
                gate.check(not missing, f"{case} headline numbers from facts.json", missing or numbers)
                gate.check(shown == want_spec, f"{case} spec figures from facts.json",
                           f"page {shown}, facts {want_spec}")
                claims = [m.group(0) for m in POLE.finditer(text) if m.group(1) != pole_margin]
                gate.check(not claims, f"{case} 'pole' only beside the P2 margin ({pole_margin} s)", claims[:3])
                page.close()
        browser.close()
    gate.exit()


if __name__ == "__main__":
    main()
