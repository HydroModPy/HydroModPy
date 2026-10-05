"""Les douze mois de 2002 sur une planche, puis les 36 mois en GIF : les
cellules où la nappe affleure, dessinées sur le maillage avec matplotlib.

Lit le dernier run de project.toml sans le relancer :

    hmp run project.toml
    python py6_monthly_maps.py
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation, PillowWriter
from matplotlib.collections import PolyCollection
from matplotlib.colors import ListedColormap

import hydromodpy as hmp

HERE = Path(__file__).resolve().parent

# Le dernier run vivant de project.toml : find range du plus récent au plus
# ancien et laisse de côté la corbeille.
cat = hmp.open(HERE)
run = cat.find(name_stem="nancon_intermittence_mf6")[0]
out = HERE / "runs" / run.name / "figures"

# %% Les données

# Un polygone par cellule, dans l'ordre des champs : les sommets de chaque
# cellule sont donnés par face_node_connectivity. Sur cette grille, toutes
# les cellules sont des carrés de 75 m, quatre sommets chacune.
mesh = run.mesh
cells = mesh.vertices[:, :2][mesh.face_node_connectivity]

# On ne garde que les cellules du bassin : le maillage couvre tout le
# rectangle autour.
seepage = hmp.read(run, "seepage_mask").to_numpy() > 0  # (mois, cellules)
seepage &= run.catchment_mask.ravel()
months = run.periods.edges[:-1]
cell_km2 = run.grid.cell_size**2 / 1e6

watershed = hmp.read(run, "watershed")
network = hmp.read(run, "hydrographic_network_reference")
xmin, ymin, xmax, ymax = watershed.total_bounds

# %% La planche de 2002

fig, axes = plt.subplots(3, 4, figsize=(12, 11), constrained_layout=True)
for ax, i in zip(axes.flat, np.flatnonzero(months.year == 2002), strict=True):
    ax.add_collection(PolyCollection(cells[seepage[i]], facecolor="tab:blue", edgecolor="none"))
    network.plot(ax=ax, color="0.65", lw=0.4)
    watershed.boundary.plot(ax=ax, color="k", lw=0.6)
    ax.set_title(f"{months[i]:%Y-%m} : {seepage[i].sum() * cell_km2:.2f} km²", fontsize="medium")
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.set_aspect("equal")
    ax.set_axis_off()
fig.suptitle(f"{run.name} : nappe affleurante (bleu) et réseau cartographié (gris)")
fig.savefig(out / "seepage_2002_monthly.png", dpi=150)
print(out / "seepage_2002_monthly.png")
plt.close(fig)

# %% Le GIF

# Une seule collection pour toutes les cellules, dont on change la couleur à
# chaque image : bien plus rapide que de redessiner la carte.
fig, ax = plt.subplots(figsize=(5, 6), constrained_layout=True)
coll = PolyCollection(cells, cmap=ListedColormap(["white", "tab:blue"]), edgecolor="none")
coll.set_clim(0, 1)
ax.add_collection(coll)
network.plot(ax=ax, color="0.65", lw=0.4)
watershed.boundary.plot(ax=ax, color="k", lw=0.6)
ax.set_xlim(xmin, xmax)
ax.set_ylim(ymin, ymax)
ax.set_aspect("equal")
ax.set_axis_off()
title = ax.set_title("")


def draw(i):
    coll.set_array(seepage[i])
    title.set_text(f"{months[i]:%Y-%m}")
    return coll, title


FuncAnimation(fig, draw, frames=len(months)).save(
    out / "seepage_2000_2002.gif", writer=PillowWriter(fps=3), dpi=80
)
print(out / "seepage_2000_2002.gif")
