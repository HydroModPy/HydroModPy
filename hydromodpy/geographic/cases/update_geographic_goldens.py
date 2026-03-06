"""Regenerate geographic unit-test golden references in one command.

Usage
-----
python hydromodpy/geographic/cases/update_geographic_goldens.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    """Run pytest on geographic golden tests with ``--update-goldens``."""
    extra_args = list(argv or [])
    repo_root = Path(__file__).resolve().parents[3]
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/unit/geographic/test_geographic_legacy_characterization.py",
        "tests/unit/geographic/test_run_geographic_case_golden.py",
        "tests/unit/geographic/test_run_geographic_dem_processing_golden.py",
        "-q",
        "--update-goldens",
        *extra_args,
    ]
    completed = subprocess.run(cmd, cwd=str(repo_root), check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
