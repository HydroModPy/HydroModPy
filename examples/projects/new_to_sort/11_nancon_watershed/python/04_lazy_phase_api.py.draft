"""Nancon - Python script 04 - Lazy phase-by-phase Python driver.

`Project.lazy(...)` returns a Project that has NOT built the geographic
context, NOT loaded data, NOT built the mesh. The caller drives each
phase explicitly. Use this when you want to:

* time each phase separately (profiling),
* iterate on the mesh size without reloading data,
* probe the workflow context between phases.

The pattern below builds geographic + data once, then iterates over a
list of cell sizes, regenerating only the mesh each time. The last
mesh is used for one final simulation.

Launch:
    python examples/projects/11_nancon_watershed/python/04_lazy_phase_api.py
"""

import time
from pathlib import Path

import hydromodpy as hmp
from hydromodpy import HydroModPyConfig

HERE = Path(__file__).resolve().parent
PROJECT_DIR = HERE.parent
CONFIG_PATH = PROJECT_DIR / "01_run_simulation_nwt.toml"


# ---------------------------------------------------------------------
# 1. Build a Project with NO setup phase run yet
# ---------------------------------------------------------------------

cfg = HydroModPyConfig.from_toml(CONFIG_PATH)
project = hmp.Project.lazy(cfg)


# ---------------------------------------------------------------------
# 2. Build the geographic context once
# ---------------------------------------------------------------------

t0 = time.perf_counter()
project.build_geographic()
print(f"geographic built in {time.perf_counter() - t0:.2f} s")


# ---------------------------------------------------------------------
# 3. Load the external forcings once
# ---------------------------------------------------------------------

t0 = time.perf_counter()
project.load_data()
print(f"data loaded in {time.perf_counter() - t0:.2f} s")


# ---------------------------------------------------------------------
# 4. Iterate over mesh cell sizes without reloading data
# ---------------------------------------------------------------------

for size in [50.0, 100.0, 200.0, 500.0]:
    t0 = time.perf_counter()
    project.build_mesh(cell_size=size)
    dt = time.perf_counter() - t0
    mesh = project.workflow_context.setup.mesh_planar
    n_cells = int(mesh.n_cells) if mesh is not None else 0
    print(f"cell_size={size:>6} -> n_cells={n_cells:>6} (mesh in {dt:.2f} s)")


# ---------------------------------------------------------------------
# 5. Run one simulation on the final mesh
# ---------------------------------------------------------------------

run = project.run(name="nancon_lazy_final")


# ---------------------------------------------------------------------
# 6. Inspect and close
# ---------------------------------------------------------------------

if run is not None:
    print(f"final run sim_id={run.sim_id} status={run.status}")

project.close()
