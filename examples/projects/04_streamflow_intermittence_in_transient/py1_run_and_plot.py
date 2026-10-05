"""Lance step4_transient.toml depuis Python, puis trace une figure que
HydroModPy ne propose pas : la surface du bassin où la nappe affleure, mois
par mois, et son lien avec le débit à l'exutoire.

    python py1_run_and_plot.py
"""

from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import hydromodpy as hmp

HERE = Path(__file__).resolve().parent

# %% Le run

# Équivaut à `hmp run step4_transient.toml`, figures et exports compris.
# Chaque relance crée un nouveau run, nancon_step4_transient.v2, .v3...
run = hmp.run(HERE / "step4_transient.toml")
print(run.name)

# %% Les données

# Les champs sont rangés par période de stress, sans date. La période i va de
# edges[i] à edges[i + 1] ; on repère chaque mois par son premier jour.
months = run.periods.edges[:-1]

# Débit simulé, moyenne du mois, et débit jaugé, journalier, moyenné sur les
# mêmes mois. Les deux en m3/s.
q_sim = pd.Series(hmp.read(run, "discharge").to_numpy(), index=months)
q_obs = hmp.read(run, "discharge_obs").resample("MS").mean().reindex(months)

# Le maillage couvre le rectangle autour du bassin : on ne compte que les
# cellules du bassin. Ici le maillage est la grille du MNT, ligne par ligne,
# d'où le ravel du masque.
seepage = hmp.read(run, "seepage_mask").to_numpy() > 0  # (mois, cellules)
in_catchment = run.catchment_mask.ravel()
cell_km2 = run.grid.cell_size**2 / 1e6
area = pd.Series((seepage & in_catchment).sum(axis=1) * cell_km2, index=months)

# Surface suintante en loi de puissance du débit, A = a Q^b, comme Godsey et
# Kirchner (2014) pour la longueur du réseau actif. L'année 2000 sert de mise
# en route du modèle, on l'écarte.
kept = months.year >= 2001
b, log_a = np.polyfit(np.log(q_sim[kept]), np.log(area[kept]), 1)
print(f"exposant b = {b:.2f}")

# %% La figure

fig, axes = plt.subplot_mosaic(
    [["q", "fit"], ["area", "fit"]],
    figsize=(12, 6),
    width_ratios=[1.7, 1],
    constrained_layout=True,
)

ax = axes["q"]
ax.plot(months, q_obs, color="k", lw=1, label="jaugé")
ax.plot(months, q_sim, color="tab:blue", label="simulé")
ax.set_yscale("log")
ax.set_yticks([0.3, 0.5, 1, 2], ["0.3", "0.5", "1", "2"])
ax.minorticks_off()
ax.set_ylabel("débit (m³/s)")
ax.tick_params(labelbottom=False)
ax.legend()

ax = axes["area"]
ax.fill_between(months, area, color="tab:orange", alpha=0.5)
ax.set_ylabel("surface suintante (km²)")
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
ax.set_xlabel("débit simulé (m³/s)")
ax.set_ylabel("surface suintante (km²)")
ax.set_title("2001-2002")
ax.legend()
fig.colorbar(points, ax=ax, label="mois", ticks=[1, 4, 7, 10])

fig.suptitle(f"{run.name} : nappe affleurante et débit")

# La figure va avec le run qu'elle décrit, à côté de celles de [display].
out = HERE / "runs" / run.name / "figures" / "seepage_vs_discharge.png"
out.parent.mkdir(exist_ok=True)
fig.savefig(out, dpi=150)
print(out)
plt.show()
