"""Wrapper that runs one script under coverage without coverage import hooks.

This mirrors the lightweight strategy used by regression helpers: coverage is
started programmatically before any project imports, which avoids the C
extension import issues triggered by ``coverage run`` in some environments.
"""

from __future__ import annotations

import runpy
import sys

import coverage

cov = coverage.Coverage(
    config_file=False,
    data_suffix=True,
    include=["*/hydromodpy/*", "*/validation_cases/*"],
)
cov.start()

script = sys.argv[1]
sys.argv = sys.argv[1:]
runpy.run_path(script, run_name="__main__")

cov.stop()
cov.save()
