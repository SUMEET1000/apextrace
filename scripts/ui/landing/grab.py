"""Landing: the guide car can be grabbed and turned, and the gap bars glide in.

At the hero and inside the pinned bars: the car is found by hover (html gets
.car-grab), a drag changes its pose, release eases it back to the path pose,
the click that follows a press on the car is eaten, and a click off the car
still reaches the page. Then the entry glide: a notch into the first bar must
show at least one frame between 5% and 95% of the step, which a jump never
does. Headless frames run about 200 ms here because the car renders in
software (measured 26 Sept 2026: the glide showed 0.64, 0.88, 0.96; a jump
went straight to 1.0), so an easing that is merely too fast, such as the
expo-out that covered 86% in its first frame at full frame rate, is not
something this check can see.
"""

from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import GL_ARGS, PIN, Gate, landing_url, parse, viewport, watch_errors  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

OUT = Path(tempfile.gettempdir()) / "apextrace-grab"
HOVER = "document.documentElement.classList.contains('car-grab')"


def shot(page, box):
    return np.asarray(Image.open(io.BytesIO(page.screenshot(clip=box)))).astype(int)


def find_car(page, width, height):
    """Centre of the densest patch of navy paint, confirmed by the hover class."""
    full = shot(page, {"x": 0, "y": 60, "width": width, "height": height - 60})
    r, b = full[..., 0], full[..., 2]
    ys, xs = np.nonzero((b > r + 12) & (r < 90))
    if len(xs) <= 30:
        return None
    hist, xe, ye = np.histogram2d(xs, ys, bins=[width // 30, (height - 60) // 30])
    i, j = np.unravel_index(hist.argmax(), hist.shape)
    sel = (xs >= xe[i]) & (xs < xe[i + 1]) & (ys >= ye[j]) & (ys < ye[j + 1])
    cx, cy = int(xs[sel].mean()), int(ys[sel].mean()) + 60
    for dx, dy in [(0, 0), (4, 0), (-4, 0), (0, 4), (0, -4), (8, 0), (-8, 0), (0, 8), (0, -8)]:
        page.mouse.move(cx + dx, cy + dy)
        if page.evaluate(HOVER):
            return cx + dx, cy + dy
    return None


def main() -> None:
    args = parse(__doc__, widths=(1440,))
    OUT.mkdir(exist_ok=True)
    gate = Gate()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=GL_ARGS)
        for width in [w for w in args.widths if w >= 860]:
            height = viewport(width)["height"]
            page = browser.new_page(viewport=viewport(width))
            errors = watch_errors(page)
            page.goto(landing_url(args.base), wait_until="load")
            page.wait_for_timeout(7000)
            page.evaluate("window.__clicks=0;document.addEventListener('click',()=>__clicks++)")
            for where in ("hero", "bars"):
                case = f"{width} {where}"
                if where == "bars":
                    pin = page.evaluate(PIN)
                    if not gate.check(pin is not None, f"{case} gap bars are pinned"):
                        continue
                    a, e = pin
                    page.evaluate(f"scrollTo(0,{a + (e - a) * 2.5 / 7})")
                    page.wait_for_timeout(8000)
                spot = find_car(page, width, height)
                if not gate.check(spot is not None, f"{case} car found by hover"):
                    page.screenshot(path=str(OUT / f"miss-{where}.png"))
                    continue
                x, y = spot
                box = {"x": max(0, x - 150), "y": max(0, y - 150), "width": 300, "height": 300}
                page.mouse.move(x, y - 400 if y > 420 else y + 400)
                page.wait_for_timeout(100)
                base = shot(page, box)
                noise = 0.0
                for _ in range(4):   # idle shake and smoke change every frame
                    page.wait_for_timeout(700)
                    noise = max(noise, float(np.abs(shot(page, box) - base).mean()))
                page.mouse.move(x, y)
                page.wait_for_timeout(100)
                base, clicks = shot(page, box), page.evaluate("__clicks")
                page.mouse.down()
                held = page.evaluate("document.documentElement.classList.contains('car-grabbing')")
                for i in range(1, 11):
                    page.mouse.move(x + 16 * i, y + 5 * i)
                    page.wait_for_timeout(30)
                page.wait_for_timeout(300)
                during = shot(page, box)
                page.mouse.up()
                page.mouse.move(x, y)
                page.wait_for_timeout(2500)
                after = shot(page, box)
                eaten = page.evaluate("__clicks") == clicks
                Image.fromarray(np.hstack([base, during, after]).clip(0, 255).astype("uint8")).save(OUT / f"{where}.png")
                d_held, d_after = float(np.abs(during - base).mean()), float(np.abs(after - base).mean())
                gate.check(held, f"{case} press shows the grabbing hand")
                gate.check(d_held >= 1.0, f"{case} pose changes while held", f"{d_held:.2f}")
                gate.check(d_after <= max(noise * 1.5, 1.0), f"{case} eases back after release",
                           f"{d_after:.2f} against idle noise {noise:.2f}")
                gate.check(eaten, f"{case} the click after a press on the car is eaten")
            page.mouse.move(40, height - 40)
            clicks = page.evaluate("__clicks")
            page.mouse.click(40, height - 40)
            gate.check(page.evaluate("__clicks") == clicks + 1, f"{width} a click off the car reaches the page")
            gate.check(not errors, f"{width} console errors", errors[:3])
            page.close()

            # Entry glide into the first bar.
            page = browser.new_page(viewport=viewport(width))
            page.goto(landing_url(args.base), wait_until="load")
            page.wait_for_timeout(3000)
            pin = page.evaluate(PIN)
            if not gate.check(pin is not None, f"{width} entry: gap bars are pinned"):
                page.close()
                continue
            page.evaluate(f"scrollTo(0,{pin[0]})")
            page.wait_for_timeout(1500)
            page.mouse.move(width / 2, height / 2)
            page.evaluate("window.__ys=[];(function f(){__ys.push(scrollY);requestAnimationFrame(f)})()")
            page.mouse.wheel(0, 100)
            page.wait_for_timeout(1500)
            ys = page.evaluate("__ys")
            y0, y_end = ys[0], ys[-1]
            between = [round((y - y0) / (y_end - y0), 2) for y in ys
                       if y_end > y0 and 0.05 < (y - y0) / (y_end - y0) < 0.95]
            gate.check(y_end > y0 and len(between) >= 1, f"{width} entry glides: a frame between 5% and 95% of the step",
                       f"{y_end - y0:.0f}px step, in-between frames {between[:6] or 'none'}")
            page.close()
        browser.close()
    print(f"screenshots in {OUT}")
    gate.exit()


if __name__ == "__main__":
    main()
