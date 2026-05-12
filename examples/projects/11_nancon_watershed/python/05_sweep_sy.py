"""Nancon - Python script 05 - Parametric sweep on Sy.

Until the `[sweep]` workflow lands in the CLI dispatcher, sweeps live
in Python. Two equivalent ways are shown:

* High-level: `project.sweep({...})` - one call, every variant is
  routed through the regular run pipeline and stored in the catalog.
* Low-level: a Python `for` loop over `project.run(name=..., **kw)`.
  Useful when each iteration depends on the previous one, or when you
  need custom names per iteration.

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
# 1. Sweep via an explicit for loop
# ---------------------------------------------------------------------

print("== Sweep via explicit loop ==")

project = hmp.Project(CONFIG_PATH)

runs = {}
for value in SWEEP_VALUES:
    run = project.run(
        name=f"nancon_sweep_sy_{value:.4f}",
        Sy=value,
        **FIXED_PARAMS,
    )
    if run is not None:
        runs[value] = run
        print(f"Sy={value:<6} sim_id={run.sim_id} status={run.status}")

project.close()


# ---------------------------------------------------------------------
# 2. Sweep via the high-level Project.sweep helper
# ---------------------------------------------------------------------

print()
print("== Sweep via Project.sweep ==")

project = hmp.Project(CONFIG_PATH)

group = project.sweep(
    {"Sy": SWEEP_VALUES},
    strategy="enumerate",
    name_template="nancon_sweepapi_sy_{value:.4f}",
)

for sim in group:
    print(f"{sim.name:<35s} sim_id={sim.sim_id} status={sim.status}")

project.close()
