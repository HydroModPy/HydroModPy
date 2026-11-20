"""Play project.toml in the lab, one step at a time, on the Urse catchment. The recharge comes
from a grid that the land surface model PyHELP computed, so the script first looks at that grid
(daily, monthly and yearly totals), then at the mesh on the relief and at the recharge the solver
reads in each cell. It solves, tries three values of K to see how the seepage follows the ratio of
K to the recharge, keeps the model as a run and asks the run for more figures.

    python py1_run_and_plot.py
"""

# %% Setup

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shapely

import hydromodpy as hmp

HERE = Path(__file__).resolve().parent
FIGURES = HERE / "summary" / "figures"
FIGURES.mkdir(parents=True, exist_ok=True)
K_FILE = 3.11338e-6  # the K of project.toml, in m/s
SECONDS_PER_YEAR = 365 * 86400

# %% Open the lab

# A lab holds the model in memory and plays the steps of a run one at a time. Nothing is
# built yet: each row of `lab.steps` is a step with its status.
lab = hmp.Lab(HERE / "project.toml")
print(lab.steps[["step", "status"]].to_string(index=False))

# %% The catchment

# The catchment is the polygon of the file. The DEM is cut to the box around it.
state = lab.advance("build_geographic")
print(state.geographic)

# %% The recharge that PyHELP computed

# `load_data` reads the files of [data]. The recharge is a grid of 40 by 40 cells of 250 m
# with one value per day over 2021-2023, in mm/day. PyHELP is a column model with no lateral
# flow, run here with one rain series, one temperature series and one soil, so every cell of the
# grid holds the same series.
state = lab.advance("load_data")
print(state.data)
grid = state.data.recharge.fields[0].data["recharge"]
daily = grid.mean(["x", "y"]).to_series()
per_cell = grid.mean("time") * 365
print(f"{grid.sizes['x']} x {grid.sizes['y']} cells of 250 m, {grid.sizes['time']} days")
print(f"mean over the three years: {per_cell.mean().item():.1f} mm/year")
print(f"from {per_cell.min().item():.1f} to {per_cell.max().item():.1f} mm/year between the cells")

monthly = daily.resample("MS").sum()
yearly = daily.resample("YS").sum()
print(yearly.round(0).rename(lambda d: d.year).to_string())

# The groundwater model is steady, so it keeps only the mean of this series.
fig, (top, bottom) = plt.subplots(2, 1, figsize=(8, 5), sharex=True)
top.plot(daily.index, daily.to_numpy(), color="navy", lw=0.8)
top.set_ylabel("Recharge (mm/day)")
bottom.bar(monthly.index, monthly.to_numpy(), width=25, color="dodgerblue")
bottom.set_ylabel("Recharge (mm/month)")
for ax in (top, bottom):
    ax.grid(alpha=0.3)
fig.suptitle("Recharge computed by PyHELP over the Urse catchment")
fig.savefig(FIGURES / "pyhelp_recharge.png", dpi=150, bbox_inches="tight")

# %% The mesh on the relief, before the solve

# One cell per pixel of the DEM in the box. `prepare_solver` freezes the model the solver reads,
# and a run stopped there already stores the ground of every cell, so it draws the mesh on the
# relief. The last row and the last column of the box lie outside the DEM. They hold no ground,
# so their cells are not active, and `limits` keeps them out of the colour scale.
state = lab.advance("prepare_solver")
print(state.mesh)
print(state.model)
before = lab.run(until_step="prepare_solver")
print(
    before.figure(
        "topography",
        overlays=["mesh", "outline", "outlet", "network"],
        limits=[1700.0, 3400.0],
        save=FIGURES / "mesh_on_relief.png",
    )
)

# %% The recharge in each cell

