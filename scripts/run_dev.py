"""Run ApexTrace in development: the FastAPI service and the Vite dev server.

    .venv/Scripts/python scripts/run_dev.py

Vite proxies ``/api`` to the backend, so the browser only ever talks to
http://localhost:5173 and development matches the built deployment, where
FastAPI serves ``frontend/dist`` from its own origin.

**One uvicorn worker, deliberately.** The loaders in ``api/cache.py`` are
per-process ``lru_cache`` entries and one of them holds a decoded race
telemetry frame (~74 MB); a second worker would double that for no extra hit
rate. ``store.upsert_manifest`` is also a read-modify-write of a single Parquet
file, so two processes must never both be able to write it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND = REPO_ROOT / "frontend"

VENV_PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
if not VENV_PYTHON.exists():
    VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
if not VENV_PYTHON.exists():
    VENV_PYTHON = Path(sys.executable)


def main() -> int:
    if not (FRONTEND / "node_modules").is_dir():
        print("Frontend dependencies are not installed. Run:\n"
              f"    cd {FRONTEND}\n"
              "    npm install\n")
        return 1

    npm = shutil.which("npm")
    if npm is None:
        print("npm is not on PATH; install Node.js to run the frontend.")
        return 1

    api = subprocess.Popen(
        [str(VENV_PYTHON), "-m", "uvicorn", "api.main:app",
         "--host", "127.0.0.1", "--port", "8000", "--reload"],
        cwd=str(REPO_ROOT),
    )
    web = subprocess.Popen([npm, "run", "dev"], cwd=str(FRONTEND), shell=False)

    print("\nApexTrace is starting")
    print("  App      http://localhost:5173")
    print("  API docs http://localhost:8000/docs")
    print("\nCtrl+C to stop both.\n")

    try:
        # Whichever process exits first ends the session. Leaving the other
        # running would hold its port and quietly break the next start — which
        # is exactly how a stale server ends up serving code you have replaced.
        while True:
            for process in (api, web):
                if process.poll() is not None:
                    return process.returncode or 0
            try:
                api.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                pass
    except KeyboardInterrupt:
        return 0
    finally:
        for process in (web, api):
            if process.poll() is None:
                process.terminate()
        for process in (web, api):
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
