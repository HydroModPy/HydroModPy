"""Example 04 driven from Python: what specific yield does to intermittence.

``project.toml`` runs one Sy. The legacy example ran three, two decades apart,
because Sy is what decides whether a catchment remembers its winter: a tight
aquifer empties before summer and its network dries back to the main valley, a
loose one carries water through and keeps the heads flowing.

Each Sy is one simulation obtained with a single parameter override. The two
figures built here are the ones only a script can give, each putting the whole
sweep in a single frame:

- ``sweep_seepage.png``    the share of the catchment that seeps, month by month
- ``sweep_hydrograph.png`` the three hydrographs against the gauge

Run it as a plain script, or cell by cell (the ``#%%`` markers) in an IDE::

    python examples/projects/04_streamflow_intermittence_in_transient/run_manual.py
"""

# %% ---- IMPORTS AND PATHS

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

import hydromodpy as hmp

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "project.toml"

# 0.1%, 5% and 30%: a fissured bedrock, a normal weathered mantle, and a store
# so loose it barely drains. The legacy example's three values.
SY_VALUES = [0.001, 0.05, 0.3]
COLORS = ["#b3202c", "#d2762a", "#1f6fb4"]


# %% ---- ONE SIMULATION PER SPECIFIC YIELD

# Project is setup-once, run-many: delineation, data loading and meshing happen
# on the first simulate() and are reused by every following one.
project = hmp.Project(CONFIG, no_display=True)

runs = {}
for sy in SY_VALUES:
    runs[sy] = project.simulate(name=f"nancon_Sy_{sy:g}", Sy=sy)
    print(f"Sy = {sy:<6g} -> {runs[sy].name} [{runs[sy].sim_id[:8]}]")

sample = runs[SY_VALUES[0]]
index = sample.time_index
print(f"\n{sample.n_timesteps} monthly periods, {index[0]:%Y-%m} -> {index[-1]:%Y-%m}")


# %% ---- HOW MUCH OF THE CATCHMENT SEEPS, MONTH BY MONTH

# The seepage mask is the wet network: the cells where the water table reaches
# the surface. Its swing through the year is the intermittence.
# The mask comes as the (nrow, ncol) grid, the field as one value per cell.
active = np.asarray(sample.catchment_mask, dtype=bool).ravel()
n_active = int(active.sum())

seepage = {}
for sy, run in runs.items():
    share = [
        100.0
        * float((np.nan_to_num(run.field("seepage_mask", timestep=t))[active] > 0).sum())
        / n_active
        for t in range(int(run.n_timesteps or 0))
    ]
    seepage[sy] = np.asarray(share)
    print(f"Sy = {sy:<6g} seepage {share and min(share):.1f}% to {share and max(share):.1f}%")

# The project holds the catalog open; hmp.open() here would be a second
# connection to the same file and DuckDB refuses it.
OUT = project.store.run_dir_for(sample.sim_id) / "figures" / "from_python"
OUT.mkdir(parents=True, exist_ok=True)


# %% ---- FIGURE 1: THE SEEPAGE NETWORK THROUGH THE SWEEP

fig, ax = plt.subplots(1, 1, figsize=(9, 4), dpi=150)
for (sy, share), color in zip(seepage.items(), COLORS, strict=True):
    ax.fill_between(index, 0, share, color=color, alpha=0.25)
    ax.plot(index, share, color=color, lw=1.6, label=f"Sy = {sy:g}")
ax.set_xlabel("Date")
ax.set_ylabel("Catchment cells that seep (%)")
ax.set_title("How far the wet network retreats each summer, against specific yield")
ax.grid(True, ls=":", lw=0.4)
ax.legend(fontsize=8)
fig.tight_layout()
fig.savefig(OUT / "sweep_seepage.png", bbox_inches="tight")


# %% ---- FIGURE 2: THE HYDROGRAPHS AGAINST THE GAUGE

fig, ax = plt.subplots(1, 1, figsize=(9, 4), dpi=150)
for (sy, run), color in zip(runs.items(), COLORS, strict=True):
    discharge = run.timeseries("discharge", station="_catchment")
    ax.plot(discharge.index, discharge.to_numpy(), color=color, lw=1.4, label=f"Sy = {sy:g}")

observed = sample.observed("discharge")
for station_id, group in observed.groupby("station_id"):
    ax.plot(
        group["datetime"],
        group["value"],
        color="black",
        lw=1.0,
        ls="--",
        label=f"observed ({station_id})",
    )
ax.set_yscale("log")
ax.set_xlabel("Date")
ax.set_ylabel("Discharge (m³/s)")
ax.set_title("Baseflow recession against specific yield")
ax.grid(True, which="both", ls=":", lw=0.4)
ax.legend(fontsize=8)
fig.tight_layout()
fig.savefig(OUT / "sweep_hydrograph.png", bbox_inches="tight")

print(f"\nsweep figures written under {OUT}")


# %% ---- CLOSE THE PROJECT

project.close()
