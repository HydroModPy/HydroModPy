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
