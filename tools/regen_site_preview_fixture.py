"""Regenerate the shared site-preview fixture's expected_preview.json.

Writes to BOTH copies (this repo's tests/fixtures/site_preview/ and the sibling
opengolflab-data/fixtures/site_preview/ when it's checked out), because the two
must stay byte-identical — see that folder's README.

Only run this when you have *decided* the expected output should change, and
make sure opengolflab-data's test_aggregate.py still agrees afterwards. If you
run it to silence a red test, you have deleted the only check that the app and
the website compute the same numbers.

    python -m tools.regen_site_preview_fixture
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import site_preview

APP_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = APP_ROOT.parent / "opengolflab-data"
APP_FIXTURE = APP_ROOT / "tests" / "fixtures" / "site_preview"
DATA_FIXTURE = DATA_ROOT / "fixtures" / "site_preview"


def main() -> int:
    # opengolflab-data holds the canonical inputs (it owns the aggregation
    # rules); the app's copy is a mirror.
    src = DATA_FIXTURE if DATA_FIXTURE.exists() else APP_FIXTURE
    shots_csv = (src / "shots.csv").read_text(encoding="utf-8")
    manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))

    out = site_preview.preview_json(shots_csv, manifest) + "\n"

    for root, d in ((APP_ROOT, APP_FIXTURE), (DATA_ROOT, DATA_FIXTURE)):
        if not root.exists():
            print(f"  - skip {d} (repo not checked out)")
            continue
        d.mkdir(parents=True, exist_ok=True)
        (d / "shots.csv").write_text(shots_csv, encoding="utf-8", newline="")
        (d / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="")
        (d / "expected_preview.json").write_text(out, encoding="utf-8", newline="")
        print(f"  -> wrote {d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
