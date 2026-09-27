"""Check the Corner Analysis SVG geometry against fixed chart-data values.

    .venv/Scripts/python scripts/ui/chart_semantics.py --base http://127.0.0.1:5173
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Gate, parse, viewport, watch_errors  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


ROUTE = "/corner-analysis?year=2024&round=12&session=Q&drivers=RUS,VER"


def main() -> None:
    args = parse(__doc__, widths=(1440, 390),
                 extra=lambda p: p.add_argument("--seed-defect", action="store_true"))
    gate = Gate()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in args.widths:
            page = browser.new_page(viewport=viewport(width))
            errors = watch_errors(page)

            def fixture(route):
                body = route.fetch().json()
                chart = body["chart_id"]
                if chart == "trace-panel":
                    for driver in body["drivers"]:
                        driver.update(distance=[0, 50, 100], speed=[110, 115, 120],
                                      throttle=[20, 50, 80], brake=[0, 1, 0], gear=[2, 3, 4])
                    body["drivers"][0]["speed"] = ([100, 110, 120] if args.seed_defect
                                                    else [100, None, 120])
                    body["delta"] = [0.1, None, 0.3]
                    body["finding"] = "The drivers differ by 20 km/h in this fixture."
                elif chart == "lap-by-lap":
                    for row in body["lap_times"]:
                        row.update(lap=[1, 2, 3], time_s=[80, None, 79])
                    body["delta"] = {"lap": [1, 2, 3], "seconds": [0.1, None, -0.1]}
                    body["cumulative"] = {"lap": [1, 2, 3], "seconds": [0.1, None, 0.0]}
                    body["finding"] = "2 comparable lap time pairs are available."
                elif chart == "corner-delta-bars":
                    body.update(labels=["A", "B", "C"], delta_s=[0.1, -0.2, None],
                                faster=["RUS", "VER", ""],
                                finding="RUS gained 0.1 s in A; VER gained 0.2 s in B.")
                route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

            page.route("**/api/chart-data/*", fixture)
            page.goto(args.base.rstrip("/") + ROUTE, wait_until="domcontentloaded")
            page.locator('[data-chart="trace-panel"]').wait_for(state="visible", timeout=60_000)
            speed = page.locator('[data-chart="trace-panel"] .corner-trace-row').nth(0).locator('path').first.get_attribute('d') or ''
            brake = page.locator('[data-chart="trace-panel"] .corner-trace-row').nth(2).locator('path').first.get_attribute('d') or ''
            gear = page.locator('[data-chart="trace-panel"] .corner-trace-row').nth(3).locator('path').first.get_attribute('d') or ''
            laps = page.locator('[data-chart="lap-by-lap"] .corner-trace-row').first.locator('path').first.get_attribute('d') or ''
            bars = page.locator('[data-chart="corner-delta-bars"] .corner-bar-track > div').all()
            gate.check(speed.count('M') == 2, f"{width}: a null breaks the speed line", speed[:80])
            gate.check('H' in brake and 'V' in brake and 'L' not in brake,
                       f"{width}: brake uses steps", brake[:80])
            gate.check('H' in gear and 'V' in gear and 'L' not in gear,
                       f"{width}: gear uses steps", gear[:80])
            gate.check(laps.count('M') == 2, f"{width}: a null breaks the lap line", laps[:80])
            left = bars[1].evaluate("e => parseFloat(e.style.left)")
            right = bars[0].evaluate("e => parseFloat(e.style.left)")
            gate.check(left < 50 and right >= 50, f"{width}: bar direction follows sign",
                       f"negative left={left}, positive left={right}")
            for name, selector in (("header", ".corner-verdict .circuit-labels"),
                                   ("map", '[data-chart="speed-delta-map"] .circuit-labels')):
                marks = page.locator(selector).locator(":scope > g").all()
                clear = bool(marks)
                boxes = []
                for mark in marks:
                    rect = mark.locator("rect")
                    line = mark.locator("line")
                    x = float(rect.get_attribute("x")); y = float(rect.get_attribute("y"))
                    size = float(rect.get_attribute("width"))
                    anchor_x = float(line.get_attribute("x1")); anchor_y = float(line.get_attribute("y1"))
                    clear &= abs(x + size / 2 - anchor_x) > size / 2 or abs(y + size / 2 - anchor_y) > size / 2
                    clear &= all(abs(x - other_x) >= size or abs(y - other_y) >= size
                                 for other_x, other_y in boxes)
                    boxes.append((x, y))
                gate.check(clear, f"{width}: {name} turn boxes clear their turns and each other",
                           f"{len(marks)} labels")
            gate.check(not errors, f"{width}: no console errors", errors[:2])
            page.close()
        browser.close()
    gate.exit()


if __name__ == "__main__":
    main()
