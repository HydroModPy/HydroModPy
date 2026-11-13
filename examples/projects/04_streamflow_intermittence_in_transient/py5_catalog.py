"""Read the runs already computed in the project, without running anything, to
get what the TOML files did not ask for.

At least one run of project.toml is needed:

    hmp run project.toml
    python py5_catalog.py
"""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

import hydromodpy as hmp
from hydromodpy.display.figure_registry import names

HERE = Path(__file__).resolve().parent

# %% The project

# The project as it is on disk, opened read-only: the script changes nothing.
proj = hmp.open(HERE)

# One row per case of the project, with its status and its label of the day.
# A run deleted with hmp catalog delete is in the trash of the project, not here.
print(proj.cases.to_string(index=False))

# The scores of every run of the site, read from their seals. Each run scores the
# gauge in the window of its own metric rule, and the table says which. Take care
# when you compare them: the daily runs have neither the same window nor the same
# step as the monthly runs.
scores = proj.runs(site="nancon").metrics
columns = ["sim_id", "station", "window_start", "window_end", "nse", "nse_log", "kge"]
print(scores.filter(items=columns).sort_values("nse", ascending=False).round(3))

# %% One run

# The run of project.toml. An edited project.toml writes nancon_intermittence_mf6.v2,
# .v3...: name the version to read it.
run = proj["nancon_intermittence_mf6"]
print(run.name, run.parameters["value"].to_dict())

# The figures of the catalog can also be drawn from Python, with the same
# fields as a [[display.figure]] table. names() lists them all.
print(len(names()), "figures:", ", ".join(names()))

# A figure a script draws is derived, not sealed: it goes to summary/figures/,
# never into the run. The seepage map of the wettest and of the driest month.
figures = HERE / "summary" / "figures" / run.name
figures.mkdir(parents=True, exist_ok=True)
for date in ["2001-01-15", "2002-10-15"]:
    fig = run.figure("seepage_mask", time=date)
    fig.savefig(figures / f"seepage_map_{date[:7]}.png", dpi=150)
    plt.close(fig)

# A rendered figure is a matplotlib figure like any other: you can edit it
# before you save it.
fig = run.figure("hydrograph", scale="log")
ax = fig.axes[0]
ax.axvspan(pd.Timestamp("2000-01-01"), pd.Timestamp("2001-01-01"), color="0.9", zorder=0)
ax.text(pd.Timestamp("2000-02-01"), 0.95, "spin-up", transform=ax.get_xaxis_transform())
fig.savefig(figures / "hydrograph_spinup.png", dpi=150)
plt.close(fig)

# %% An export on demand

# The states of January 2001, as GeoTIFF, written in runs/<run>/exports/ next to
# the ones the TOML already asks for, and listed in its exports/index.json.
for path in hmp.export(run, ["watertable_depth", "seepage_mask"], time="2001-01-15"):
    print(path)
