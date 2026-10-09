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
from hydromodpy.display import names

HERE = Path(__file__).resolve().parent

# %% The catalog

# The index of the project, .hmp/index.duckdb, opened read-only: the script
# does not modify it.
cat = hmp.open(HERE)

# One row per run. The runs that an if_exists = "replace" replaced are in the
# trash, with the status "trashed".
frame = cat.frame
done = frame[frame["status"] == "completed"]
print(done[["name", "flow_regime", "n_timesteps", "duration_s"]].to_string(index=False))

# The scores against the discharge of the gauge, for every transient run. Take
# care when you compare them: the daily runs have neither the same period nor
# the same step as the monthly runs.
transient = cat.find(status="completed", flow_regime="transient")
scores = pd.DataFrame(
    {
        metric: transient.compare(metric, station="NANCON").set_index("name")["value"]
        for metric in ["nse", "nse_log", "kge"]
    }
)
print(scores.sort_values("nse", ascending=False).round(3))

# %% One run

# The latest run of project.toml. find returns the live runs of that name,
# from the most recent to the oldest, and leaves the trash out.
run = cat.find(name_stem="nancon_intermittence_mf6")[0]
print(run.name, run.params)

# The figures of the catalog can also be drawn from Python, with the same
# options as [display.overrides]. names() lists them all.
print(len(names()), "figures:", ", ".join(names()))

# The seepage map of the wettest and of the driest month, over the whole mesh
# instead of the catchment alone.
figures = HERE / "runs" / run.name / "figures"
for date in ["2001-01-15", "2002-10-15"]:
    fig = hmp.figure(run, "seepage_map", time=date, extent="mesh")
    fig.savefig(figures / f"seepage_map_{date[:7]}.png", dpi=150)
    plt.close(fig)

# A rendered figure is a matplotlib figure like any other: you can edit it
# before you save it.
fig = hmp.figure(run, "hydrograph_sim_obs", log_y=True)
ax = fig.axes[0]
ax.axvspan(pd.Timestamp("2000-01-01"), pd.Timestamp("2001-01-01"), color="0.9", zorder=0)
ax.text(pd.Timestamp("2000-02-01"), 0.95, "spin-up", transform=ax.get_xaxis_transform())
fig.savefig(figures / "hydrograph_spinup.png", dpi=150)
plt.close(fig)

# %% An export on demand

# The states of January 2001, as GeoTIFF, written in share/<run>/ next to the
# ones the TOML already asks for.
for path in hmp.export(run, ["watertable_depth", "seepage_mask"], time="2001-01-15"):
    print(path)
