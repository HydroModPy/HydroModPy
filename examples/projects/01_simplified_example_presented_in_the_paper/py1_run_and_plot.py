"""Play project.toml in the lab, one step at a time, and look at what each step built: the
catchment, the gauge and its discharge, the mesh on the relief, the five layers and the K the
solver will read in each. Then solve, keep the model as a run, and draw from the run the
water table, the seepage and the particles.

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
# regional DEM from the outlet, and its box is the domain of the model.
state = lab.advance("build_geographic")
print(state.geographic)
area_km2 = state.geographic.catch_area

# %% The gauge of the Canut

# `load_data` reads the files of [data]. The gauge is a table of daily discharge in m3/s.
state = lab.advance("load_data")
print(state.data)
gauge = state.data.hydrometry.points[0]
discharge = gauge.data.set_index("datetime")["value"]
discharge = discharge["1990":"2019"] / (area_km2 * 1e6) * 86400 * 1000
print(f"{gauge.location.metadata['name']}: mean {discharge.mean():.2f} mm/day over 1990-2019")

# The regime of the river: the median of each day of the year over 30 years, the band
# where 80 % of the years fall, and the year 2017.
day = discharge.index.dayofyear
regime = discharge.groupby(day).quantile([0.1, 0.5, 0.9]).unstack()
year = discharge["2017"]
fig, ax = plt.subplots(figsize=(6, 4))
ax.fill_between(regime.index, regime[0.1], regime[0.9], color="skyblue", label="10 to 90 %")
ax.plot(regime.index, regime[0.5], color="darkred", lw=2, label="median")
ax.plot(year.index.dayofyear, year, color="blue", lw=1, label="2017")
ax.set_yscale("log")
ax.set_ylim(0.01, 10)
ax.set_xlim(1, 366)
ax.set_xticks(np.linspace(1, 366, 13), list("JFMAMJJASONDJ"))
ax.set_ylabel("Q / A (mm/day)")
ax.set_title("The Canut, 1990 to 2019")
ax.legend(loc="lower left")
fig.savefig(FIGURES / "discharge_regime.png", dpi=150, bbox_inches="tight")

# %% The mesh

# One cell per pixel of the DEM in the box. The mesh says its cells, its area and its extent.
state = lab.advance("build_mesh")
print(state.mesh)

# %% The mesh on the relief, before the solve

# `prepare_solver` freezes the model the solver reads. A run stopped there already stores the
# ground of every cell, so it draws the mesh on the relief, with the mapped streams and the
# gauge. It has no seal yet.
state = lab.advance("prepare_solver")
print(state.model)
before = lab.run(until_step="prepare_solver")
print(
    before.figure(
        "topography",
        overlays=["mesh", "outline", "network", "outlet", "stations"],
        save=FIGURES / "mesh_on_relief.png",
    )
)

# %% The five layers and their K

# `solve(build_only=True)` writes the MODFLOW 6 model without solving it. Its packages hold
# what the solver will read: one row per layer and one column per cell. K and Sy follow
# exp(-depth / 20 m), taken at the middle of each layer.
built = lab.solve(build_only=True)
mf6 = built["flow_main::modflow6"].solver_model
ground = mf6.dis.top.array
bases = mf6.dis.botm.array
tops = np.vstack([ground, bases[:-1]])
layers = pd.DataFrame(
    {
        "thickness (m)": (tops - bases).mean(axis=1),
        "middle depth (m)": (ground - (tops + bases) / 2).mean(axis=1),
        "K (m/s)": mf6.npf.k.array.mean(axis=1),
        "Sy": mf6.sto.sy.array.mean(axis=1),
    },
    index=pd.RangeIndex(1, len(bases) + 1, name="layer"),
)
print(layers.to_string(float_format="{:.3g}".format))

# %% Solve and read the water table

# `lab.read` solves, then reads a variable of the solve: one row per period, one column per
# cell. Nothing is written to runs/ yet.
head = lab.read("head")
print(f"water table from {float(head.min()):.1f} to {float(head.max()):.1f} m")
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
# nothing is solved again. K from north to south, then the drain flow with the seepage cells.
print(
    run.figure(
        "hydraulic_conductivity",
        type="section",
        line=[[323775.0, 6779400.0], [323775.0, 6773850.0]],
        scale="log",
        save=FIGURES / "conductivity_north_south.png",
    )
)
print(
    run.figure(
        "watertable_depth",
        overlays=["outline", "network", "pathlines"],
        limits=[0.0, 10.0],
        save=FIGURES / "watertable_depth_and_pathlines.png",
    )
)

# %% The files for QGIS

# The [[export]] blocks of project.toml wrote these files when the run was sealed.
for path in run.exports:
    print(path)
# The particle tracks are one line per particle, with its travel time in years from its
# cell to where it leaves the aquifer. Half of the water seeps out within this time.
tracks = gpd.read_file(next(path for path in run.exports if path.name == "pathlines.gpkg"))
print(f"{len(tracks)} particles, median travel time {tracks['travel_yr'].median():.2f} years")
