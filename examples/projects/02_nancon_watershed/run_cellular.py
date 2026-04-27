"""Cellular notebook example (Spyder / Jupyter).

Demonstrates the lazy Project API: build each model phase once
(geographic, data) then iterate on mesh parameters without reloading
the DEM or the recharge forcing. Cells are separated by `# %%` so
Spyder and Jupyter can run them step by step. The script also runs
end-to-end as a normal Python file.
"""

# %% Imports and lazy config
# Lazy annotations.
from __future__ import annotations

# Wall-clock timing for each cell.
import time

# Path API.
from pathlib import Path

# Public HydroModPy façade.
import hydromodpy as hmp

# Workspace anchor for the project root.
from hydromodpy.core.workspace.config import WorkspaceConfig

# Folder of this script (project root).
HERE = Path(__file__).resolve().parent
# Shared example data folder.
DATA = HERE.parent.parent / "data"

# Build a fully-typed configuration object in memory.
cfg = hmp.Config(
    # Single-run workflow.
    workflow="simulation",
    # Project root used to resolve relative paths and to host outputs.
    workspace=WorkspaceConfig(project_root=HERE),
    # Watershed delineation from the Nançon outlet.
    geographic=hmp.Geographic.from_outlet(
        x=389285.91,
        y=6816518.749,
        dem=DATA / "dem" / "DEM_armorican_massif.tif",
        snap_dist="150 m",
        buff_area="10%",
        crs_project="EPSG:2154",
    ),
    # Constant-thickness aquifer model.
    domain=hmp.Domain.with_thickness(30.0),
    # Only the data families that this minimal example needs.
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
    # Homogeneous flow parameters and recharge sink.
    flow=hmp.Flow.homogeneous(K=5e-5, Sy=0.05, Ss=1e-5, active_sinks_sources=["recharge"]),
    # Three-year monthly transient.
    simulation=hmp.Sim.transient(
        time=("2000-01-01", "2002-12-31", "1 month"),
        flow="modflownwt",
        name="nancon_cellular",
    ),
)

# `Project.lazy(cfg)` validates the config but does not build anything.
# We then drive build_geographic / load_data / build_mesh by hand so we
# can re-run only the steps we want.
project = hmp.Project.lazy(cfg)


# %% Build the geographic context once
# This step is heavy: DEM read, depression breaching, watershed delineation.
t0 = time.perf_counter()
project.build_geographic()
print(f"geographic built in {time.perf_counter() - t0:.2f} s")


# %% Load the external forcings once
# Recharge and discharge CSV reads happen here. Slow on the first call,
# free afterwards.
t0 = time.perf_counter()
project.load_data()
print(f"data loaded in {time.perf_counter() - t0:.2f} s")


# %% Iterate on the mesh cell size without reloading data
# We mutate the in-memory config between calls. Only the mesh phase is
# rebuilt; the geographic context and the loaded data are reused.
for size in [30.0, 50.0, 100.0, 200.0, 500.0]:
    # Apply the new cell size when the mesh-catchment block is present.
    if project.cfg.mesh_catchment is not None:
        project.cfg.mesh_catchment.cell_size = size
    # Time the remesh step.
    t0 = time.perf_counter()
    project.build_mesh()
    dt = time.perf_counter() - t0
    # Read the active-cell count from the freshly built planar mesh.
    n_cells = project._ctx.setup.mesh_planar.n_cells if project.has_mesh else 0
    print(f"cell_size={size:>6} -> n_cells={n_cells:>6} (remesh in {dt:.2f} s)")


# %% Run one simulation on the last mesh
# Plain `project.run(...)` works once the model phase is ready.
run = project.run(name="cellular_final")
print(f"run sim_id={run.sim_id} status={run.status}")


# Always close the project to release the DuckDB / Zarr handles.
project.close()
