"""Check the Corner Analysis SVG geometry against fixed chart-data values.

    .venv/Scripts/python scripts/ui/chart_semantics.py --base http://127.0.0.1:5173
"""

from __future__ import annotations

import json
import math
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
                        row.update(lap=[1, 2, 3], time_s=[80, None, 79], pit_lap=[2])
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
            structure = page.evaluate("""() => ({
                answer: document.querySelector('.corner-verdict').getBoundingClientRect().top,
                picker: document.querySelector('.corner-picker').getBoundingClientRect().top,
                ticks: document.querySelectorAll('.corner-progress u').length,
                sections: document.querySelectorAll('.corner-section').length,
                tableOpen: document.querySelector('.corner-table-details').open,
            })""")
            gate.check(structure['picker'] < structure['answer']
                       and structure['ticks'] == structure['sections'] + 1
                       and structure['tableOpen'] == (width > 600),
                       f"{width}: selectors, answer, progress ticks and exact values follow the viewport", structure)
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
            axes = page.locator('[data-chart="trace-panel"] .corner-chart-axes')
            lap_axes = page.locator('[data-chart="lap-by-lap"] .corner-chart-axes')
            gate.check(axes.count() == 5 and lap_axes.count() >= 2
                       and all("LAP DISTANCE (m)" in title for title in
                               axes.locator('.corner-axis-title').all_text_contents())
                       and all("LAP NUMBER" in title for title in
                               lap_axes.locator('.corner-axis-title').all_text_contents()),
                       f"{width}: every graph names its X axis and unit")
            trace_ticks = [row.locator('.corner-chart-axes text').all_text_contents()
                           for row in page.locator('[data-chart="trace-panel"] .corner-trace-row').all()]
            lap_ticks = [row.locator('.corner-chart-axes text').all_text_contents()
                         for row in page.locator('[data-chart="lap-by-lap"] .corner-trace-row').all()]
            gate.check(all(any(unit in tick for tick in trace_ticks[i])
                           for i, unit in ((0, 'km/h'), (1, '%'), (3, 'G'), (4, ' s')))
                       and {'OFF', 'ON'} <= set(trace_ticks[2])
                       and all(any(tick.startswith('L') for tick in row)
                               and any(tick.endswith(' s') for tick in row) for row in lap_ticks),
                       f"{width}: graph ticks carry units, brake states and lap numbers")
            legend = page.locator('[data-chart="trace-panel"] .corner-chart-legend')
            labels = legend.locator('strong').all_text_contents()
            samples = legend.locator('.corner-legend-line').evaluate_all("""nodes => nodes.map(e => {
                const s = getComputedStyle(e); return [s.borderTopColor, s.borderTopStyle];
            })""")
            lines = page.locator('[data-chart="trace-panel"] .corner-trace-row').first.locator('path').evaluate_all(
                "nodes => nodes.map(e => getComputedStyle(e).stroke)")
            gate.check(labels == ['RUS', 'VER'] and samples == [[lines[0], 'solid'], [lines[1], 'dashed']]
                       and 'REFERENCE' in legend.inner_text() and 'COMPARE' in legend.inner_text(),
                       f"{width}: driver legend names both roles and matches graph line styles",
                       f"{labels}, {samples}, {lines}")
            clips = page.locator('[data-chart="trace-panel"] [data-plot-draw]')
            initial_widths = [float(clip.get_attribute('width')) for clip in clips.all()]
            gate.check(len(initial_widths) == 5 and all(value == 0 for value in initial_widths),
                       f"{width}: telemetry lines wait for scroll to draw", initial_widths)
            page.evaluate("""() => {
                const svg = document.querySelector('[data-chart="trace-panel"] .corner-trace-row svg');
                scrollTo(0, scrollY + svg.getBoundingClientRect().top - innerHeight * .77);
            }""")
            page.wait_for_timeout(100)
            midway = float(clips.first.get_attribute('width'))
            page.wait_for_timeout(900)
            finished = float(clips.first.get_attribute('width'))
            gate.check(0 < midway < 687 and abs(finished - 687) < .1,
                       f"{width}: telemetry completes after entry without further scrolling",
                       f"mid={midway:.1f}, finished={finished:.1f}")
            clipped_ticks = page.locator('.corner-chart-axes text').evaluate_all("""nodes => nodes.filter(e => {
                const b = e.getBBox(), v = e.ownerSVGElement.viewBox.baseVal;
                return b.x < -0.5 || b.y < -0.5 || b.x + b.width > v.width + 0.5
                    || b.y + b.height > v.height + 0.5;
            }).map(e => e.textContent)""")
            gate.check(not clipped_ticks, f"{width}: axis labels fit their SVG viewboxes", clipped_ticks[:4])
            bar_head = page.locator('[data-chart="corner-delta-bars"] .corner-bar-axis').inner_text()
            gate.check('SEGMENT' in bar_head and '(s)' in bar_head and '0 s' in bar_head,
                       f"{width}: corner bars show measure, unit and zero scale", bar_head[:100])
            fill = page.locator('[data-chart="corner-delta-bars"] .corner-bar-track > div').first
            initial_scale = fill.evaluate("e => new DOMMatrix(getComputedStyle(e).transform).a")
            page.evaluate("""() => {
                const bars = document.querySelector('[data-chart="corner-delta-bars"] .corner-bars');
                scrollTo(0, scrollY + bars.getBoundingClientRect().top - innerHeight * .77);
            }""")
            page.wait_for_timeout(100)
            midway_scale = fill.evaluate("e => new DOMMatrix(getComputedStyle(e).transform).a")
            page.wait_for_timeout(850)
            final_scale = fill.evaluate("e => new DOMMatrix(getComputedStyle(e).transform).a")
            gate.check(initial_scale == 0 and 0 < midway_scale < 1 and abs(final_scale - 1) < .01,
                       f"{width}: segment bars grow from zero and finish without further scrolling",
                       f"{initial_scale:.2f} -> {midway_scale:.2f} -> {final_scale:.2f}")
            page.locator('[data-chart="lap-by-lap"] .corner-chart-scrubber input').press('ArrowRight')
            lap_readout = page.locator('[data-chart="lap-by-lap"] .corner-chart-readout').inner_text()
            pit_guides = page.locator('[data-chart="lap-by-lap"] .corner-pit-guide')
            gate.check('Per-lap delta: no pair · running sum: no pair' in lap_readout
                       and pit_guides.locator('text').count() == 0
                       and pit_guides.locator('title').count() > 0,
                       f"{width}: missing lap pairs and pit guides stay readable", lap_readout[-90:])
            for name, selector in (("header", ".corner-verdict"),
                                   ("replay", ".corner-replay")):
                surface = page.locator(selector)
                paths = surface.locator(".sector-circuit > polyline").all()
                colours = [path.evaluate("e => getComputedStyle(e).stroke") for path in paths[1:]]
                swatches = surface.locator(".corner-sector-key i").evaluate_all(
                    "nodes => nodes.map(e => getComputedStyle(e).backgroundColor)")
                gate.check(len(paths) == 4 and len(set(colours)) == 3 and colours == swatches,
                           f"{width}: {name} has three matching sector paths and key",
                           f"paths={len(paths)}, colours={colours}, key={swatches}")
                gate.check(surface.locator("svg text").count() == 0,
                           f"{width}: {name} has no labels on the circuit")
                direction = surface.locator('.sector-circuit .circuit-direction')
                arrow = direction.locator('path').last
                shape = arrow.get_attribute('d') or ''
                gate.check(direction.count() == 1 and arrow.get_attribute('fill') == 'none'
                           and 'H' in shape and 'L' in shape,
                           f"{width}: {name} has a subtle line arrow beside start/finish", shape)
                placement = surface.locator('.sector-circuit').evaluate("""e => {
                    const arrow = e.querySelector('.circuit-direction');
                    const marker = e.querySelector('[aria-label="Start and finish line"] rect');
                    const m = arrow.transform.baseVal.consolidate().matrix;
                    const dx = m.e - (Number(marker.getAttribute('x')) + 6);
                    const dy = m.f - (Number(marker.getAttribute('y')) + 6);
                    const distance = Math.hypot(dx, dy);
                    return {distance, forward: dx * m.a + dy * m.b};
                }""")
                gate.check(18 <= placement['distance'] <= 30
                           and placement['forward'] > placement['distance'] * .7,
                           f"{width}: {name} arrow sits just after the start in travel direction", placement)
            gate.check(page.locator('[data-chart="speed-delta-map"] .circuit-direction').count() == 1,
                       f"{width}: analytical map shows racing direction")
            map_placement = page.locator('[data-chart="speed-delta-map"] svg').evaluate("""e => {
                const arrow = e.querySelector('.circuit-direction');
                const marker = e.querySelector('.corner-map-marks > rect:last-of-type');
                const m = arrow.transform.baseVal.consolidate().matrix;
                const dx = m.e - (Number(marker.getAttribute('x')) + 5);
                const dy = m.f - (Number(marker.getAttribute('y')) + 5);
                const distance = Math.hypot(dx, dy);
                return {distance, forward: dx * m.a + dy * m.b};
            }""")
            gate.check(18 <= map_placement['distance'] <= 30
                       and map_placement['forward'] > map_placement['distance'] * .7,
                       f"{width}: analytical map arrow aligns with its start marker", map_placement)
            map_marks = page.locator('[data-chart="speed-delta-map"] .corner-map-marks')
            marks = map_marks.locator(":scope > g").all()
            boxes = []
            nearby = bool(marks)
            for mark in marks:
                dot = mark.locator("circle")
                label = mark.locator("text")
                dx = float(label.get_attribute("x")) - float(dot.get_attribute("cx"))
                dy = float(label.get_attribute("y")) - 3.5 - float(dot.get_attribute("cy"))
                nearby &= 8 <= math.hypot(dx, dy) <= 41
                boxes.append(label.evaluate("e => { const b = e.getBBox(); return [b.x, b.y, b.width, b.height] }"))
            clear = all(a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0]
                        or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1]
                        for i, a in enumerate(boxes) for b in boxes[:i])
            gate.check(nearby and clear and map_marks.locator(":scope > g line, :scope > g rect").count() == 0,
                       f"{width}: turn numbers sit beside their dots without boxes, leaders or overlap",
                       f"{len(marks)} labels, nearby={nearby}, clear={clear}")
            replay_box = page.locator('.corner-replay-map').evaluate(
                "e => [getComputedStyle(e).backgroundColor, getComputedStyle(e).borderTopWidth]")
            gate.check(replay_box == ['rgba(0, 0, 0, 0)', '0px'],
                       f"{width}: replay circuit sits directly on yellow", replay_box)
            cars = [page.locator(f'.corner-replay-map [data-driver="{driver}"] > g > path:first-child')
                    for driver in ('a', 'b')]
            car_colours = [car.evaluate("e => getComputedStyle(e).fill") for car in cars]
            driver_key = page.locator('.corner-replay-bottom i').evaluate_all(
                "nodes => nodes.map(e => getComputedStyle(e).backgroundColor)")
            gate.check(len(car_colours) == 2 and len(set(car_colours)) == 2
                       and car_colours == driver_key and set(car_colours).isdisjoint(colours),
                       f"{width}: driver markers match their key and differ from sectors",
                       f"cars={car_colours}, key={driver_key}")
            opacity = page.locator('.corner-replay-map [data-driver]').evaluate_all(
                "nodes => nodes.map(e => getComputedStyle(e).opacity)")
            gate.check(opacity == ['1', '1'], f"{width}: overlap does not blend the cars grey", opacity)
            filters = page.locator('.corner-replay-map [data-driver]').evaluate_all(
                "nodes => nodes.map(e => getComputedStyle(e).filter)")
            gate.check(filters == ['none', 'none'], f"{width}: neither car has a glow", filters)
            speed_select = page.get_by_label('Replay speed')
            options = speed_select.locator('option').evaluate_all('nodes => nodes.map(e => Number(e.value))')
            gate.check(options == [1, 2, 4, 8, 10, 15, 20],
                       f"{width}: replay offers all seven playback speeds", options)
            controls = page.locator('.corner-replay-controls').evaluate("""e => ({
                overflow: e.scrollWidth > e.clientWidth + 1,
                heights: [...e.children].map(c => Math.round(c.getBoundingClientRect().height))
            })""")
            gate.check(not controls['overflow'] and all(h == 48 for h in controls['heights']),
                       f"{width}: replay controls fit and share a 48 px height", controls)
            meter = page.locator('.corner-replay-meter')
            meter_state = meter.evaluate("""e => {
                const replay = e.closest('.corner-replay'), marker = e.firstElementChild;
                return {
                    bar: getComputedStyle(e).backgroundImage,
                    marker: getComputedStyle(marker).backgroundColor,
                    position: parseFloat(marker.style.left),
                    labels: [...replay.querySelectorAll('.corner-replay-meter-labels span')].map(n => n.textContent.trim()),
                    ahead: replay.querySelector('.corner-replay-bottom small').textContent.trim()
                };
            }""")
            ahead = meter_state['ahead']
            position = meter_state['position']
            if ahead == 'LEVEL':
                aligned = abs(position - 50) <= .25
            elif ahead == 'RUS ahead':
                aligned = position < 50 and meter_state['marker'] == car_colours[1]
            else:
                aligned = ahead == 'VER ahead' and position > 50 and meter_state['marker'] == car_colours[0]
            a_at = meter_state['bar'].find(car_colours[0])
            b_at = meter_state['bar'].find(car_colours[1])
            gate.check(0 <= a_at < b_at
                       and meter_state['labels'] == ['RUS ahead', 'LEVEL', 'VER ahead'] and aligned,
                       f"{width}: gap meter colours, labels and position follow the driver legend",
                       meter_state)
            replay = page.locator('.corner-replay-map')
            replay.hover()
            moving = replay.locator('svg > g:last-child > g')
            before = moving.get_attribute('transform')
            page.wait_for_timeout(300)
            after = moving.get_attribute('transform')
            gate.check(before != after, f"{width}: replay keeps moving on hover",
                       f"{before} -> {after}")
            speed_select.select_option('20')
            before = moving.get_attribute('transform')
            page.wait_for_timeout(200)
            after = moving.get_attribute('transform')
            gate.check(before != after and speed_select.input_value() == '20',
                       f"{width}: 20x replay selection advances the cars", f"{before} -> {after}")
            page.evaluate("scrollTo(0, (document.documentElement.scrollHeight - innerHeight) / 2)")
            page.wait_for_function("parseFloat(document.querySelector('.corner-progress i').style.width) > 40")
            progress = page.locator('.corner-progress i').evaluate("e => parseFloat(e.style.width)")
            gate.check(45 <= progress <= 55, f"{width}: progress line tracks page scroll", progress)
            gate.check(not errors, f"{width}: no console errors", errors[:2])
            page.close()
            reduced = browser.new_page(viewport=viewport(width), reduced_motion='reduce')
            reduced.route("**/api/chart-data/*", fixture)
            reduced.goto(args.base.rstrip("/") + ROUTE, wait_until="domcontentloaded")
            reduced.locator('[data-chart="trace-panel"]').wait_for(state="visible", timeout=60_000)
            static_widths = [float(clip.get_attribute('width')) for clip in
                             reduced.locator('[data-chart="trace-panel"] [data-plot-draw]').all()]
            gate.check(len(static_widths) == 5 and all(value == 687 for value in static_widths),
                       f"{width}: reduced motion shows complete telemetry immediately", static_widths)
            static_fill = reduced.locator('[data-chart="corner-delta-bars"] .corner-bar-track > div').first
            gate.check(static_fill.evaluate("e => getComputedStyle(e).transform") == 'none',
                       f"{width}: reduced motion shows complete segment bars immediately")
            reduced.close()
        browser.close()
    gate.exit()


if __name__ == "__main__":
    main()
