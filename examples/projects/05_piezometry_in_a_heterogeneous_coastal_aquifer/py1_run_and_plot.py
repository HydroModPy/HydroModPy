"""Play project.toml in the lab, one step at a time, and look at what each step built: the
recharge, the sea level and the piezometer record, the mesh on the relief, then the sea cells,
the drains and the two zones of K and Sy the solver will read. Then solve, keep the model as a
run, put the simulated head at the piezometer next to the measured one, and ask the run for two
more figures.

    python py1_run_and_plot.py
"""

# %% Setup

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import hydromodpy as hmp

HERE = Path(__file__).resolve().parent
FIGURES = HERE / "summary" / "figures"
FIGURES.mkdir(parents=True, exist_ok=True)
SEA_LEVEL = HERE / "../../data/oceanic/oceanic_custom_GOUVILLE_20160101_20161231_D.csv"
PIEZOMETER = (363780.7, 6897112.7)

# %% Open the lab

# A lab holds the model in memory and plays the steps of a run one at a time. Nothing is
# built yet: each row of `lab.steps` is a step with its status.
lab = hmp.Lab(HERE / "project.toml")
print(lab.steps[["step", "status"]].to_string(index=False))

# %% The data

# `load_data` reads the files of [data]: the DEM, the two zones, the daily recharge and the
# daily record of the piezometer. The sea level is the file the ocean boundary reads.
state = lab.advance("load_data")
print(state.data)
recharge = state.data.recharge.points[0].data.set_index("datetime")["value"]
measured = state.data.piezometry.points[0].data.set_index("datetime")["value"]
sea = pd.read_csv(SEA_LEVEL, parse_dates=["datetime"]).set_index("datetime")["value"]
print(f"recharge: {recharge.sum():.0f} mm over 2016, mean {recharge.mean():.2f} mm/day")
print(f"sea level: {sea.min():.2f} to {sea.max():.2f} m, mean {sea.mean():.3f} m")
print(f"piezometer: {measured.min():.2f} to {measured.max():.2f} m")

fig, axes = plt.subplots(3, 1, figsize=(8, 7), sharex=True)
axes[0].bar(recharge.index, recharge, width=1.0, color="dodgerblue")
axes[0].set_ylabel("Recharge (mm/day)")
axes[1].plot(sea.index, sea, color="navy", lw=1)
axes[1].axhline(sea.mean(), color="navy", ls="--", lw=1, label="mean, used on 1 January")
axes[1].set_ylabel("Sea level (m)")
axes[1].legend(loc="upper right")
axes[2].plot(measured.index, measured, color="k", lw=1.5)
axes[2].set_ylabel("Piezometer (m)")
axes[0].set_title("What drives the water table of Gouville in 2016, and what it does")
fig.savefig(FIGURES / "forcings_2016.png", dpi=150, bbox_inches="tight")

# %% The mesh on the relief, before the solve

# One cell per pixel of the 25 m DEM. `prepare_solver` freezes the model the solver reads. A
# run stopped there already stores the ground of every cell, so it draws the mesh on the
# relief, with the piezometer. It has no seal yet.
state = lab.advance("prepare_solver")
print(state.mesh)
print(state.model)
before = lab.run(until_step="prepare_solver")
print(
    before.figure("topography", overlays=["mesh", "stations"], save=FIGURES / "mesh_on_relief.png")
)

# %% What the solver will read

# `solve(build_only=True)` writes the MODFLOW 6 model without solving it. Its packages hold
# what the solver will read. The sea cells are those whose ground is at or below the highest
# sea level of the year, and every other cell drains at the ground.
built = lab.solve(build_only=True)
gwf = built["flow_main::modflow6"].solver_model.gwf
sea_cells = gwf.get_package("chd").stress_period_data.get_data()
drains = gwf.get_package("drn").stress_period_data.get_data()
print(f"{len(sea_cells[0])} sea cells and {len(drains[0])} drain cells")
print(f"sea level on 1 January {sea_cells[0][0][1]:.3f} m, on 2 January {sea_cells[1][0][1]:.3f} m")
k_per_day = gwf.npf.k.array.ravel() * 86400
sy = gwf.sto.sy.array.ravel()
west = k_per_day < 50
print(
    f"west: {west.sum()} cells, K {np.median(k_per_day[west]):.1f} m/day, Sy {np.median(sy[west]):.2f}"
)
print(
    f"east: {(~west).sum()} cells, K {np.median(k_per_day[~west]):.1f} m/day, Sy {np.median(sy[~west]):.2f}"
)

