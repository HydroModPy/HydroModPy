"""Wrapper that runs a script under coverage measurement.

Usage: python coverage_runner.py <script_path>

This mirrors the canonical source list from ``pyproject.toml`` but keeps using
``config_file=False`` + ``include`` to avoid coverage import hooks, which can
break numpy, dask, rasterio, and other compiled dependencies in script-style
regression runs.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

import coverage

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.ci.coverage_helpers import coverage_include_patterns

cov = coverage.Coverage(
    config_file=False,
    data_suffix=True,
    include=coverage_include_patterns(),
)
cov.start()

script = sys.argv[1]
sys.argv = sys.argv[1:]  # so the script sees itself as sys.argv[0]
runpy.run_path(script, run_name="__main__")

cov.stop()
cov.save()
