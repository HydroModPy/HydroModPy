"""Sweep the hydraulic conductivity K of project.toml: one run per value.

The catchment, the data and the mesh are prepared by the first run and reused by
the others, which change K only. Count about a minute per run.

Run it from the project folder:

    python sweep_k.py
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import hydromodpy as hmp
from hydromodpy.config import HydroModPyConfig

HERE = Path.cwd()

# m/s. project.toml takes 5e-5.
K_VALUES = [1e-5, 2e-5, 5e-5, 1e-4, 2e-4]

# %% The runs

# No figures and no exports per run: the figure of the sweep is enough.
cfg = HydroModPyConfig.from_toml(HERE / "project.toml")
cfg.export = []

sim_ids = []
with hmp.Project(cfg, no_display=True) as project:
    for k in K_VALUES:
        sim_ids.append(project.simulate(name=f"sweep_k_{k:.0e}", K=k).sim_id)

# The Project closes its catalog when the block ends: read the runs back from the
# catalog of the project.
cat = hmp.open(HERE)
runs = [cat[sim_id] for sim_id in sim_ids]

# %% What each run gives

months = runs[0].periods.edges[:-1]
in_catchment = runs[0].catchment_mask.ravel()
cell_km2 = runs[0].grid.cell_size ** 2 / 1e6

areas = {}
rows = []
for run in runs:
    seepage = hmp.read(run, "seepage_mask").to_numpy() > 0
    area = (seepage & in_catchment).sum(axis=1) * cell_km2
    areas[run.params["K"]] = area
    scores = run.metrics.query("station_id == 'NANCON'").set_index("metric_name")["value"]
    rows.append(
        {
            "K": run.params["K"],
            "mean seepage area (km2)": area.mean(),
            "min seepage area (km2)": area.min(),
            "NSE": scores["nse"],
            "log NSE": scores["log_nse"],
        }
    )
table = pd.DataFrame(rows).set_index("K")
print(table.round(3))

# %% The figure

fig, (ax1, ax2) = plt.subplots(
    1, 2, figsize=(12, 4.5), width_ratios=[1.8, 1], constrained_layout=True
)
colors = plt.get_cmap("viridis")(np.linspace(0, 0.9, len(runs)))
for (k, area), color in zip(areas.items(), colors, strict=True):
    ax1.plot(months, area, color=color, label=f"K = {k:.0e} m/s")
ax1.set_yscale("log")
ax1.set_ylabel("seepage area (km2)")
ax1.legend(fontsize="small")

ax2.plot(table.index, table["NSE"], "o-", color="k", label="NSE")
ax2.plot(table.index, table["log NSE"], "s--", color="0.5", label="NSE on log Q")
ax2.set_xscale("log")
ax2.set_xlabel("K (m/s)")
ax2.set_ylabel("score of the flow at the gauge")
ax2.legend()

out = HERE / "share" / "figures" / "sweep_k.png"
out.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(out, dpi=150)
print(out)
