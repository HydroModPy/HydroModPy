"""Play project.toml in the lab to watch the model take shape, then keep it as a run
and draw an overview of it: the water-table depth with the seepage cells and the particle
tracks, the section through the two wells, and the monthly recharge, outflow and pumping.
The tracks are then written for QGIS.

    python py1_run_and_plot.py
"""

# %% Setup

from pathlib import Path

import flopy
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import shapely
from shapely.geometry import LineString

import hydromodpy as hmp

HERE = Path(__file__).resolve().parent
FIGURES = HERE / "summary" / "figures"
FIGURES.mkdir(parents=True, exist_ok=True)

# %% Open the lab

# A lab holds the model in memory and plays the steps of a run one at a time.
# It writes nothing to runs/ until `lab.run`.
lab = hmp.Lab(HERE / "project.toml")


def draw_cells(ax, mesh, values, **kwargs):
    """Colour the cells of a regular mesh, stored row by row from the north."""
    nrow, ncol = mesh.structured_shape
    x, y = mesh.centers[:, 0].reshape(nrow, ncol), mesh.centers[:, 1].reshape(nrow, ncol)
    ax.set_aspect("equal")
    ax.ticklabel_format(useOffset=False, style="plain")
    ax.set(xlabel="x (m)", ylabel="y (m)")
    return ax.pcolormesh(x, y, values.reshape(nrow, ncol), shading="nearest", **kwargs)


# %% The mesh

# Play every step up to the mesh, then draw its cells and the contour of the catchment.
state = lab.advance("build_mesh")
contour = gpd.read_file(state.geographic.watershed_shp).boundary

fig, ax = plt.subplots(figsize=(6, 7), constrained_layout=True)
draw_cells(
    ax,
    state.mesh,
    np.zeros(state.mesh.n_cells),
    cmap="gray_r",
    vmin=0,
    vmax=1,
    edgecolors="0.6",
    lw=0.3,
)
contour.plot(ax=ax, color="crimson", lw=2, label="catchment contour")
ax.set_title(f"The mesh: {state.mesh.n_cells} cells")
ax.legend(loc="lower right")
fig.savefig(FIGURES / "lab_mesh.png", dpi=150)

# %% The wells

# `prepare_solver` freezes the model. Its `wells` map a name to a position and a rate.
state = lab.advance("prepare_solver")
fig, ax = plt.subplots(figsize=(6, 7), constrained_layout=True)
draw_cells(
    ax,
    state.mesh,
    np.zeros(state.mesh.n_cells),
    cmap="gray_r",
    vmin=0,
    vmax=1,
    edgecolors="0.6",
    lw=0.3,
)
contour.plot(ax=ax, color="crimson", lw=2)
for name, well in state.model.wells.items():
    peak = -min(well.flux) * 86400
    ax.plot(
        well.location.x,
        well.location.y,
        "o",
        ms=10,
        mec="k",
        label=f"{name}, up to {peak:.0f} m³/day",
    )
ax.set_title("The two pumping wells")
ax.legend(loc="lower right")
fig.savefig(FIGURES / "lab_wells.png", dpi=150)

# %% Solve and read the head


# `solve` plays what is left up to the solver. The heads are in the raw MODFLOW 6 files.
def january_head():
    solved = next(run for name, run in lab.solve().items() if "prt" not in name)
    heads = flopy.utils.HeadFile(str(next(Path(solved.output_dir).glob("*.hds")))).get_alldata()
    return np.where(np.abs(heads[0]) < 1e20, heads[0], np.nan).ravel()


head = january_head()
print(f"mean head in January, K = 1e-5 m/s: {np.nanmean(head):.3f} m")
fig, ax = plt.subplots(figsize=(7, 7), constrained_layout=True)
image = draw_cells(ax, state.mesh, head, cmap="viridis")
contour.plot(ax=ax, color="k", lw=1.5)
ax.set_title("Head in January, K = 1e-5 m/s")
fig.colorbar(image, ax=ax, shrink=0.8, label="head (m)")
fig.savefig(FIGURES / "lab_head.png", dpi=150)

# %% Change K

# A new K makes the model stale, and only the two solver steps play again.
lab.set(K=5e-5)
print(lab.steps[["step", "status"]].query("status != 'built'").to_string(index=False))
head = january_head()
print(f"mean head in January, K = 5e-5 m/s: {np.nanmean(head):.3f} m")

# %% Keep the run

# Back to the K of the file: the lab forgets changes that bring it back to the
# file, so the run kept is the run of project.toml.
# The test with K = 5e-5 m/s stays in the lab and leaves no trace.
lab.set(K=1e-5)
run = lab.run()
print(run.name)
lab.close()

# %% The data

# The mesh is 28 x 35 square cells, stored row by row from the north. Its cell centres
# give the x of each column and the y of each row.
nrow, ncol = run.mesh.structured_shape
centres = run.mesh.cell_centers()
x = centres[:ncol, 0]
y = centres[::ncol, 1]
size = x[1] - x[0]
north = y[0] + size / 2
extent = (x[0] - size / 2, x[-1] + size / 2, y[-1] - size / 2, north)

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
# A well takes water out, so MODFLOW stores its rate below zero: the figure shows the volume pumped.
pumping = -run.read("well").sum(dim=("layer", "cell")).to_numpy() * 86400

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
rows = north - y
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
pumped.set_ylim(0, 2 * pumping.max())
pumped.set_ylabel("pumping (m³/day)")
pumped.legend(loc="center right")
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
