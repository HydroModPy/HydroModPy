# -*- coding: utf-8 -*-
"""Nançon — specific yield (Sy) sensitivity.

Template showing how to drive HydroModPy from Python: sweep one
parameter across several runs, then read back each run's catalog
(DuckDB + Zarr) to build summary figures. Copy this file next to your
own ``project.toml`` and adjust the configuration block below.
"""

from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import ListedColormap

import hydromodpy as hmp


# ---------------------------------------------------------------------
# Configuration — edit these to fit your project
# ---------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
PROJECT_TOML = HERE / "project.toml"
FIG_DIR = HERE / "figures"

# Parameter sweep: one run per value.
SWEEP_PARAM = "Sy"
SWEEP_VALUES = [0.001, 0.05, 0.30]

# Other flow parameters held constant across the sweep.
FIXED_PARAMS = {"K": 5e-5, "Ss": 1e-5}

# Variable name written by the observation ingest (see
# `ingest_observations`). Suffix "_obs" distinguishes observed from
# simulated series in the `timeseries` table.
OBS_VARIABLE = "discharge_obs"


# ---------------------------------------------------------------------
# 1. Run the sweep
# ---------------------------------------------------------------------

project = hmp.Project(PROJECT_TOML)

runs = {}
for value in SWEEP_VALUES:
    runs[value] = project.run(
        name=f"{SWEEP_PARAM.lower()}_{value:.4f}",
        **{SWEEP_PARAM: value},
        **FIXED_PARAMS,
    )


# ---------------------------------------------------------------------
# 2. Geometric context (shared across runs) from the catalog
# ---------------------------------------------------------------------

first_run = next(iter(runs.values()))

thickness = first_run.params["thickness"]

grid = first_run.grid
cell_size = grid.cell_size
grid_shape = grid.shape
crs_extent = grid.extent
catchment_area_m2 = grid.catchment_area_m2

catchment_mask = first_run.catchment_mask
n_active_cells = int(catchment_mask.sum())

dem = first_run.dem
contour_gdf = first_run.geographic("watershed_contour")

dates = first_run.time_index
n_periods = len(dates)
sim_start, sim_end = dates[0], dates[-1]

FIG_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------
# 3. Catchment-level series: lazy views from the catalog
# ---------------------------------------------------------------------

saturated_fraction = {v: run.saturated_fraction().values for v, run in runs.items()}
drainage_density   = {v: run.drainage_density().values   for v, run in runs.items()}
accumulation_flux  = {v: run.fields("accumulation_flux") for v, run in runs.items()}


# ---------------------------------------------------------------------
# 4. Cross-sections
# ---------------------------------------------------------------------

fig, axes = plt.subplots(len(runs), 1, figsize=(7, 3.5 * len(runs)), dpi=200)
axes = np.atleast_1d(axes)

mid_row = grid_shape[0] // 2
distance = np.arange(grid_shape[1]) * cell_size
dem_profile = dem[mid_row, :]

for ax, (value, run) in zip(axes, runs.items()):
    density = saturated_fraction[value]
    t_min, t_max = int(density.argmin()), int(density.argmax())

    for label, tidx, color in [("Min", t_min, "navy"), ("Max", t_max, "dodgerblue")]:
        wt = run.field("watertable_elevation", tidx).reshape(grid_shape).copy()
        wt[wt < 0] = np.nan
        ax.fill_between(distance, dem_profile - thickness, wt[mid_row, :],
                        color=color, alpha=0.4, lw=0)
        ax.plot(distance, wt[mid_row, :], color=color, lw=1,
                label=f"{label} ({dates[tidx]:%Y-%m})")

    ax.fill_between(distance, wt[mid_row, :], dem_profile,
                    color="saddlebrown", alpha=0.3, lw=0)
    ax.plot(distance, dem_profile, color="saddlebrown", lw=1.5)
    ax.fill_between(distance, 0, dem_profile - thickness,
                    color="lightgrey", alpha=0.5, lw=0)
    ax.plot(distance, dem_profile - thickness, color="dimgray", lw=1)

    valid = np.isfinite(dem_profile)
    ax.set_xlim(distance[valid].min(), distance[valid].max())
    ax.set_ylim(np.nanmin(dem_profile) - thickness - 5,
                np.nanmax(dem_profile) + 5)
    ax.set_xlabel("Distance [m]")
    ax.set_ylabel("Elevation [m]")
    ax.set_title(f"{SWEEP_PARAM} = {value}", fontsize=10)
    ax.legend(fontsize=8)

