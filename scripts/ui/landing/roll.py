"""Landing: the spec numbers roll to their final values and never roll back.

Scrolls until the spec line is near the top, checks every digit column has
reached its data-to position, then scrolls back up and checks nothing moved.
With reduced motion the numbers are plain text, so there is nothing to roll.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import Gate, landing_url, parse, viewport  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

COLUMNS = "()=>[...document.querySelectorAll('.spec .s')].map(s=>[s.dataset.to,s.style.transform])"


def main() -> None:
    args = parse(__doc__)
    gate = Gate()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in args.widths:
            vp = viewport(width)
            page = browser.new_page(viewport=vp)
            page.goto(landing_url(args.base), wait_until="load")
            page.wait_for_timeout(4000)
            page.mouse.move(width / 2, vp["height"] / 2)
            for _ in range(400):
                if page.evaluate("document.querySelector('.spec').getBoundingClientRect().top") <= 200:
                    break
                page.mouse.wheel(0, 200)
                page.wait_for_timeout(50)
            page.wait_for_timeout(1500)
            down = page.evaluate(COLUMNS)
            # The page writes -to * 1, and JavaScript prints -0 as "0".
            final = bool(down) and all(t == f"translateY({-float(to) or 0.0:g}em)" for to, t in down)
            gate.check(final, f"{width} spec digits reach their final values",
                       [t for _, t in down if t][:4] or "no digit columns")
            for _ in range(15):
                page.mouse.wheel(0, -200)
                page.wait_for_timeout(50)
            page.wait_for_timeout(1500)
            up = page.evaluate(COLUMNS)
            gate.check(up == down, f"{width} spec digits stay after scrolling back up",
                       [b for (_, a), (_, b) in zip(down, up) if a != b][:4])
            page.close()
        browser.close()
    gate.exit()


if __name__ == "__main__":
    main()
