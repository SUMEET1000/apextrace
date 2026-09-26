# Not a gate: it fails the same way on pages from before 25 Sept and nobody
# has explained why. Usage: pinmotion.py <landing-url> <width> <height>
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common import PIN
"""Scrolls down through the pinned gap bars in small wheel steps and tracks the car's centre in
the gap column, measured against the top of the big number's last glyph so a screenshot taken
mid-scroll (which can shift the pinned section a few px) does not count as car motion. While scrolling down, the car may stay or move down; moving up by more than 2 px
is the 'goes the opposite way first' bug. Prints FAIL and exits 1 if it happens."""
import io, sys
import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright
URL, W, H = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
with sync_playwright() as p:
    b = p.chromium.launch(args=['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
    pg = b.new_page(viewport={'width': W, 'height': H}); pg.goto(URL); pg.wait_for_timeout(6000)
    a, e = pg.evaluate(PIN)
    x0, x1 = pg.evaluate("()=>[document.querySelector('#count > div').getBoundingClientRect().right, document.querySelector('#parts').getBoundingClientRect().left]")
    pg.mouse.move(W / 2, H / 2)
    while pg.evaluate('scrollY') < a + (e - a) * .15: pg.mouse.wheel(0, 200); pg.wait_for_timeout(40)
    pg.wait_for_timeout(1200); ys = []
    while pg.evaluate('scrollY') < a + (e - a) * .95:
        pg.mouse.wheel(0, 50); pg.wait_for_timeout(60)
        full = np.asarray(Image.open(io.BytesIO(pg.screenshot(clip={'x': x0 - 30, 'y': 60, 'width': x1 - x0 + 30, 'height': H - 60})))).astype(int)
        ink = (full[:, :24].max(axis=2) < 60).sum(axis=1) > 3; img = full[:, 30:]
        r, g, bl = img[..., 0], img[..., 1], img[..., 2]
        m = (bl > r + 12) & (r < 90)   # navy paint
        ys.append(float(np.nonzero(m)[0].mean()) - float(np.nonzero(ink)[0].min()) if m.sum() > 30 and ink.any() else None)
    b.close()
v = [y for y in ys if y is not None]
back = [round(v[i] - v[i + 1], 1) for i in range(len(v) - 1) if v[i] - v[i + 1] > 2]
print(f'{W}x{H}: {len(v)} samples, y {min(v):.0f}..{max(v):.0f}, backward moves: {back or "none"}')
print('PASS' if not back and len(v) > 20 else 'FAIL'); sys.exit(0 if not back and len(v) > 20 else 1)
