"""Landing: the guide car parks on the hero photo band, right end, at its size.

The spot is 08's (kept 26 Sept 2026): side view, wheels on the band's bottom
line, 3% of the width in from the right, length min(224, 0.128 vw, 0.96 x band
height). The car is found as the dark pixels that are there with the car
canvas shown and gone with it hidden, inside a box around that spot.
"""

from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import GL_ARGS, Gate, landing_url, parse, viewport, watch_errors  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

OUT = Path(tempfile.gettempdir()) / "apextrace-herocar"
BAND = "(()=>{const r=document.querySelector('.hero .photo').getBoundingClientRect();return [r.bottom,r.height]})()"


def rgb(page, box):
    return np.asarray(Image.open(io.BytesIO(page.screenshot(clip=box))).convert("RGB")).astype(int)


def main() -> None:
    args = parse(__doc__, widths=(1920, 1440, 1366))
    OUT.mkdir(exist_ok=True)
    gate = Gate()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=GL_ARGS)
        for width in [w for w in args.widths if w >= 860]:
            page = browser.new_page(viewport=viewport(width))
            errors = watch_errors(page)
            page.goto(landing_url(args.base), wait_until="load")
            page.wait_for_timeout(7500)   # the car drives in 3.3 s after load and takes 1.8 s to park
            bottom, band_h = page.evaluate(BAND)
            length = min(224, width * 0.128, band_h * 0.96)
            want_x = width - width * 0.03 - length / 2
            box = {"x": max(0, want_x - length), "y": max(0, bottom - length * 0.6),
                   "width": length * 2, "height": length * 0.6 + 30}
            shown = rgb(page, box)
            page.evaluate("document.getElementById('car').style.visibility='hidden'")
            hidden = rgb(page, box)
            page.evaluate("document.getElementById('car').style.visibility=''")
            dark = shown.max(axis=2) < 110
            changed = np.abs(shown - hidden).sum(axis=2) > 60
            ys, xs = np.nonzero(dark & changed & (hidden.max(axis=2) >= 110))
            Image.fromarray(np.vstack([shown, hidden]).astype("uint8")).save(OUT / f"{width}.png")
            case = f"{width}"
            if not gate.check(len(xs) > 50, f"{case} car drawn near its hero spot", f"{len(xs)} car pixels"):
                continue
            left, right = box["x"] + xs.min(), box["x"] + xs.max()
            low = box["y"] + ys.max()
            gate.check(0.75 * length <= right - left <= 1.15 * length, f"{case} car length",
                       f"{right - left:.0f}px, expected about {length:.0f}px")
            gate.check(abs((left + right) / 2 - want_x) <= 0.15 * length, f"{case} car at the band's right end",
                       f"centre x {(left + right) / 2:.0f}, expected {want_x:.0f}")
            gate.check(abs(low - (bottom - 3)) <= 6, f"{case} wheels on the band's bottom line",
                       f"lowest car pixel {low:.0f}, band bottom {bottom:.0f}")
            gate.check(not errors, f"{case} console errors", errors[:3])
            page.close()
        browser.close()
    print(f"screenshots in {OUT}")
    gate.exit()


if __name__ == "__main__":
    main()
