"""Sweep K from project.toml: one run per value, then one figure that puts
them all together.

Each run is project.toml with K set on top, as `hmp run project.toml --set
flow.param.K.field.value=2e-5` does on the command line, so its manifest
records the override. The catchment, the data and the mesh come from the
caches the first run fills. Count one minute per run.

    python py4_sweep_k.py
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import hydromodpy as hmp
from hydromodpy.config import HydroModPyConfig

HERE = Path(__file__).resolve().parent

# m/s. project.toml takes 5e-5.
K_VALUES = [1e-5, 2e-5, 5e-5, 1e-4, 2e-4]

# %% The runs

# One run per K, named after its index, without the figures and the exports:
# the figure of the sweep is enough.
cfg = HydroModPyConfig.from_toml(HERE / "project.toml")
cfg.export = []
runs = [
    hmp.run(cfg, name=f"nancon_k{i}", set={"K": k}, no_display=True).open()
    for i, k in enumerate(K_VALUES)
]

# %% What each run gives

months = runs[0].periods.edges[:-1]
in_catchment = runs[0].catchment_mask.ravel()
cell_km2 = runs[0].grid.cell_size ** 2 / 1e6

areas = {}
rows = []
for run in runs:
    seepage = run.read("seepage_mask").to_numpy() > 0
    area = (seepage & in_catchment).sum(axis=1) * cell_km2
    areas[run.parameters.loc["K", "value"]] = area
    # Scored at the gauge of [site], in the window of [metrics].
    scores = run.metrics.set_index("metric")["value"]
    rows.append(
        {
            "K": run.parameters.loc["K", "value"],
            "mean area (km²)": area.mean(),
            "min area (km²)": area.min(),
            "NSE": scores["nse"],
            "log NSE": scores["nse_log"],
        }
    )
table = pd.DataFrame(rows).set_index("K")
print(table.round(3))

# The NSE barely moves from one K to the next while the seepage area varies by
# a factor of ten: the discharge at the gauge does not constrain K, the
# network does. This is why run_calibration.toml calibrates K on the mapped
# network.

# %% The figure

fig, (ax1, ax2) = plt.subplots(
    1, 2, figsize=(12, 4.5), width_ratios=[1.8, 1], constrained_layout=True
)
colors = plt.get_cmap("viridis")(np.linspace(0, 0.9, len(runs)))
for (k, area), color in zip(areas.items(), colors, strict=True):
    ax1.plot(months, area, color=color, label=f"K = {k:.0e} m/s")
ax1.set_yscale("log")
ax1.set_yticks([0.3, 1, 3, 10], ["0.3", "1", "3", "10"])
ax1.minorticks_off()
ax1.set_ylabel("seepage area (km²)")
ax1.legend(fontsize="small")

ax2.plot(table.index, table["NSE"], "o-", color="k", label="NSE")
ax2.plot(table.index, table["log NSE"], "s--", color="0.5", label="NSE on log Q")
ax2.set_xscale("log")
ax2.set_xticks(K_VALUES, [f"{k:.0e}" for k in K_VALUES])
ax2.minorticks_off()
ax2.set_xlabel("K (m/s)")
ax2.set_ylabel("discharge score at the gauge")
ax2.legend()

out = HERE / "summary" / "figures" / "sweep_k.png"
out.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(out, dpi=150)
print(out)
plt.show()
