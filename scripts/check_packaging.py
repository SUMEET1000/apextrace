"""Every session the manifest advertises must have its artefacts on disk.

store.read_artefact returns an empty frame for a missing file and the API
returns every manifest row, so a session dropped from the image is still
offered by the picker. Nothing else catches that.

The expected session count is an argument, not a constant, because this runs
against two different datasets: the source tree, which stays at 295 whatever
happens, and the image, which a shrink rung makes smaller. One constant would
mean a rung that lowered it broke the source-tree run.

weather is excluded deliberately: build_dataset.py:99-100 writes it only when
the session has it, so its absence is not a packaging fault.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pitwall import config, store  # noqa: E402

REQUIRED = ("laps", "telemetry", "trackmap", "corners", "results")

if len(sys.argv) != 2:
    print("usage: check_packaging.py <expected-session-count>")
    sys.exit(2)
expected = int(sys.argv[1])

manifest = store.read_manifest()
if len(manifest) != expected:
    print(f"manifest has {len(manifest)} sessions, expected {expected}")
    sys.exit(1)

missing = [
    f"{row.slug}/{name}"
    for row in manifest.itertuples()
    for name in REQUIRED
    if not (config.PROCESSED_DIR / str(row.slug) / f"{name}.parquet").is_file()
]
print(f"{len(manifest)} sessions advertised, {len(missing)} missing artefacts")
for item in missing[:20]:
    print("  missing:", item)
sys.exit(1 if missing else 0)