# `solve(build_only=True)` writes the MODFLOW 6 model without solving it. Its recharge package
# holds the rate of each cell in m/s, here the mean of the daily grid over the three years.
built = lab.solve(build_only=True)
mf6 = built["flow_main::modflow6"].solver_model
active = np.asarray(mf6.dis.idomain.array).ravel() > 0
rate = np.asarray(mf6.rch.recharge.array).ravel()[active] * SECONDS_PER_YEAR * 1000
print(f"{active.sum()} active cells, recharge from {rate.min():.1f} to {rate.max():.1f} mm/year")

# %% Solve and read the water table

# `lab.read` solves, then reads a variable of the solve: one row per period, one column per
# cell. Nothing is written to runs/ yet. The water table is seepage where it reaches the ground,
# and only the cells of the catchment are counted.
ground = np.asarray(state.model.geometry.column.top).ravel()
centres = state.mesh.cell_centers()
polygon = gpd.read_file(state.model.geometry.catchment.watershed_shp).union_all()
inside = shapely.contains_xy(polygon, centres[:, 0], centres[:, 1])
recharge_ms = float(np.asarray(mf6.rch.recharge.array).ravel()[inside].mean())


def describe(k):
    """Solve with K = k and give the numbers of the catchment."""
    lab.set(K=k)
    head = lab.read("head").to_numpy().ravel()
    return {
        "K/R": k / recharge_ms,
        "K (m/s)": k,
        "water table (m)": np.nanmean(head[inside]),
        "depth (m)": np.nanmean((ground - head)[inside]),
        "seepage (%)": (head[inside] >= ground[inside]).mean() * 100,
        "discharge (m3/day)": float(lab.read("discharge").squeeze()) * 86400,
    }


reference = describe(K_FILE)
print(pd.Series(reference).to_string(float_format="{:.4g}".format))
# The discharge is larger than the recharge over the catchment, which is 13600 m3/day, because the
# aquifer of the box also feeds the catchment from the buffer around it.
print(f"recharge over the catchment: {recharge_ms * 86400 * inside.sum() * 624.853:.0f} m3/day")

# %% Three more values of K

# The mapped network is a few kilometres of stream. The seepage cells that the water table
# sustains are as long or as short as K / recharge says. A K ten times larger than the file's
# carries the water under the ground, and a K ten times smaller lets it come up everywhere.
# `lab.set(K=...)` makes the solver steps stale and `lab.read` solves again, in about five seconds.
rows = [describe(k) for k in (K_FILE / 10, K_FILE * 10)] + [reference]
sweep = pd.DataFrame(rows).sort_values("K/R").set_index("K/R")
print(sweep.to_string(float_format="{:.4g}".format))
lab.set(K=K_FILE)  # back to the file: the lab forgets the change

fig, ax = plt.subplots(figsize=(6, 4))
ax.semilogx(sweep.index, sweep["seepage (%)"], "o-", color="navy", lw=2)
ax.set_xlabel("K / recharge")
ax.set_ylabel("Seepage cells (% of the catchment)")
ax.set_title("The seepage follows K / recharge")
ax.grid(alpha=0.3, which="both")
fig.savefig(FIGURES / "seepage_against_k_over_recharge.png", dpi=150, bbox_inches="tight")

# %% Keep the run

# The run takes the solve of the lab, then draws the figures and writes the files that
# project.toml asks for.
run = lab.run()
lab.close()
print(run.name)
for path in run.figures:
    print(path)

# %% More figures, asked from Python

# `run.figure` takes the keys of a [[display.figure]] table and draws from the sealed run, so
# nothing is solved again. The depth of the water table with the mapped streams over it, then
# the water table from south to north along the catchment.
print(
    run.figure(
        "watertable_depth",
        overlays=["outline", "network", "seepage"],
        limits=[0.0, 60.0],
        save=FIGURES / "watertable_depth_and_network.png",
    )
)
print(
    run.figure(
        "watertable_elevation",
        type="section",
        line=[[2797000.0, 1132000.0], [2797000.0, 1136600.0]],
        save=FIGURES / "section_south_north.png",
    )
)

# %% The files for QGIS

for path in run.exports:
    print(path)
