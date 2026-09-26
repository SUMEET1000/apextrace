"""Landing: one wheel notch lights exactly one more gap bar, down and up.

Three kinds of notch, at three window heights: one 100 px event (a Chrome
wheel), eight 13 px events (a smooth mouse or trackpad) and one 3-line event
(Firefox's deltaMode 1). A ScrollTrigger snap skipped bars at 800 px tall, so
heights either side of that are covered. The bars pin only at 860 px and up.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import PIN, Gate, landing_url, parse  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

LIT = "document.querySelectorAll('#parts li.on').length"
LINES = """([d,n])=>{for(let i=0;i<n;i++)document.elementFromPoint(innerWidth/2,innerHeight/2)
  .dispatchEvent(new WheelEvent('wheel',{deltaY:d,deltaMode:1,bubbles:true,cancelable:true}))}"""
HEIGHTS = (700, 800, 1080)


def notch(page, style: str, sign: int) -> None:
    if style == "px":
        page.mouse.wheel(0, 100 * sign)
    elif style == "small":
        for _ in range(8):
            page.mouse.wheel(0, 13 * sign)
            page.wait_for_timeout(12)
    else:
        page.evaluate(LINES, [3 * sign, 1])
    page.wait_for_timeout(700)


def main() -> None:
    args = parse(__doc__, widths=(1440,))
    gate = Gate()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        cases = [(w, h, s, "no-preference") for w in args.widths if w >= 860
                 for h in HEIGHTS for s in ("px", "small", "lines")]
        cases += [(w, 900, "px", "reduce") for w in args.widths if w >= 860]
        for width, height, style, mode in cases:
            page = browser.new_page(viewport={"width": width, "height": height}, reduced_motion=mode)
            page.goto(landing_url(args.base), wait_until="load")
            page.wait_for_timeout(3000)
            pin = page.evaluate(PIN)
            case = f"{width}x{height} {style} {mode}"
            if not gate.check(pin is not None, f"{case} gap bars are pinned"):
                page.close()
                continue
            page.evaluate(f"scrollTo(0,{pin[0]})")
            page.wait_for_timeout(1200)
            page.mouse.move(width / 2, height / 2)
            n = page.evaluate("document.querySelectorAll('#parts li').length")
            down = []
            for _ in range(n + 3):   # the last three pass through and leave the pin
                notch(page, style, 1)
                down.append(page.evaluate(LIT))
            up = []
            for _ in range(n + 6):
                notch(page, style, -1)
                up.append(page.evaluate(LIT))
            # Down from the pin's start: 1, 2, ... n, then n while the page scrolls on out.
            gate.check(down == list(range(1, n + 1)) + [n] * 3, f"{case} down one bar per notch", down)
            # Up from past the pin: n until the pin is re-entered, then one fewer per
            # notch down to 0, then 0 while the page scrolls on out above it.
            first = next((i for i, k in enumerate(up) if k < n), len(up))
            inside = up[first:]
            ok = all(k == n for k in up[:first]) and inside[:n] == list(range(n - 1, -1, -1)) \
                and all(k == 0 for k in inside[n:])
            gate.check(ok, f"{case} up one bar per notch", up)
            page.close()
        browser.close()
    gate.exit()


if __name__ == "__main__":
    main()
