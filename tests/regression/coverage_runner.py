"""Wrapper that runs a script under coverage measurement.

Usage: python coverage_runner.py <script_path>

Uses ``config_file=False`` + ``include`` to avoid coverage's import hooks
(which break numpy, dask, rasterio C extensions).  Only hydromodpy source
files are recorded.
"""

import sys
import runpy
import coverage

# config_file=False  → don't read [tool.coverage.run] source, no import hooks
# include            → only record lines in hydromodpy source files
# data_suffix=True   → write .coverage.<pid> for parallel combine
cov = coverage.Coverage(
    config_file=False,
    data_suffix=True,
    include=["*/hydromodpy/*"],
)
cov.start()

script = sys.argv[1]
sys.argv = sys.argv[1:]  # so the script sees itself as sys.argv[0]
runpy.run_path(script, run_name="__main__")

cov.stop()
cov.save()
