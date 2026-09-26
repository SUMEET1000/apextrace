"""States gate: every analysis route shows loading, empty and error states.

Playwright routes stand in for the API, per route:
  held       every /api/* request held 8 s: the shell is up at once, the data
             area counts seconds, says the server is waking after 3 s, and the
             page settles once the requests go through
  empty      an empty manifest, then a session with no drivers: "Nothing to show"
  500        a plain-text 500 on /api/manifest: the status in an alert with a
             Retry button, and Retry recovers once the API answers again
  404        the API's own "not in the manifest" detail on /api/session
  409        Corner Analysis only: the real corner-issue refusal on /api/corner-analysis
  race 404   Race Arc only: the API's own "No lap data" detail on /api/race-arc

    "$PY" scripts/ui/states.py --base http://127.0.0.1:4173
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Gate, parse, viewport, watch_errors  # noqa: E402
from playwright.sync_api import Error as PlaywrightError, sync_playwright  # noqa: E402

ROUTES = {
    "corner": "/corner-analysis?year=2024&round=12&session=Q&drivers=RUS,VER",
    "race": "/race-arc?year=2024&round=1&session=R",
}
HOLD_S = 8
# Texts the API itself sends (api/main.py, pitwall/corners.py).
NOT_IN_MANIFEST = "Session {} is not in the manifest"
SLUGS = {"corner": "2024/12_Q", "race": "2024/01_R"}
CORNER_409 = ("Corner analysis is unavailable for this session because 2 corner marker(s) have no "
              "distance. Lap times, strategy and degradation are unaffected.")
NO_LAP_DATA = "No lap data available for this session"

BUSY = "document.querySelector('[aria-busy=\"true\"]')"


def text_of(page, selector: str) -> str:
    loc = page.locator(selector)
    return loc.first.inner_text() if loc.count() else ""


def settled(page, timeout_ms: int = 60_000) -> str | None:
    try:
        page.wait_for_function(f"!{BUSY}", timeout=timeout_ms)
    except PlaywrightError:
        return f"still loading after {timeout_ms // 1000} s: {text_of(page, '[aria-busy=true]')!r}"
    page.wait_for_timeout(500)
    return None


def fulfil_json(status: int, body: dict):
    return lambda route: route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


def empty_session(route):
    body = route.fetch().json()
    body["drivers"], body["driver_laps"] = [], {}
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))


def open_page(browser, base: str, route: str, width: int, setup):
    ctx = browser.new_context(viewport=viewport(width))
    page = ctx.new_page()
    errors = watch_errors(page)
    setup(page)
    page.goto(base.rstrip("/") + route, wait_until="domcontentloaded", timeout=60_000)
    return ctx, page, errors


def expect_alert(gate: Gate, page, label: str, wanted: str) -> None:
    why = settled(page)
    alert = text_of(page, "[role=alert]")
    retry = page.get_by_role("button", name=re.compile("retry", re.I)).count()
    gate.check(not why and wanted in alert and retry > 0, label,
               why or f"alert {alert!r}, retry buttons {retry}, wanted {wanted!r}")


def run(gate: Gate, browser, base: str, name: str, route: str, width: int) -> None:
    tag = f"{name} {width}"

    # held: nothing from the API for HOLD_S seconds.
    held: list = []
    released = False

    def hold(r):
        r.continue_() if released else held.append(r)

    ctx, page, errors = open_page(browser, base, route, width, lambda p: p.route("**/api/**", hold))
    page.wait_for_timeout(1200)
    shell = page.locator("header nav a").count()
    busy = text_of(page, "[aria-busy=true]")
    chip = text_of(page, ".eng")
    gate.check(shell >= 2 and re.search(r"loading .* \d+ s", busy, re.I) is not None and "WAKING" in chip,
               f"{tag} held: shell and seconds counter at 1.2 s",
               f"nav links {shell}, busy {busy!r}, chip {chip!r}")
    early = "waking" in busy.lower()
    page.wait_for_timeout(3300)
    busy = text_of(page, "[aria-busy=true]")
    seconds = re.search(r"(\d+) s", busy)
    gate.check(not early and "server is waking up" in busy.lower() and seconds is not None and int(seconds.group(1)) >= 3,
               f"{tag} held: waking message after 3 s, not before",
               f"at 1.2 s waking shown={early}; at 4.5 s {busy!r}")
    page.wait_for_timeout((HOLD_S - 4.5) * 1000)
    released = True
    for r in held:
        r.continue_()
    why = settled(page)
    alert = text_of(page, "[role=alert]")
    gate.check(not why and not alert and not errors, f"{tag} held: settles once the API answers",
               why or alert or errors[:2])
    ctx.close()

    # empty manifest
    ctx, page, _ = open_page(browser, base, route, width,
                             lambda p: p.route("**/api/manifest*", fulfil_json(200, {"sessions": [], "years": [], "featured": []})))
    why = settled(page)
    gate.check(not why and "nothing to show" in page.inner_text("main").lower(), f"{tag} empty manifest", why or page.inner_text("main")[:120])
    ctx.close()

    # empty session
    ctx, page, _ = open_page(browser, base, route, width, lambda p: p.route("**/api/session?*", empty_session))
    why = settled(page)
    gate.check(not why and "nothing to show" in page.inner_text("main").lower(), f"{tag} empty session", why or page.inner_text("main")[:120])
    ctx.close()

    # 500, plain text, then Retry
    ctx, page, _ = open_page(browser, base, route, width,
                             lambda p: p.route("**/api/manifest*", lambda r: r.fulfill(status=500, body="Internal Server Error")))
    expect_alert(gate, page, f"{tag} 500 on manifest", "500")
    page.unroute("**/api/manifest*")
    page.get_by_role("button", name=re.compile("retry", re.I)).first.click()
    why = settled(page)
    gate.check(not why and not text_of(page, "[role=alert]") and page.locator(".pw-main").count() == 1,
               f"{tag} Retry recovers", why or text_of(page, "[role=alert]"))
    ctx.close()

    # 404 with the API's detail
    ctx, page, _ = open_page(browser, base, route, width,
                             lambda p: p.route("**/api/session?*", fulfil_json(404, {"detail": NOT_IN_MANIFEST.format(SLUGS[name])})))
    expect_alert(gate, page, f"{tag} 404 on session", NOT_IN_MANIFEST.format(SLUGS[name]))
    ctx.close()

    endpoint, status, detail = (("**/api/corner-analysis?*", 409, CORNER_409) if name == "corner"
                                else ("**/api/race-arc?*", 404, NO_LAP_DATA))
    ctx, page, _ = open_page(browser, base, route, width, lambda p: p.route(endpoint, fulfil_json(status, {"detail": detail})))
    expect_alert(gate, page, f"{tag} {status} on {endpoint.split('/')[-1].rstrip('?*')}", detail)
    ctx.close()


def main() -> None:
    args = parse(__doc__, widths=(1440, 390))
    gate = Gate()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in args.widths:
            for name, route in ROUTES.items():
                run(gate, browser, args.base, name, route, width)
        browser.close()
    gate.exit()


if __name__ == "__main__":
    main()
