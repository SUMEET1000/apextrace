"""Shared plumbing for the browser gates in scripts/ui.

Every gate takes ``--base URL`` and optional ``--widths``, records each
assertion through ``Gate.check`` and exits through ``Gate.exit``, so the
printed PASS/FAIL line and the exit code come from the same list. A script
that only prints numbers is a diagnostic, not a gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WIDTHS = (1920, 1440, 1366, 390)
HEIGHTS = {1920: 1080, 1440: 900, 1366: 768, 1024: 768, 390: 844}
# The guide car is WebGL, and headless Chromium only draws it with SwiftShader.
GL_ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]

# Start and end of the pinned gap-bar section, read from the spacer GSAP wraps
# a pinned element in. Works whether GSAP came from a CDN or from npm, where
# ScrollTrigger is not a global.
PIN = """(()=>{const c=document.getElementById('count'),s=c&&c.parentElement;
  if(!s||!s.classList.contains('pin-spacer'))return null;
  const a=s.getBoundingClientRect().top+scrollY;return [a,a+s.offsetHeight-c.offsetHeight]})()"""


def parse(doc: str, widths=WIDTHS, extra=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=doc.strip().splitlines()[0])
    parser.add_argument("--base", required=True,
                        help="app origin such as http://127.0.0.1:4173, or the full URL of a landing .html page")
    parser.add_argument("--widths", default=widths,
                        type=lambda s: tuple(int(w) for w in s.split(",")))
    if extra:
        extra(parser)
    return parser.parse_args()


def landing_url(base: str) -> str:
    return base if base.endswith(".html") else base.rstrip("/") + "/"


def facts() -> dict:
    return json.loads((REPO / "frontend" / "src" / "landing" / "facts.json").read_text(encoding="utf-8"))


def viewport(width: int) -> dict:
    return {"width": width, "height": HEIGHTS.get(width, 900)}


def watch_errors(page) -> list[str]:
    errors: list[str] = []
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(str(e)))
    return errors


class Gate:
    def __init__(self) -> None:
        self.fails: list[str] = []

    def check(self, ok: bool, label: str, detail: object = "") -> bool:
        print(("PASS " if ok else "FAIL ") + label + (f" - {detail}" if detail not in ("", None) else ""))
        if not ok:
            self.fails.append(label)
        return ok

    def exit(self) -> None:
        print(f"{len(self.fails)} failed" if self.fails else "all passed")
        sys.exit(1 if self.fails else 0)
