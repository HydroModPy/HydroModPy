"""Play project.toml in the lab and read what it builds, as numbers and as files, without
drawing anything. The catchment, the mesh and the layers are printed, the flow is solved, the
model is kept as a run, and the files of the run are opened again: the rasters, the NetCDF
file, the CSV tables and the particle tracks. This is what a batch job does on a machine
with no screen.

    python py1_run.py
"""

# %% Setup

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import xarray as xr

import hydromodpy as hmp

HERE = Path(__file__).resolve().parent

# %% Open the lab

# A lab holds the model in memory and plays the steps of a run one at a time. Nothing is
# built yet: each row of `lab.steps` is a step with its status.
lab = hmp.Lab(HERE / "project.toml")
print(lab.steps[["step", "status"]].to_string(index=False))

# %% The catchment, the DEM and the mesh

# `advance` plays every missing step up to the one named. The catchment is cut out of the
# regional DEM from the outlet, which moves onto the flow network when it lies off it. The
# box around the catchment is the domain of the model, with one cell per pixel of the DEM.
state = lab.advance("build_geographic")
print(state.geographic)
state = lab.advance("load_data")
print(state.data)
state = lab.advance("build_mesh")
print(state.mesh)

# %% The layers the solver will read

# `solve(build_only=True)` writes the MODFLOW 6 model without solving it. Its packages hold
# what the solver reads: one row per layer and one column per cell. The three layers share
# the 50 m under the ground, and K is the same in each.
state = lab.advance("prepare_solver")
built = lab.solve(build_only=True)
mf6 = built["flow_main::modflow6"].solver_model
ground = np.asarray(state.model.geometry.column.top).ravel()
bases = mf6.dis.botm.array
tops = np.vstack([ground, bases[:-1]])
layers = pd.DataFrame(
    {
        "thickness (m)": (tops - bases).mean(axis=1),
        "K (m/s)": mf6.npf.k.array.mean(axis=1),
    },
    index=pd.RangeIndex(1, len(bases) + 1, name="layer"),
)
print(layers.to_string(float_format="{:.3g}".format))

# %% Solve and read the water table

# `lab.read` solves, then reads a variable of the solve: one row per period, one column per
# cell. Nothing is written to runs/ yet. The water table is seepage where it reaches the
# ground.
head = lab.read("head").to_numpy().ravel()
seep = head >= ground
print(
    f"water table from {head.min():.1f} to {head.max():.1f} m, mean depth {(ground - head).mean():.1f} m"
)
print(f"seepage in {seep.mean() * 100:.1f} % of the cells of the box")
print(f"discharge at the outlet: {float(lab.read('discharge').squeeze()) * 86400:.0f} m3/day")

# %% Keep the run

# The run takes the solve of the lab, tracks the particles, and writes the files that
# project.toml asks for. The display is switched off, so it writes no figure.
run = lab.run()
lab.close()
print(run.name, "figures:", len(run.figures))

# %% The files of the run

# The [[export]] blocks wrote these files when the run was sealed.
for path in run.exports:
    print(path.name)

# %% The rasters

# One GeoTIFF per variable. They hold the box of the model, and the water table is nodata
# outside the catchment.
for name in ["watertable_elevation_first", "watertable_depth_first", "seepage_mask_first"]:
    with rasterio.open(next(path for path in run.exports if path.name == f"{name}.tif")) as src:
        values = src.read(1, masked=True)
        print(
            f"{name}: {src.height} x {src.width} pixels of {src.res[0]:.0f} m, "
            f"mean {values.mean():.3f}, from {values.min():.3f} to {values.max():.3f}"
        )

# %% The NetCDF file

# The three fields in one file, readable by QGIS or by xarray.
fields = xr.open_dataset(next(path for path in run.exports if path.name == "fields.nc"))
print(fields)
fields.close()

# %% The tables

# The water budget and the discharge at the outlet, as CSV.
for name in ["budget", "discharge"]:
    table = pd.read_csv(next(path for path in run.exports if path.name == f"{name}.csv"))
    print(name)
    print(table.to_string(index=False))

# %% The particle tracks

# One line per particle, with its travel time in years from the cell where it entered to the
# place where it leaves the aquifer.
tracks = gpd.read_file(next(path for path in run.exports if path.name == "pathlines.gpkg"))
years = tracks["travel_yr"].to_numpy()
print(
    f"{len(years)} particles, median travel time {np.median(years):.1f} years, "
    f"mean {years.mean():.1f} years, 90 % leave within {np.quantile(years, 0.9):.0f} years"
)

# %% Read the run again without solving

# The run is on disk. Any variable is read back from its store, with no figure and no
# solver, here the depth of the water table over the catchment.
depth = run.read("watertable_depth").to_numpy().ravel()
print(f"watertable depth: mean {np.nanmean(depth):.2f} m over {depth.size} cells")
