"""Play project.toml in the lab, one step at a time, and look at what each step built: the
catchment and its forcing, the mesh on the relief, and the ten layers the solver will read.
Then solve the flow, the nitrate and the particles, and keep the model as a run. From the run
the script counts, week by week, the water table, the seepage and the nitrate that the seepage
cells bring to the streams, draws the nitrate of each week as a box, asks HydroModPy for a map
of the nitrate every four weeks and stitches them into an animation. It ends with the travel
times of the particles.

    python py1_run_and_plot.py
"""

# %% Setup

from pathlib import Path

import geopandas as gpd
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shapely
from PIL import Image

import hydromodpy as hmp

HERE = Path(__file__).resolve().parent
FIGURES = HERE / "summary" / "figures"
FIGURES.mkdir(parents=True, exist_ok=True)

# %% Open the lab

# A lab holds the model in memory and plays the steps of a run one at a time. Nothing is
# built yet: each row of `lab.steps` is a step with its status.
lab = hmp.Lab(HERE / "project.toml")
print(lab.steps[["step", "status"]].to_string(index=False))

# %% The catchment and its forcing

# The catchment is cut out of the DEM from the outlet. `load_data` then reads the files of
# [data]: the DEM, the mapped streams, the gauged discharge, the recharge and the runoff.
state = lab.advance("load_data")
print(state.geographic)
print(state.data)

# The recharge is given per month and the runoff per day, both in mm/day. They are averaged
# here over the weeks of the model, beside the discharge gauged at the outlet over 2003, in
# mm/day over the area of the catchment.
area = float(gpd.read_file(state.geographic.watershed_shp).area.sum())
days = pd.date_range("2003-01-01", "2003-12-31", freq="D")
forcing = (
    pd.DataFrame(
        {
            name: getattr(state.data, name)
            .points[0]
            .data.set_index("datetime")["value"]
            .reindex(days, method="ffill")
            for name in ("recharge", "runoff")
        }
    )
    .resample("7D", origin="2003-01-01")
    .mean()
)
gauge = state.data.hydrometry.points[0].data.set_index("datetime")["value"]
gauge = gauge.loc["2003"].resample("7D", origin="2003-01-01").mean() * 86400 / area * 1000
print(forcing.iloc[::4].round(2).to_string())
fig, ax = plt.subplots(figsize=(8, 3))
ax.step(
    forcing.index, forcing["recharge"], where="post", color="dodgerblue", lw=2, label="recharge"
)
ax.step(forcing.index, forcing["runoff"], where="post", color="navy", lw=2, label="runoff")
ax.plot(gauge.index, gauge, color="k", lw=1.5, label="gauged discharge")
ax.set_ylabel("mm/day")
ax.set_title("Forcing of the drought year and gauged discharge, 2003")
ax.legend()
fig.savefig(FIGURES / "forcing_2003.png", dpi=150, bbox_inches="tight")

# %% The mesh on the relief, before the solve

# `prepare_solver` freezes the model the solver reads. A run stopped there already stores the
# ground of every cell, so it draws the mesh on the relief.
state = lab.advance("prepare_solver")
print(state.model)
before = lab.run(until_step="prepare_solver")
print(
    before.figure(
        "topography",
        overlays=["mesh", "outline", "network", "outlet"],
        save=FIGURES / "mesh_on_relief.png",
    )
)

# %% The ten layers

# `solve(build_only=True)` writes the MODFLOW 6 flow model without solving it. Its packages
# hold what the solver will read: one row per layer and one column per cell. The base is flat
# at 0 m and each layer is 1.2 times thicker than the one above it. K and Sy fall with depth,
# faster under the hills, at the ground for the first layer and at the base of the others. The nitrate moves through the pores of Sy, which serves
# as porosity. Each value is the mean over the cells of the box.
built = lab.solve(build_only=True)
mf6 = built["flow_main::modflow6"].solver_model
ground = np.asarray(state.model.geometry.column.top).ravel()
bases = mf6.dis.botm.array
tops = np.vstack([ground, bases[:-1]])
layers = pd.DataFrame(
    {
        "thickness (m)": (tops - bases).mean(axis=1),
        "base depth (m)": (ground - bases).mean(axis=1),
        "K (m/s)": mf6.npf.k.array.mean(axis=1),
        "Sy": mf6.sto.sy.array.mean(axis=1),
    },
    index=pd.RangeIndex(1, len(bases) + 1, name="layer"),
)
print(layers.to_string(float_format="{:.3g}".format))

# %% Solve and keep the run

# The run solves the flow, then the nitrate with GWT and the particles with PRT on the flow of
# each week. It then draws the figures and writes the files that project.toml asks for.
run = lab.run()
lab.close()
print(run.name)
for path in run.figures:
    print(path)

# %% The water table and the discharge, week by week

