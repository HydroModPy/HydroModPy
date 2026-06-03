"""Nancon - Python script 05 - Parametric sweep on Sy.

The public Python API exposes parameter overrides on ``project.simulate``.
A sweep is therefore a simple ``for`` loop over the swept values,
calling ``project.simulate(name=..., Sy=value, **fixed)`` once per point.
The catalog stores every run; downstream scripts (07_inspect_catalog)
read them back.

Launch:
    python examples/projects/11_nancon_watershed/python/05_sweep_sy.py
"""

from pathlib import Path

import hydromodpy as hmp

HERE = Path(__file__).resolve().parent
PROJECT_DIR = HERE.parent
CONFIG_PATH = PROJECT_DIR / "01_run_simulation_nwt.toml"

SWEEP_VALUES = [0.001, 0.05, 0.30]
FIXED_PARAMS = {"K": 5e-5, "Ss": 1e-5}


# ---------------------------------------------------------------------
# 1. Open the project once
# ---------------------------------------------------------------------

project = hmp.Project(CONFIG_PATH)


# ---------------------------------------------------------------------
# 2. Sweep via an explicit for loop
# ---------------------------------------------------------------------

runs = {}
for value in SWEEP_VALUES:
    run = project.simulate(
        name=f"nancon_sweep_sy_{value:.4f}",
        Sy=value,
        **FIXED_PARAMS,
    )
    if run is not None:
        runs[value] = run
        print(f"Sy={value:<6} sim_id={run.sim_id} status={run.status}")


# ---------------------------------------------------------------------
# 3. Release the catalog handle
# ---------------------------------------------------------------------

project.close()
