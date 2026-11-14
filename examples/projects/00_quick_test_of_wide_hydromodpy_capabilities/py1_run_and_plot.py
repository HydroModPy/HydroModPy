"""Run project.toml from Python, then draw a figure of your own from what the
run stored: the water-table depth with the seepage cells and the particle
tracks, the section through the two wells, and the monthly recharge, outflow
and pumping. The tracks are then written for QGIS.

    python py1_run_and_plot.py
"""

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import shapely
from shapely.geometry import LineString

import hydromodpy as hmp

HERE = Path(__file__).resolve().parent

# %% The run

# The same as `hmp run project.toml`, figures and exports included. An unchanged
# file is not computed again: the run of the last execution comes back.
run = hmp.run(HERE / "project.toml").open()
print(run.name)

# %% The data

# The grid is the 28 x 35 cells of the DEM, stored row by row from the north.
nrow, ncol = run.grid.shape
xmin, xmax, ymin, ymax = run.grid.extent
extent = (xmin, xmax, ymin, ymax)
size = run.grid.cell_size
x = xmin + size * (np.arange(ncol) + 0.5)
y = ymax - size * (np.arange(nrow) + 0.5)

# January is period 0, the month both wells pump.
depth = run.read("watertable_depth", time=0).to_numpy().reshape(nrow, ncol)
seepage = run.read("seepage_mask", time=0).to_numpy().reshape(nrow, ncol) > 0
elevation = run.read("watertable_elevation", time=0).to_numpy().reshape(nrow, ncol)
ground = run.read("topography").to_numpy().reshape(nrow, ncol)

# The catchment polygon, and the cells whose centre lies in it.
watershed = run.read("watershed")
xx, yy = np.meshgrid(x, y)
inside = shapely.contains_xy(watershed.union_all(), xx, yy)
area = inside.sum() * size**2

# One row per position of a particle. Each track runs from the cell it was
# released in, at the start of January, to where it leaves the aquifer.
particles = run.read("particles").sort_values(["particle", "step"])
tracks = particles.groupby("particle")[["x", "y"]].apply(lambda p: LineString(p.to_numpy()))

# Monthly rates in mm per month of 30 days. The recharge is the one the model
# received: the steady January takes the mean.
months = run.periods.edges[:-1]
recharge = run.recharge_forcing().to_numpy() * 86400 * 30 * 1000
drained = (run.read("outflow_drain").to_numpy() * inside.ravel()).sum(axis=1)
outflow = drained / area * 86400 * 30 * 1000
pumping = run.read("well").sum(dim=("layer", "cell")).to_numpy() * 86400

# %% The figures

fig, axes = plt.subplots(1, 3, figsize=(18, 5), constrained_layout=True)

ax = axes[0]
image = ax.imshow(depth, extent=extent, cmap="jet", vmin=0, vmax=10, alpha=0.5)
ax.imshow(np.ma.masked_where(~seepage, seepage), extent=extent, cmap="gray_r", vmin=0, vmax=1)
watershed.boundary.plot(ax=ax, color="k", lw=2)
gpd.GeoSeries(tracks.to_list()).plot(ax=ax, color="k", lw=0.3)
ax.axvline(x[28], color="k", ls="--", lw=2)
ax.ticklabel_format(useOffset=False, style="plain")
ax.set_title("Seepage fed by pathlines, water-table depth in January")
fig.colorbar(image, ax=ax, label="water-table depth (m)")

ax = axes[1]
rows = ymax - y
ax.fill_between(rows, 0, elevation[:, 28], step="mid", color="dodgerblue", alpha=0.3)
ax.fill_between(rows, elevation[:, 28], ground[:, 28], step="mid", color="saddlebrown", alpha=0.3)
ax.step(rows, elevation[:, 28], where="mid", color="blue", lw=3, label="water table")
ax.step(rows, ground[:, 28], where="mid", color="saddlebrown", lw=3, label="topography")
ax.set_ylim(50, 72)
ax.set_xlabel("distance from the north edge (m)")
ax.set_ylabel("elevation (m)")
ax.set_title(f"Section at x = {x[28]:.0f} m through the two wells, January")
ax.legend()

ax = axes[2]
ax.step(months, recharge, where="post", color="dodgerblue", lw=6, label="recharge")
ax.step(months, outflow, where="post", color="red", lw=3, label="outflow of the catchment")
ax.set_ylim(0, 70)
ax.set_ylabel("mm per month")
ax.legend(loc="upper right")
pumped = ax.twinx()
pumped.bar(months, pumping, width=5, color="darkorange", label="pumping, both wells")
pumped.set_ylabel("pumping (m³/day)")
pumped.legend(loc="lower right")
ax.set_title("Monthly stress periods of 2017")

fig.suptitle(f"{run.name}: wells, seepage and particles in January")

# A figure a script draws from a run is derived, not sealed: it goes to
# summary/figures/, never into the run, whose figures/ holds the [display] list.
out = HERE / "summary" / "figures" / f"{run.name}_wells_and_seepage.png"
out.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(out, dpi=150)
print(out)

# %% The tracks for QGIS

# [[export]] writes the fields, the series and the catchment layers, not the
# tracks yet. They are one GeoDataFrame away, in the CRS of the project.
travel = particles.groupby("particle")["time_days"].max() / 365.25
layer = gpd.GeoDataFrame({"travel_years": travel}, geometry=tracks.to_list(), crs=watershed.crs)
gpkg = HERE / "summary" / f"{run.name}_particle_tracks.gpkg"
layer.to_file(gpkg, driver="GPKG")
print(gpkg)
plt.show()
