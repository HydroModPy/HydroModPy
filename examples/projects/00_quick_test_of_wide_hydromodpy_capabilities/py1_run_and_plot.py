"""Play project.toml in the lab to watch the model take shape, try another K, then keep
the model as a run. HydroModPy draws every figure: the mesh on the relief before the
solve, the figures project.toml lists, and two more asked from Python. The particle
tracks are then written for QGIS.

    python py1_run_and_plot.py
"""

# %% Setup

from pathlib import Path

import flopy
import geopandas as gpd
import numpy as np
from shapely.geometry import LineString

import hydromodpy as hmp

HERE = Path(__file__).resolve().parent
FIGURES = HERE / "summary" / "figures"
FIGURES.mkdir(parents=True, exist_ok=True)

# %% Open the lab

# A lab holds the model in memory and plays the steps of a run one at a time.
lab = hmp.Lab(HERE / "project.toml")

# %% The mesh and the wells

# `prepare_solver` freezes the model. Its `wells` map a name to a position and a rate.
state = lab.advance("prepare_solver")
print(f"{state.mesh.n_cells} cells")
for name, well in state.model.wells.items():
    peak = -min(well.flux) * 86400
    print(f"{name}: x = {well.location.x:.0f} m, y = {well.location.y:.0f} m, {peak:.0f} m³/day")

# %% The mesh on the relief, before the solve

# A run stopped at `prepare_solver` already stores the ground of every cell, so it draws
# the relief under the mesh. It has no seal yet: `lab.run` finishes it further down.
before = lab.run(until_step="prepare_solver")
print(
    before.figure(
        "topography", overlays=["mesh", "network", "outlet"], save=FIGURES / "mesh_on_relief.png"
    )
)

# %% Solve and read the head


# `solve` plays what is left up to the solver. The heads are in the raw MODFLOW 6 files.
def january_head():
    solved = next(run for name, run in lab.solve().items() if "prt" not in name)
    heads = flopy.utils.HeadFile(str(next(Path(solved.output_dir).glob("*.hds")))).get_alldata()
    return np.where(np.abs(heads[0]) < 1e20, heads[0], np.nan).ravel()


print(f"mean head in January, K = 1e-5 m/s: {np.nanmean(january_head()):.3f} m")

# %% Change K

# A new K makes the model stale, and only the two solver steps play again.
lab.set(K=5e-5)
print(lab.steps[["step", "status"]].query("status != 'built'").to_string(index=False))
print(f"mean head in January, K = 5e-5 m/s: {np.nanmean(january_head()):.3f} m")

# %% Keep the run

# Back to the K of the file: the lab forgets changes that bring it back to the
# file, so the run kept is the run of project.toml.
# The test with K = 5e-5 m/s stays in the lab and leaves no trace.
lab.set(K=1e-5)
run = lab.run()
print(run.name)
lab.close()

# %% The figures of the run

# The [display] list of project.toml is drawn when the run is sealed: the catchment card,
# the maps, the section through the two wells, the particle tracks and the water budget.
for path in run.figures:
    print(path)

# %% Two more figures, asked from Python

# `run.figure` takes the keys of a [[display.figure]] table and draws from the sealed run,
# so nothing is solved again. Without `save` it gives back the matplotlib figure.
# The section through the two wells again, in September.
print(
    run.figure(
        "watertable_elevation",
        type="section",
        line=[[152700.0, 6858862.5], [152700.0, 6856762.5]],
        time="2017-09-15",
        save=FIGURES / "section_through_wells_september.png",
    )
)
# The water-table depth of January with the well cells and the seepage cells.
print(
    run.figure(
        "watertable_depth",
        time="2017-01-15",
        overlays=["outline", "network", "wells", "seepage"],
        save=FIGURES / "watertable_depth_wells_and_seepage.png",
    )
)

# %% The numbers behind a figure

# With `data=True` a figure gives its tables and draws nothing. Table `a` of the water
# budget holds one row per month and per term, in mm per day over the catchment.
budget = run.figure("water_budget", data=True)["a"]
print(budget.pivot(index="time", columns="variable", values="simulated").round(3).to_string())

# %% The tracks for QGIS

# [[export]] writes the fields, the series and the catchment layers, not the
# tracks yet. They are one GeoDataFrame away, in the CRS of the project.
# One row per position of a particle. Each track runs from the cell it was
# released in, at the start of January, to where it leaves the aquifer.
particles = run.read("particles").sort_values(["particle", "step"])
tracks = particles.groupby("particle")[["x", "y"]].apply(lambda p: LineString(p.to_numpy()))
travel = particles.groupby("particle")["time_days"].max() / 365.25
crs = run.read("watershed").crs
layer = gpd.GeoDataFrame({"travel_years": travel}, geometry=tracks.to_list(), crs=crs)
gpkg = HERE / "summary" / f"{run.name}_particle_tracks.gpkg"
layer.to_file(gpkg, driver="GPKG")
print(gpkg)
