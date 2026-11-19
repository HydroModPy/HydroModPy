"""Play project.toml in the lab, one step at a time, and look at what each step built: the
catchment, the DEM, the mesh on the relief, the ten layers and the K the solver will read in
each. Then solve, keep the model as a run, and draw from the run the water table, the
seepage and the particles. The travel times of the particles are then counted in a small plot
of their own.

    python py1_run_and_plot.py
"""

# %% Setup

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import hydromodpy as hmp

HERE = Path(__file__).resolve().parent
FIGURES = HERE / "summary" / "figures"
FIGURES.mkdir(parents=True, exist_ok=True)

# %% Open the lab

# A lab holds the model in memory and plays the steps of a run one at a time. Nothing is
# built yet: each row of `lab.steps` is a step with its status.
lab = hmp.Lab(HERE / "project.toml")
print(lab.steps[["step", "status"]].to_string(index=False))

# %% The catchment

# `advance` plays every missing step up to the one named. The catchment is cut out of the
# regional DEM from the outlet, which moves onto the flow network when it lies off it.
# The box around the catchment is the domain of the model.
state = lab.advance("build_geographic")
print(state.geographic)

# %% The DEM

# `load_data` reads the files of [data]. The DEM of the box is a table of heights at 75 m.
state = lab.advance("load_data")
print(state.data)

# %% The mesh

# One cell per pixel of the DEM in the box. The mesh says its cells, its area and its extent.
state = lab.advance("build_mesh")
print(state.mesh)

# %% The mesh on the relief, before the solve

# `prepare_solver` freezes the model the solver reads. A run stopped there already stores the
# ground of every cell, so it draws the mesh on the relief. It has no seal yet.
state = lab.advance("prepare_solver")
print(state.model)
before = lab.run(until_step="prepare_solver")
print(
    before.figure(
        "topography",
        overlays=["mesh", "outline", "outlet"],
        save=FIGURES / "mesh_on_relief.png",
    )
)

# %% The ten layers and their K

# `solve(build_only=True)` writes the MODFLOW 6 model without solving it. Its packages hold
# what the solver will read: one row per layer and one column per cell. The base is flat at
# 1000 m, so the aquifer is 120 m thick under the valleys and more than 1300 m under the
# crests, and each layer is 1.5 times thicker than the one above it. K falls as
# exp(-depth / 50 m), taken at the middle of each layer. Each value is the mean over the cells
# of the box.
built = lab.solve(build_only=True)
mf6 = built["flow_main::modflow6"].solver_model
ground = np.asarray(state.model.geometry.column.top).ravel()
bases = mf6.dis.botm.array
tops = np.vstack([ground, bases[:-1]])
layers = pd.DataFrame(
    {
        "thickness (m)": (tops - bases).mean(axis=1),
        "middle depth (m)": (ground - (tops + bases) / 2).mean(axis=1),
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
print(f"water table from {head.min():.1f} to {head.max():.1f} m, mean depth {(ground - head).mean():.1f} m")
print(f"seepage in {seep.mean() * 100:.1f} % of the cells of the box")
print(f"discharge at the outlet: {float(lab.read('discharge').squeeze()) * 86400:.0f} m3/day")

# %% Keep the run

# The run takes the solve of the lab, tracks the particles, then draws the figures and writes
# the files that project.toml asks for.
run = lab.run()
lab.close()
print(run.name)
for path in run.figures:
    print(path)

# %% Two more figures, asked from Python

# `run.figure` takes the keys of a [[display.figure]] table and draws from the sealed run, so
# nothing is solved again. The pathlines over the water-table depth, then the water table
# from east to west through the outlet.
print(
    run.figure(
        "watertable_depth",
        overlays=["outline", "seepage", "pathlines"],
        limits=[0.0, 100.0],
        save=FIGURES / "watertable_depth_and_pathlines.png",
    )
)
print(
    run.figure(
        "watertable_elevation",
        type="section",
        line=[[598500.0, 6193904.0], [602200.0, 6193904.0]],
        save=FIGURES / "section_west_east.png",
    )
)

# %% The travel times

# The [[export]] blocks of project.toml wrote these files when the run was sealed. The
# particle tracks are one line per particle, with its travel time in years from its cell to
# where it leaves the aquifer.
for path in run.exports:
    print(path)
tracks = gpd.read_file(next(path for path in run.exports if path.name == "pathlines.gpkg"))
years = np.sort(tracks["travel_yr"].to_numpy())
print(
    f"{len(years)} particles, median travel time {np.median(years):.1f} years, "
    f"mean {years.mean():.1f} years, 90 % leave within {np.quantile(years, 0.9):.0f} years"
)

# The share of the particles that are still in the aquifer after a time t, on two log axes.
# The long tail belongs to the water that goes deep under the crests.
share = 1.0 - np.arange(1, len(years) + 1) / len(years) + 1.0 / len(years)
fig, ax = plt.subplots(figsize=(6, 4))
ax.loglog(years, share, color="navy", lw=2)
ax.set_xlabel("Travel time (years)")
ax.set_ylabel("Share of particles still in the aquifer")
ax.set_title("Residence times, Lasset")
ax.grid(alpha=0.3, which="both")
fig.savefig(FIGURES / "residence_times_loglog.png", dpi=150, bbox_inches="tight")
