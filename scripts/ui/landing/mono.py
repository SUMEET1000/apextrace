"""Landing: the page never scrolls against the wheel inside the pinned gap bars.

Wheels down, then up, one 100 px notch every 260 ms (faster than the 0.45 s
glide, so notches chain) and samples scrollY every frame. A move of more than
1 px against the wheel is a bounce, and a bounce swings the guide car.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import PIN, Gate, landing_url, parse, viewport  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


def main() -> None:
    args = parse(__doc__, widths=(1920, 1440, 1366))
    gate = Gate()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in [w for w in args.widths if w >= 860]:
            vp = viewport(width)
            page = browser.new_page(viewport=vp)
            page.goto(landing_url(args.base), wait_until="load")
            page.wait_for_timeout(3000)
            pin = page.evaluate(PIN)
            if not gate.check(pin is not None, f"{width} gap bars are pinned"):
                page.close()
                continue
            page.evaluate(f"scrollTo(0,{pin[0] - 5})")
            page.wait_for_timeout(1500)
            page.mouse.move(width / 2, vp["height"] / 2)
            page.evaluate("window.__ys=[];(function f(){__ys.push(scrollY);requestAnimationFrame(f)})()")
            for delta in (100, -100):
                page.evaluate("__ys=[]")
                for _ in range(9):
                    page.mouse.wheel(0, delta)
                    page.wait_for_timeout(260)
                page.wait_for_timeout(800)
                ys = page.evaluate("__ys")
                back = [round(b - a) for a, b in zip(ys, ys[1:]) if (b - a) * delta < -1]
                moved = abs(ys[-1] - ys[0]) > 100
                gate.check(moved and not back, f"{width} wheel {delta:+}: never against the wheel",
                           f"{ys[0]:.0f} -> {ys[-1]:.0f}, against: {back[:5] or 'none'}")
            page.close()
        browser.close()
    gate.exit()


if __name__ == "__main__":
    main()
