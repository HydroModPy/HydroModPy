"""Cellular Python workflow for the Nançon transient example.

The validated TOML remains the source of truth. The cells below show how to
drive the public :class:`hydromodpy.Project` phase API step by step.
"""

# %% Imports and config
from __future__ import annotations

import time
from pathlib import Path

import hydromodpy as hmp
from hydromodpy.master_config.hydromodpy_config import HydroModPyConfig

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "run_transient_nwt.toml"

cfg = HydroModPyConfig.from_toml(CONFIG_PATH)
project = hmp.Project.lazy(cfg)


try:
    # %% Build the geographic context once
    t0 = time.perf_counter()
    project.build_geographic()
    print(f"geographic built in {time.perf_counter() - t0:.2f} s")

    # %% Load the external forcings once
    t0 = time.perf_counter()
    project.load_data()
    print(f"data loaded in {time.perf_counter() - t0:.2f} s")

    # %% Build or iterate on mesh without reloading data
    sizes = [30.0, 50.0, 100.0, 200.0, 500.0] if cfg.mesh_catchment is not None else [None]
    for size in sizes:
        t0 = time.perf_counter()
        if size is None:
            project.build_mesh()
        else:
            project.build_mesh(cell_size=size)
        dt = time.perf_counter() - t0
        mesh = project.workflow_context.setup.mesh_planar
        n_cells = int(mesh.n_cells) if mesh is not None else 0
        label = "default" if size is None else f"{size:>6}"
        print(f"cell_size={label} -> n_cells={n_cells:>6} (mesh in {dt:.2f} s)")

    # %% Run one simulation on the last mesh
    run = project.run(name="cellular_final")
    if run is not None:
        print(f"run sim_id={run.sim_id} status={run.status}")
finally:
    project.close()
