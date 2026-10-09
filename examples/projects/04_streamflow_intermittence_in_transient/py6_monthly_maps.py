"""The twelve months of 2002 on one sheet, then the 36 months as a GIF: the
cells where the water table reaches the surface, drawn on the mesh with
matplotlib.

Reads the latest run of project.toml without running it:

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

# The latest live run of project.toml: find returns the runs from the most
# recent to the oldest and leaves the trash out.
cat = hmp.open(HERE)
run = cat.find(name_stem="nancon_intermittence_mf6")[0]
out = HERE / "runs" / run.name / "figures"

# %% The data

# One polygon per cell, in the order of the fields: face_node_connectivity
# gives the vertices of each cell. On this grid every cell is a 75 m square
# with four vertices.
mesh = run.mesh
cells = mesh.vertices[:, :2][mesh.face_node_connectivity]

# Keep the cells of the catchment only: the mesh covers the whole rectangle
# around it.
seepage = hmp.read(run, "seepage_mask").to_numpy() > 0  # (months, cells)
seepage &= run.catchment_mask.ravel()
months = run.periods.edges[:-1]
cell_km2 = run.grid.cell_size**2 / 1e6

watershed = hmp.read(run, "watershed")
network = hmp.read(run, "hydrographic_network_reference")
xmin, ymin, xmax, ymax = watershed.total_bounds

# %% The sheet of 2002

fig, axes = plt.subplots(3, 4, figsize=(12, 11), constrained_layout=True)
for ax, i in zip(axes.flat, np.flatnonzero(months.year == 2002), strict=True):
    ax.add_collection(PolyCollection(cells[seepage[i]], facecolor="tab:blue", edgecolor="none"))
    network.plot(ax=ax, color="0.65", lw=0.4)
    watershed.boundary.plot(ax=ax, color="k", lw=0.6)
    ax.set_title(f"{months[i]:%Y-%m}: {seepage[i].sum() * cell_km2:.2f} km²", fontsize="medium")
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.set_aspect("equal")
    ax.set_axis_off()
fig.suptitle(f"{run.name}: water table at the surface (blue) and mapped network (grey)")
fig.savefig(out / "seepage_2002_monthly.png", dpi=150)
print(out / "seepage_2002_monthly.png")
plt.close(fig)

# %% The GIF

# One collection for all the cells, whose colours change at each frame: much
# faster than drawing the map again.
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
