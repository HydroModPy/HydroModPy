"""A figure made from the exported files alone, without importing HydroModPy:
pandas, geopandas, rasterio and xarray are enough. This is what a colleague
can do when you send the share/<run>/ folder.

The exports of step 5 come first:

    hmp run step5_export.toml
    python py3_read_exports.py                    # the last share/nancon_step5_export*
    python py3_read_exports.py path/to/share/<run>
"""

import sys
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
import shapely
import xarray as xr
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from rasterio.features import geometry_mask

HERE = Path(__file__).resolve().parent

if len(sys.argv) > 1:
    folder = Path(sys.argv[1])
else:
    # Running an edited step 5 again writes a new folder (.v2, .v3...). An
    # unchanged file is not computed again. Take the most recent folder.
    folder = max((HERE / "share").glob("nancon_step5_export*"), key=lambda p: p.stat().st_mtime)
print(folder)

# %% Reading

# The catchment, the mapped network, and the cells of the simulated active
# network in October 2002, the driest month of the record.
watershed = gpd.read_file(folder / "watershed.gpkg")
basin = watershed.geometry.iloc[0]
network = gpd.read_file(folder / "hydrographic_network_reference.gpkg")
active = gpd.read_file(folder / "simulated_active_network_2002-10-15.gpkg")
active = active[active.centroid.within(basin)]

# The depth of the water table that same month. The raster covers the whole
# model domain, so mask what lies outside the catchment.
with rasterio.open(folder / "watertable_depth_2002-10-15.tif") as src:
    depth = src.read(1, masked=True)
    outside = geometry_mask([basin], out_shape=depth.shape, transform=src.transform)
    extent = (src.bounds.left, src.bounds.right, src.bounds.bottom, src.bounds.top)
depth = np.ma.masked_where(outside, depth)

# Gauged and simulated discharge: a long CSV, one row per date and per series.
# The simulated value is dated at the end of its month (2001-02-01 for January
# 2001). Move it back to the first day to compare it with the monthly means of
# the gauge. Step 5 exports 2001-2002 only: the year 2000 is the spin-up.
series = pd.read_csv(next(folder.glob("*_series*.csv")), parse_dates=["datetime"])
q_obs = series.query("variable == 'discharge_obs'").set_index("datetime")["value"]
q_sim = series.query("variable == 'discharge'").set_index("datetime")["value"]
q_sim.index = q_sim.index - pd.offsets.MonthBegin(1)
q_obs = q_obs.resample("MS").mean().reindex(q_sim.index)

# The water-table record: one value per cell and per month, the cell centres
# in face_x and face_y. Same one-month shift as the CSV.
ds = xr.open_dataset(folder / "watertable_2000_2002.nc")
in_basin = shapely.contains_xy(basin, ds["face_x"].to_numpy(), ds["face_y"].to_numpy())
depth_cells = ds["watertable_depth"].to_numpy()[:, in_basin]
shallow = pd.Series(
    (depth_cells < 1.0).mean(axis=1) * 100,
    index=ds["time"].to_index() - pd.offsets.MonthBegin(1),
).loc[q_sim.index]

# Water budget of the catchment, in mm per year. The fluxes are mean rates per
# period (m3/s): multiply them by the length of the period. Recharge is
# positive, drains are negative, storage is positive when the aquifer empties.
budget = pd.read_csv(
    folder / "budget.csv", parse_dates=["period_start", "period_end"], dtype={"zone_id": str}
)
budget = budget[budget["zone_id"] == "catchment"]
seconds = (budget["period_end"] - budget["period_start"]).dt.total_seconds()
budget["mm"] = (budget["flux_in"] - budget["flux_out"]) * seconds / basin.area * 1000
year = budget["period_start"].dt.year.rename("year")
print(budget.pivot_table(index=year, columns="component", values="mm", aggfunc="sum").round())

# %% The figure

fig, axes = plt.subplot_mosaic(
    [["map", "q"], ["map", "shallow"]],
    figsize=(13, 6),
    width_ratios=[1, 1.3],
    constrained_layout=True,
)

ax = axes["map"]
im = ax.imshow(depth, extent=extent, cmap="YlGnBu_r", vmin=0, vmax=10)
active.plot(ax=ax, color="tab:red", alpha=0.7)
network.plot(ax=ax, color="navy", lw=0.7)
watershed.boundary.plot(ax=ax, color="k", lw=1)
xmin, ymin, xmax, ymax = basin.bounds
ax.set_xlim(xmin - 300, xmax + 300)
ax.set_ylim(ymin - 300, ymax + 300)
ax.set_axis_off()
ax.set_title("October 2002")
ax.legend(
    handles=[
        Line2D([], [], color="navy", lw=0.7, label="mapped network"),
        Patch(color="tab:red", alpha=0.7, label="simulated active network"),
    ],
    loc="upper left",
)
fig.colorbar(im, ax=ax, label="water-table depth (m)", shrink=0.7, extend="max")

ax = axes["q"]
ax.plot(q_obs, color="k", lw=1, label="gauged")
ax.plot(q_sim, color="tab:blue", label="simulated")
ax.set_yscale("log")
ax.set_yticks([0.3, 0.5, 1, 2], ["0.3", "0.5", "1", "2"])
ax.minorticks_off()
ax.set_ylabel("monthly discharge (m³/s)")
ax.tick_params(labelbottom=False)
ax.legend()

ax = axes["shallow"]
ax.plot(shallow, color="tab:green")
ax.set_ylabel("catchment with water table within 1 m (%)")
ax.sharex(axes["q"])

out = HERE / "share" / "figures" / f"{folder.name}_overview.png"
out.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(out, dpi=150)
print(out)
plt.show()
