"""Cellular notebook example (Spyder/Jupyter).

Demonstrates Project.lazy() and the manual model-phase verbs: build each
phase once, then iterate on mesh parameters without reloading DEM or
recharge. Run cells with #%% in Spyder or run the script end-to-end.
"""

# %% Imports and lazy config
from __future__ import annotations

import time
from pathlib import Path

import hydromodpy as hmp
from hydromodpy.core.workspace.config import WorkspaceConfig

HERE = Path(__file__).resolve().parent
DATA = HERE.parent.parent / "data"

cfg = hmp.Config(
    workflow="simulation",
    workspace=WorkspaceConfig(project_root=HERE),
    geographic=hmp.Geographic.from_outlet(
        x=389285.91,
        y=6816518.749,
        dem=DATA / "dem" / "DEM_armorican_massif.tif",
        snap_dist="150 m",
        buff_area="10%",
        crs_project="EPSG:2154",
    ),
    domain=hmp.Domain.with_thickness(30.0),
    data=hmp.Data(
        types=["dem", "hydrometry", "recharge"],
        dem=hmp.DEM.from_geotiff(DATA / "dem" / "DEM_armorican_massif.tif"),
        hydrometry=hmp.Hydrometry.from_csv_directory(
            DATA / "hydrometry",
            start="2000-01-01",
            end="2002-12-31",
        ),
        recharge=hmp.Recharge.from_csv_directory(
            DATA / "recharge",
            start="2000-01-01",
            end="2002-12-31",
        ),
    ),
    flow=hmp.Flow.homogeneous(K=5e-5, Sy=0.05, Ss=1e-5, active_sinks_sources=["recharge"]),
    simulation=hmp.Sim.transient(
        time=("2000-01-01", "2002-12-31", "1 month"),
        flow="modflownwt",
        name="nancon_cellular",
    ),
)

project = hmp.Project.lazy(cfg)

# %% Build geographic once (slow: DEM processing, delineation)
t0 = time.perf_counter()
project.build_geographic()
print(f"geographic built in {time.perf_counter() - t0:.2f} s")

# %% Load data once (slow: file reads)
t0 = time.perf_counter()
project.load_data()
print(f"data loaded in {time.perf_counter() - t0:.2f} s")

# %% Iterate on cell_size without reloading DEM or data
for size in [30.0, 50.0, 100.0, 200.0, 500.0]:
    if project.cfg.mesh_catchment is not None:
        project.cfg.mesh_catchment.cell_size = size
    t0 = time.perf_counter()
    project.build_mesh()
    dt = time.perf_counter() - t0
    n_cells = project._ctx.setup.mesh_planar.n_cells if project.has_mesh else 0
    print(f"cell_size={size:>6} -> n_cells={n_cells:>6} (remesh in {dt:.2f} s)")

# %% Run one simulation on the last mesh
run = project.run(name="cellular_final")
print(f"run sim_id={run.sim_id} status={run.status}")

project.close()
