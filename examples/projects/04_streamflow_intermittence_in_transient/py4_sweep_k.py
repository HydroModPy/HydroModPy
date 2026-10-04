"""Balayage de K à partir de project.toml : un run par valeur, puis une
figure qui les met tous ensemble.

Le bassin, les données et le maillage sont préparés au premier run et
servent aux suivants, qui ne changent que K. Compter une minute par run.

    python py4_sweep_k.py
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import hydromodpy as hmp
from hydromodpy.config import HydroModPyConfig

HERE = Path(__file__).resolve().parent

# m/s. project.toml prend 5e-5.
K_VALUES = [1e-5, 2e-5, 5e-5, 1e-4, 2e-4]

# %% Les runs

# Ni figures ni exports par run, la figure du balayage suffit.
cfg = HydroModPyConfig.from_toml(HERE / "project.toml")
cfg.export = []

sim_ids = []
with hmp.Project(cfg, no_display=True) as project:
    for k in K_VALUES:
        sim_ids.append(project.simulate(name=f"nancon_k_{k:.0e}", K=k).sim_id)

# Le Project ferme son catalogue en sortant du with : on relit les runs dans
# le catalogue du projet.
cat = hmp.open(HERE)
runs = [cat[sim_id] for sim_id in sim_ids]

# %% Ce que chaque run donne

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
            "surface moyenne (km²)": area.mean(),
            "surface min (km²)": area.min(),
            "NSE": scores["nse"],
            "NSE log": scores["log_nse"],
        }
    )
table = pd.DataFrame(rows).set_index("K")
print(table.round(3))

# Le NSE bouge à peine d'un K à l'autre quand la surface suintante varie d'un
# facteur dix : le débit à la jauge ne contraint pas K, le réseau si. C'est
# pour cela que run_calibration.toml cale K sur le réseau cartographié.

# %% La figure

fig, (ax1, ax2) = plt.subplots(
    1, 2, figsize=(12, 4.5), width_ratios=[1.8, 1], constrained_layout=True
)
colors = plt.get_cmap("viridis")(np.linspace(0, 0.9, len(runs)))
for (k, area), color in zip(areas.items(), colors, strict=True):
    ax1.plot(months, area, color=color, label=f"K = {k:.0e} m/s")
ax1.set_yscale("log")
ax1.set_yticks([0.3, 1, 3, 10], ["0.3", "1", "3", "10"])
ax1.minorticks_off()
ax1.set_ylabel("surface suintante (km²)")
ax1.legend(fontsize="small")

ax2.plot(table.index, table["NSE"], "o-", color="k", label="NSE")
ax2.plot(table.index, table["NSE log"], "s--", color="0.5", label="NSE sur log Q")
ax2.set_xscale("log")
ax2.set_xticks(K_VALUES, [f"{k:.0e}" for k in K_VALUES])
ax2.minorticks_off()
ax2.set_xlabel("K (m/s)")
ax2.set_ylabel("score du débit à la jauge")
ax2.legend()

out = HERE / "share" / "figures" / "sweep_k.png"
out.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(out, dpi=150)
print(out)
plt.show()
