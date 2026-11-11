"""Run step4_transient.toml from Python, then draw a figure HydroModPy does
not offer: the area of the catchment where the water table reaches the
surface, month by month, against the discharge at the outlet.

    python py1_run_and_plot.py
"""

from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import hydromodpy as hmp

HERE = Path(__file__).resolve().parent

# %% The run

# The same as `hmp run step4_transient.toml`, figures and exports included.
# An unchanged file is not computed again: the run of the last execution comes
# back. An edited file writes a new run, nancon_step4_transient.v2, .v3...
run = hmp.run(HERE / "step4_transient.toml").open()
print(run.name)

# %% The data

# The fields are stored by stress period, without a date. Period i runs from
# edges[i] to edges[i + 1]: each month is named by its first day.
months = run.periods.edges[:-1]

# Simulated discharge, the mean of the month, and gauged discharge, daily,
# averaged over the same months. Both in m3/s.
q_sim = pd.Series(run.read("discharge").to_numpy(), index=months)
q_obs = run.read("discharge_obs").resample("MS").mean().reindex(months)

# The mesh covers the rectangle around the catchment: count the cells of the
# catchment only. The mesh is the DEM grid, row by row, hence the ravel of the
# mask.
seepage = run.read("seepage_mask").to_numpy() > 0  # (months, cells)
in_catchment = run.catchment_mask.ravel()
cell_km2 = run.grid.cell_size**2 / 1e6
area = pd.Series((seepage & in_catchment).sum(axis=1) * cell_km2, index=months)

# Seepage area as a power law of the discharge, A = a Q^b, as Godsey and
# Kirchner (2014) write the length of the active network. The year 2000 is the
# spin-up of the model: it is left out.
kept = months.year >= 2001
b, log_a = np.polyfit(np.log(q_sim[kept]), np.log(area[kept]), 1)
print(f"exponent b = {b:.2f}")

# %% The figure

fig, axes = plt.subplot_mosaic(
    [["q", "fit"], ["area", "fit"]],
    figsize=(12, 6),
    width_ratios=[1.7, 1],
    constrained_layout=True,
)

ax = axes["q"]
ax.plot(months, q_obs, color="k", lw=1, label="gauged")
ax.plot(months, q_sim, color="tab:blue", label="simulated")
ax.set_yscale("log")
ax.set_yticks([0.3, 0.5, 1, 2], ["0.3", "0.5", "1", "2"])
ax.minorticks_off()
ax.set_ylabel("discharge (m³/s)")
ax.tick_params(labelbottom=False)
ax.legend()

ax = axes["area"]
ax.fill_between(months, area, color="tab:orange", alpha=0.5)
ax.set_ylabel("seepage area (km²)")
ax.sharex(axes["q"])
ax.xaxis.set_major_locator(mdates.YearLocator())

ax = axes["fit"]
points = ax.scatter(q_sim[kept], area[kept], c=months[kept].month, cmap="twilight", vmin=1, vmax=12)
q = np.geomspace(q_sim[kept].min(), q_sim[kept].max(), 50)
ax.plot(q, np.exp(log_a) * q**b, color="k", lw=1, label=rf"$A \propto Q^{{{b:.2f}}}$")
ax.set_xscale("log")
ax.set_yscale("log")
ax.set_xticks([0.3, 0.5, 1, 2], ["0.3", "0.5", "1", "2"])
ax.set_yticks([1, 2, 3, 4], ["1", "2", "3", "4"])
ax.minorticks_off()
ax.set_xlabel("simulated discharge (m³/s)")
ax.set_ylabel("seepage area (km²)")
ax.set_title("2001-2002")
ax.legend()
fig.colorbar(points, ax=ax, label="month", ticks=[1, 4, 7, 10])

fig.suptitle(f"{run.name}: water table at the surface and discharge")

# A figure a script draws from a run is derived, not sealed: it goes to
# summary/figures/, never into the run, whose figures/ holds the [display] list.
out = HERE / "summary" / "figures" / f"{run.name}_seepage_vs_discharge.png"
out.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(out, dpi=150)
print(out)
plt.show()