# Each week is named by its first day. Only the cells whose centre lies in the catchment are
# counted. The discharge is the drain flow routed to the outlet plus the runoff, in mm/day over
# the area of the catchment.
weeks = run.periods.edges[:-1]
centres = run.mesh.cell_centers()
inside = shapely.contains_xy(run.read("watershed").union_all(), centres[:, 0], centres[:, 1])
depth = run.read("watertable_depth").to_numpy()[:, inside]
seep = run.read("seepage_mask").to_numpy()[:, inside] > 0
discharge = run.read("discharge").to_numpy().ravel()[: len(weeks)] * 86400 / area * 1000
water = pd.DataFrame(
    {
        "depth (m)": depth.mean(axis=1),
        "seepage (%)": seep.mean(axis=1) * 100,
        "discharge (mm/day)": discharge,
    },
    index=pd.Index(weeks.strftime("%Y-%m-%d"), name="week"),
)
print(water.iloc[::4].round(2).to_string())

# %% The nitrate of the seepage, week by week

# The seepage cells of the catchment carry the nitrate of the top layer to the streams. The
# aquifer starts at 100 mg/L and the recharge brings 50 mg/L, so the nitrate falls while it
# rains, then slowly through the dry months as the water from deeper and older paths decays.
# The run stores kg/m3, and 1 kg/m3 is 1000 mg/L. A cell that does not seep holds no value.
nitrate = run.read("concentration_seepage").to_numpy()[:, inside] * 1000.0
boxes, means = [], []
for values in nitrate:
    values = values[np.isfinite(values) & (values > 0)]
    means.append(values.mean())
    boxes.append(
        {
            "med": np.median(values),
            "q1": np.quantile(values, 0.25),
            "q3": np.quantile(values, 0.75),
            "whislo": values.min(),
            "whishi": values.max(),
            "fliers": [],
        }
    )
stats = pd.DataFrame(
    {
        "min": [b["whislo"] for b in boxes],
        "median": [b["med"] for b in boxes],
        "mean": means,
        "max": [b["whishi"] for b in boxes],
    },
    index=water.index,
)
print(stats.iloc[::4].round(1).to_string())

# One box per week: the whiskers span every seepage cell, the box its middle half, and the
# black line joins the means. The recharge is drawn behind.
fig, ax = plt.subplots(figsize=(9, 4))
positions = mdates.date2num(weeks + pd.Timedelta(days=3))
ax.bxp(
    boxes,
    positions=positions,
    widths=4,
    showfliers=False,
    manage_ticks=False,
    boxprops={"color": "forestgreen"},
    medianprops={"color": "forestgreen"},
    whiskerprops={"color": "forestgreen"},
    capprops={"linewidth": 0},
)
ax.plot(positions, means, color="k", lw=2, label="mean of the seepage cells")
ax.axhline(50.0, color="darkorange", lw=1, label="nitrate of the recharge")
ax.set_ylabel("NO3 (mg/L)")
ax.set_ylim(30, 100)
ax.xaxis.set_major_locator(mdates.MonthLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
ax.legend(loc="upper right")
rain = ax.twinx()
rain.step(forcing.index, forcing["recharge"], where="post", color="dodgerblue", lw=1.5, zorder=0)
rain.set_ylabel("recharge (mm/day)", color="dodgerblue")
rain.set_ylim(0, 8)
ax.set_zorder(rain.get_zorder() + 1)
ax.patch.set_visible(False)
ax.set_title("Nitrate of the seepage cells, drought year 2003")
fig.savefig(FIGURES / "seepage_nitrate_by_week.png", dpi=150, bbox_inches="tight")

# %% A map every four weeks, and an animation

# `run.figure` takes the keys of a [[display.figure]] table and draws from the sealed run, so
# nothing is solved again. The scale is held from 30 to 100 mg/L, so the maps can be compared.
frames = []
for week in weeks[::4]:
    middle = (week + pd.Timedelta(days=3)).strftime("%Y-%m-%d")
    path = run.figure(
        "concentration_seepage",
        time=middle,
        limits=[30.0, 100.0],
        overlays=["outline", "network"],
        save=FIGURES / f"seepage_nitrate_{middle}.png",
    )
    frames.append(path)
images = [Image.open(path).convert("RGB") for path in frames]
images[0].save(
    FIGURES / "seepage_nitrate.gif", save_all=True, append_images=images[1:], duration=600, loop=0
)
print(FIGURES / "seepage_nitrate.gif")

# %% The travel times

# The [[export]] blocks of project.toml wrote these files when the run was sealed. The particle
# tracks are one line per particle, with its travel time in years from its cell to where it
# leaves the aquifer.
for path in run.exports:
    print(path)
tracks = gpd.read_file(next(path for path in run.exports if path.name == "pathlines.gpkg"))
years = np.sort(tracks["travel_yr"].to_numpy())
print(
    f"{len(years)} particles, median travel time {np.median(years):.1f} years, "
    f"10 % leave within {np.quantile(years, 0.1):.1f} years, 90 % within "
    f"{np.quantile(years, 0.9):.0f} years"
)
