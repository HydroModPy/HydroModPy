"""Nancon - Python script 01 - Run a TOML config from Python.

This is the simplest Python entry point. It does what `hmp run` does
but from a Python file, which is convenient when you want to:

* drive HydroModPy from a notebook,
* read the catalog right after the run,
* or chain follow-up logic on the returned `Run` object.

The TOML is the SINGLE SOURCE OF TRUTH. Nothing here overrides any
field; we just hand the validated config to `Project(...)` and call
`project.run()`.

Launch:
    python examples/projects/11_nancon_watershed/python/01_run_from_toml.py
"""

from pathlib import Path

import hydromodpy as hmp

HERE = Path(__file__).resolve().parent
PROJECT_DIR = HERE.parent
CONFIG_PATH = PROJECT_DIR / "01_run_simulation_nwt.toml"


# ---------------------------------------------------------------------
# 1. Open the project from a TOML path
# ---------------------------------------------------------------------

project = hmp.Project(CONFIG_PATH)


# ---------------------------------------------------------------------
# 2. Run one simulation
# ---------------------------------------------------------------------

run = project.run()


# ---------------------------------------------------------------------
# 3. Inspect the result and release the catalog handle
# ---------------------------------------------------------------------

if run is not None:
    print(f"sim_id={run.sim_id} name={run.name} status={run.status}")

project.close()
