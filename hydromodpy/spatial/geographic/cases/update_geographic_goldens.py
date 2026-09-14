"""Regenerate every geographic golden reference in one command.

Usage
-----
python hydromodpy/spatial/geographic/cases/update_geographic_goldens.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# The geographic tests that own a committed golden reference. Two of these moved
# to the regression tier; the previous hardcoded list still pointed at
# tests/unit/geographic/ and at two files that never existed in this checkout,
# so the command regenerated nothing and said so with an exit code nobody read.
# tests/unit/geographic/test_golden_regeneration_paths.py keeps this list honest.
GOLDEN_TEST_PATHS = (
    "tests/regression/fast/geographic/test_run_geographic_dem_processing_golden.py",
    "tests/regression/fast/geographic/test_run_geographic_river_network_golden.py",
    "tests/unit/geographic/test_catchment_delineation_outlet.py",
    "tests/unit/geographic/test_catchment_delineation_polygon.py",
)


def main(argv: list[str] | None = None) -> int:
    """Run pytest on geographic golden tests with ``--update-goldens``."""
    extra_args = list(argv or [])
    repo_root = Path(__file__).resolve().parents[3]
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *GOLDEN_TEST_PATHS,
        "-q",
        "--update-goldens",
        *extra_args,
    ]
    completed = subprocess.run(cmd, cwd=str(repo_root), check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
