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
try:
    if sys.argv[1] == "-m":
        module_name = sys.argv[2]
        sys.argv = [module_name] + sys.argv[3:]
        runpy.run_module(module_name, run_name="__main__", alter_sys=True)
    else:
        script = sys.argv[1]
        sys.argv = sys.argv[1:]  # so the script sees itself as sys.argv[0]
        runpy.run_path(script, run_name="__main__")
except SystemExit as exc:
    if exc.code != 0:
        import traceback
        print(
            f"\n[coverage_runner] SystemExit(code={exc.code!r}) caught.\n"
            f"Traceback (origin of sys.exit):",
            file=sys.stderr,
        )
        traceback.print_exc(file=sys.stderr)
    raise
except BaseException:
    import traceback
    traceback.print_exc(file=sys.stderr)
    raise
finally:
    cov.stop()
    cov.save()