fig.tight_layout()
fig.savefig(FIG_DIR / "cross_section_comparison.png", bbox_inches="tight")
plt.close(fig)


# ---------------------------------------------------------------------
# 5. Simulated vs observed discharge
# ---------------------------------------------------------------------

Q_obs = None
hydrometry = project.data.hydrometry
if hydrometry is not None and hydrometry.points:
    station_id = hydrometry.points[0].station_id
    q_raw = first_run.timeseries(OBS_VARIABLE, station=station_id)
    q_raw = q_raw.loc[sim_start:sim_end]
    Q_obs = (q_raw / catchment_area_m2 * 86400).resample("ME").sum() * 1000

# Daily-mean drain flux → monthly depth equivalent (mm/month).
days_in_month = np.array([d.days_in_month for d in dates])
Q_sim = {}
for value, run in runs.items():
    drain = run.fields("outflow_drain")
    drain[~np.isfinite(drain)] = 0.0
    q_daily = np.abs(drain * catchment_mask).sum(axis=(1, 2)) / catchment_area_m2 * 86400 * 1000
    Q_sim[value] = pd.Series(q_daily * days_in_month, index=dates)

pos = np.concatenate([q.values for q in Q_sim.values()]
                     + ([Q_obs.values] if Q_obs is not None else []))
pos = pos[pos > 0]
y_min, y_max = float(pos.min()) * 0.5, float(pos.max()) * 2.0

fig, axes = plt.subplots(len(runs), 2, figsize=(12, 3.5 * len(runs)),
                         gridspec_kw={"width_ratios": [3, 1]}, dpi=200)
axes = axes.reshape(len(runs), 2)

for (ax_ts, ax_sc), (value, q_sim) in zip(axes, Q_sim.items()):
    if Q_obs is not None:
        ax_ts.plot(Q_obs, color="k", lw=2, label="Observed")
    ax_ts.plot(q_sim, color="red", lw=2, label="Simulated")
    ax_ts.set_ylabel("Q/A [mm/month]")
    ax_ts.set_yscale("log")
    ax_ts.set_ylim(y_min, y_max)
    ax_ts.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax_ts.legend(fontsize=8)
    ax_ts.set_title(f"{SWEEP_PARAM} = {value}", fontsize=10)

    if Q_obs is not None:
        q_aligned = q_sim.reindex(Q_obs.index, method="nearest")
        ax_sc.scatter(Q_obs, q_aligned, s=20, alpha=0.7,
                      color="forestgreen", edgecolor="none")
        ax_sc.plot([max(1, y_min), y_max], [max(1, y_min), y_max],
                   color="grey", zorder=-1)
        ax_sc.set_xscale("log")
        ax_sc.set_yscale("log")
        ax_sc.set_xlim(max(1, y_min), y_max)
        ax_sc.set_ylim(max(1, y_min), y_max)
        ax_sc.set_xlabel("Obs [mm/month]")
        ax_sc.set_ylabel("Sim [mm/month]")

fig.tight_layout()
fig.savefig(FIG_DIR / "streamflow_comparison.png", bbox_inches="tight")
plt.close(fig)


# ---------------------------------------------------------------------
# 6. Intermittent vs perennial drainage density
# ---------------------------------------------------------------------