# %% Solve and read the water table

# `lab.read` solves, then reads a variable of the solve: one row per period and one column per
# cell. The steady 1 January comes first. A cell seeps when its head reaches the ground.
head = lab.read("head")
ground = lab.state.model.geometry.column.top
first = np.asarray(head.isel(time=0)).ravel()
print(f"mean head on 1 January: {first.mean():.2f} m")
print(f"cells at or above the ground on 1 January: {100 * np.mean(first >= ground):.1f} %")

# %% Keep the run

# The run takes the solve of the lab, then draws the figures and writes the files that
# project.toml asks for.
run = lab.run()
lab.close()
print(run.name)
for path in run.figures:
    print(path)

# %% The piezometer, simulated and measured

# [observation] keeps the head of the piezometer cell at every time step, under the station
# obs:GOUVILLE_F4. A time step is stamped at its end, so the head of 1 January is read on
# 2 January. The depth is the ground of that cell minus the head.
simulated = run.timeseries("head", station="obs:GOUVILLE_F4")
simulated.index = simulated.index - pd.Timedelta(days=1)
centres = run.mesh.cell_centers()
cell = int(np.argmin(np.hypot(centres[:, 0] - PIEZOMETER[0], centres[:, 1] - PIEZOMETER[1])))
cell_ground = float(np.asarray(run.read("topography")).ravel()[cell])
pair = pd.DataFrame({"measured": measured, "simulated": simulated}).dropna()
gap = pair["simulated"] - pair["measured"]
print(f"ground of the piezometer cell: {cell_ground:.2f} m")
print(f"mean gap {gap.mean():+.2f} m, RMSE {np.sqrt((gap**2).mean()):.2f} m")
print(f"correlation {pair.corr().iloc[0, 1]:.2f} over {len(pair)} days")

fig, axes = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
axes[0].plot(pair.index, pair["measured"], color="k", lw=2, label="Measured")
axes[0].plot(pair.index, pair["simulated"], color="red", lw=2, label="Simulated")
axes[0].set_ylabel("Elevation (m)")
axes[0].set_title("Piezometer BSS 01423X0044/F4")
axes[0].legend(loc="upper right")
axes[1].plot(pair.index, cell_ground - pair["measured"], color="k", lw=2, label="Measured")
axes[1].plot(pair.index, cell_ground - pair["simulated"], color="red", lw=2, label="Simulated")
axes[1].set_ylabel("Depth under the ground (m)")
axes[1].invert_yaxis()
axes[1].legend(loc="upper right")
fig.savefig(FIGURES / "piezometer_measured_and_simulated.png", dpi=150, bbox_inches="tight")

# %% Two more figures, asked from Python

# `run.figure` takes the keys of a [[display.figure]] table and draws from the sealed run, so
# nothing is solved again. The seepage cells at the high of the piezometer, then the head
# along the strip in mid January, when the winter recharge starts to lift it.
print(
    run.figure(
        "seepage_mask",
        time="2016-03-15",
        overlays=["stations"],
        save=FIGURES / "seepage_march.png",
    )
)
print(
    run.figure(
        "watertable_elevation",
        type="section",
        line=[[363010.0, 6897112.7], [366330.0, 6897112.7]],
        time="2016-01-15",
        save=FIGURES / "section_west_east_january.png",
    )
)

# %% The numbers behind a figure

# With `data=True` a figure gives its tables and draws nothing. Table `a` of the water budget
# holds one row per day and per term, in mm per day over the strip. The sea takes back what
# the recharge brings.
budget = run.figure("water_budget", station="zone:domain", data=True)["a"]
print(budget.groupby("variable")["simulated"].mean().round(3).to_string())

# %% The files for QGIS

# The [[export]] blocks of project.toml wrote these files when the run was sealed.
for path in run.exports:
    print(path)