fig, axes = plt.subplots(len(runs), 1, figsize=(8, 3 * len(runs)), dpi=200)
axes = np.atleast_1d(axes)

for ax, (value, intermittent) in zip(axes, drainage_density.items()):
    active = (accumulation_flux[value] > 0) & catchment_mask
    perennial = np.zeros(n_periods)
    for year in sorted({d.year for d in dates}):
        yr = [t for t, d in enumerate(dates) if d.year == year]
        always = active[yr].all(axis=0)
        perennial[yr] = 100.0 * (always & catchment_mask).sum() / n_active_cells

    ax.fill_between(dates, 0, intermittent, step="pre",
                    color="dodgerblue", alpha=0.5, label="Intermittent")
    ax.fill_between(dates, 0, perennial, step="pre",
                    color="navy", alpha=0.5, label="Perennial")
    ax.set_ylabel("Drainage density [%]")
    ax.set_xlim(sim_start, sim_end)
    ax.set_ylim(0, None)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_minor_locator(mdates.MonthLocator())
    ax.set_title(f"{SWEEP_PARAM} = {value}", fontsize=10)
    ax.legend(fontsize=8)

fig.tight_layout()
fig.savefig(FIG_DIR / "drainage_density_comparison.png", bbox_inches="tight")
plt.close(fig)


# ---------------------------------------------------------------------
# 7. Saturation maps (min/max) with vector contour
# ---------------------------------------------------------------------

fig, axes = plt.subplots(len(runs), 2, figsize=(8, 4 * len(runs)), dpi=200)
axes = axes.reshape(len(runs), 2)

for row_axes, (value, run) in zip(axes, runs.items()):
    density = saturated_fraction[value]
    t_min, t_max = int(density.argmin()), int(density.argmax())

    for ax, (tidx, label) in zip(row_axes, [(t_min, "Min"), (t_max, "Max")]):
        flux = accumulation_flux[value][tidx]
        ax.set_title(f"{SWEEP_PARAM}={value}  {label} ({dates[tidx]:%Y-%m})  "
                     f"Asat={density[tidx]:.1f}%", fontsize=9)
        ax.imshow(np.ma.masked_where(~catchment_mask, dem),
                  cmap="Greys", alpha=0.5, extent=crs_extent, origin="upper")
        ax.imshow(np.ma.masked_where((flux <= 0) | ~catchment_mask, flux),
                  cmap=ListedColormap(["navy"]), extent=crs_extent, origin="upper")
        contour_gdf.plot(ax=ax, color="black", lw=0.6)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_aspect("equal")

fig.tight_layout()
fig.savefig(FIG_DIR / "saturation_maps_comparison.png", bbox_inches="tight")
plt.close(fig)


# ---------------------------------------------------------------------
# 8. Persistence index
# ---------------------------------------------------------------------

fig, axes = plt.subplots(1, len(runs), figsize=(4 * len(runs), 5), dpi=200)
axes = np.atleast_1d(axes)

for ax, (value, accflux_stack) in zip(axes, accumulation_flux.items()):
    persistency = (accflux_stack > 0).sum(axis=0) / n_periods
    pi = np.ma.masked_where(~catchment_mask | (persistency <= 0), persistency)
    im = ax.imshow(pi, cmap="jet", vmin=0, vmax=1,
                   extent=crs_extent, origin="upper")
    contour_gdf.plot(ax=ax, color="black", lw=0.6)
    ax.set_title(f"{SWEEP_PARAM} = {value}", fontsize=10)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_aspect("equal")

cbar_ax = fig.add_axes([0.25, 0.05, 0.5, 0.02])
fig.colorbar(im, cax=cbar_ax, orientation="horizontal",
             label="Persistence index [-]")
fig.tight_layout(rect=[0, 0.08, 1, 1])
fig.savefig(FIG_DIR / "persistency_comparison.png", bbox_inches="tight")
plt.close(fig)


project.close()
