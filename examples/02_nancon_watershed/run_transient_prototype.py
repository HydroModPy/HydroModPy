# -*- coding: utf-8 -*-
"""Nançon — sensibilité à la porosité de drainage (Sy).

Montre comment piloter HydroModPy depuis Python, faire varier un
paramètre à chaque run, puis relire le catalogue (DuckDB + Zarr) pour
tracer les figures de synthèse.
"""

from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import ListedColormap

import hydromodpy as hmp


HERE = Path(__file__).resolve().parent
SY_VALUES = [0.001, 0.05, 0.30]

# ---------------------------------------------------------------------
# 1. Trois runs MODFLOW-NWT, Sy variable
# ---------------------------------------------------------------------

project = hmp.Project(HERE / "project.toml")

runs = {}
for sy in SY_VALUES:
    runs[sy] = project.run(Sy=sy, K=5e-5, Ss=1e-5, name=f"nancon_sy_{sy:.4f}")


# ---------------------------------------------------------------------
# 2. Contexte géométrique (commun aux 3 runs) lu depuis le catalogue
# ---------------------------------------------------------------------

first_run = next(iter(runs.values()))
catalog = project.store
zarr_store = catalog.open_zarr(first_run.sim_id)

thickness = first_run.parameters.loc["thickness", "value"]

dem, dem_meta = zarr_store.read_geographic_raster("watershed_dem")
dem = dem.astype(float)
dem[dem < 0] = np.nan

cell_size = abs(float(dem_meta["transform"][0]))
grid_shape = dem.shape
catchment_mask = np.isfinite(dem) & (dem > 0)
n_active_cells = int(catchment_mask.sum())
catchment_area_m2 = n_active_cells * cell_size ** 2

# imshow en CRS réel pour overlay direct du contour vectoriel
t = dem_meta["transform"]
xmin, ymax = t[2], t[5]
crs_extent = (xmin, xmin + grid_shape[1] * t[0], ymax + grid_shape[0] * t[4], ymax)

contour_gdf = catalog.read_geographic_feature(first_run.sim_id, "watershed_contour")

n_periods = project.time_grid.nper
dates = pd.date_range(start="2000-01-01", end="2002-12-31", freq="ME")

fig_dir = HERE / "figures"
fig_dir.mkdir(parents=True, exist_ok=True)


def rasters(run, variable):
    """Pile (n_periods, nrow, ncol) pour une variable cell-based."""
    return np.stack([run.field(variable, t).reshape(grid_shape)
                     for t in range(n_periods)])


# ---------------------------------------------------------------------
# 3. Séries catchment : vues lazy depuis le catalogue
# ---------------------------------------------------------------------

saturated_fraction = {sy: catalog[run.sim_id].saturated_fraction().values
                      for sy, run in runs.items()}
drainage_density = {sy: catalog[run.sim_id].drainage_density().values
                    for sy, run in runs.items()}

# Rasters nécessaires pour les cartes et la persistance spatiale
accumulation_flux = {sy: rasters(run, "accumulation_flux") for sy, run in runs.items()}


# ---------------------------------------------------------------------
# 4. Coupes transversales
# ---------------------------------------------------------------------

fig, axes = plt.subplots(len(runs), 1, figsize=(7, 3.5 * len(runs)), dpi=200)
axes = np.atleast_1d(axes)

mid_row = grid_shape[0] // 2
distance = np.arange(grid_shape[1]) * cell_size
dem_profile = dem[mid_row, :]

for ax, (sy, run) in zip(axes, runs.items()):
    density = saturated_fraction[sy]
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
    ax.set_ylabel("Élévation [m]")
    ax.set_title(f"Sy = {sy}", fontsize=10)
    ax.legend(fontsize=8)

fig.tight_layout()
fig.savefig(fig_dir / "cross_section_comparison.png", bbox_inches="tight")
plt.close(fig)


# ---------------------------------------------------------------------
# 5. Débits simulés vs observés (obs hors catalogue pour l'instant)
# ---------------------------------------------------------------------

obs_csv = HERE.parent / "data/hydrometry/hydrometry_custom_NANCON_19820201_20220125_D.csv"
Q_obs = None
if obs_csv.exists():
    q_raw = pd.read_csv(obs_csv, index_col=0, parse_dates=True).squeeze()
    area_m2 = project.geographic.catch_area * 1e6
    Q_obs = (q_raw / area_m2 * 86400).resample("ME").sum() * 1000
    Q_obs = Q_obs[(Q_obs.index.year >= 2000) & (Q_obs.index.year <= 2002)]

Q_sim = {}
days_in_month = np.array([d.day for d in dates])
for sy, run in runs.items():
    drain = rasters(run, "outflow_drain")
    drain[~np.isfinite(drain)] = 0.0
    q_daily = np.abs(drain * catchment_mask).sum(axis=(1, 2)) / catchment_area_m2 * 86400 * 1000
    Q_sim[sy] = pd.Series(q_daily * days_in_month, index=dates)

pos = np.concatenate([q.values for q in Q_sim.values()]
                     + ([Q_obs.values] if Q_obs is not None else []))
pos = pos[pos > 0]
y_min, y_max = float(pos.min()) * 0.5, float(pos.max()) * 2.0

fig, axes = plt.subplots(len(runs), 2, figsize=(12, 3.5 * len(runs)),
                         gridspec_kw={"width_ratios": [3, 1]}, dpi=200)
axes = axes.reshape(len(runs), 2)

for (ax_ts, ax_sc), (sy, q_sim) in zip(axes, Q_sim.items()):
    if Q_obs is not None:
        ax_ts.plot(Q_obs, color="k", lw=2, label="Observé")
    ax_ts.plot(q_sim, color="red", lw=2, label="Simulé")
    ax_ts.set_ylabel("Q/A [mm/mois]")
    ax_ts.set_yscale("log")
    ax_ts.set_ylim(y_min, y_max)
    ax_ts.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax_ts.set_xlim(pd.Timestamp("1999"), pd.Timestamp("2004"))
    ax_ts.legend(fontsize=8)
    ax_ts.set_title(f"Sy = {sy}", fontsize=10)

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
        ax_sc.set_xlabel("Obs [mm/mois]")
        ax_sc.set_ylabel("Sim [mm/mois]")

fig.tight_layout()
fig.savefig(fig_dir / "streamflow_comparison.png", bbox_inches="tight")
plt.close(fig)


# ---------------------------------------------------------------------
# 6. Densité de drainage intermittent vs pérenne
# ---------------------------------------------------------------------

fig, axes = plt.subplots(len(runs), 1, figsize=(8, 3 * len(runs)), dpi=200)
axes = np.atleast_1d(axes)

for ax, (sy, intermittent) in zip(axes, drainage_density.items()):
    active = (accumulation_flux[sy] > 0) & catchment_mask
    perennial = np.zeros(n_periods)
    for year in sorted({d.year for d in dates}):
        yr = [t for t, d in enumerate(dates) if d.year == year]
        always = active[yr].all(axis=0)
        perennial[yr] = 100.0 * (always & catchment_mask).sum() / n_active_cells

    ax.fill_between(dates, 0, intermittent, step="pre",
                    color="dodgerblue", alpha=0.5, label="Intermittent")
    ax.fill_between(dates, 0, perennial, step="pre",
                    color="navy", alpha=0.5, label="Pérenne")
    ax.set_ylabel("Densité de drainage [%]")
    ax.set_xlim(pd.Timestamp("2000-01"), pd.Timestamp("2002-12"))
    ax.set_ylim(0, None)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_minor_locator(mdates.MonthLocator())
    ax.set_title(f"Sy = {sy}", fontsize=10)
    ax.legend(fontsize=8)

fig.tight_layout()
fig.savefig(fig_dir / "drainage_density_comparison.png", bbox_inches="tight")
plt.close(fig)


# ---------------------------------------------------------------------
# 7. Cartes de saturation (min/max) avec contour vectoriel
# ---------------------------------------------------------------------

fig, axes = plt.subplots(len(runs), 2, figsize=(8, 4 * len(runs)), dpi=200)
axes = axes.reshape(len(runs), 2)

for row_axes, (sy, run) in zip(axes, runs.items()):
    density = saturated_fraction[sy]
    t_min, t_max = int(density.argmin()), int(density.argmax())

    for ax, (tidx, label) in zip(row_axes, [(t_min, "Min"), (t_max, "Max")]):
        flux = accumulation_flux[sy][tidx]
        ax.set_title(f"Sy={sy}  {label} ({dates[tidx]:%Y-%m})  "
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
fig.savefig(fig_dir / "saturation_maps_comparison.png", bbox_inches="tight")
plt.close(fig)


# ---------------------------------------------------------------------
# 8. Indice de persistance
# ---------------------------------------------------------------------

fig, axes = plt.subplots(1, len(runs), figsize=(4 * len(runs), 5), dpi=200)
axes = np.atleast_1d(axes)

for ax, (sy, accflux_stack) in zip(axes, accumulation_flux.items()):
    persistency = (accflux_stack > 0).sum(axis=0) / n_periods
    pi = np.ma.masked_where(~catchment_mask | (persistency <= 0), persistency)
    im = ax.imshow(pi, cmap="jet", vmin=0, vmax=1,
                   extent=crs_extent, origin="upper")
    contour_gdf.plot(ax=ax, color="black", lw=0.6)
    ax.set_title(f"Sy = {sy}", fontsize=10)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_aspect("equal")

cbar_ax = fig.add_axes([0.25, 0.05, 0.5, 0.02])
fig.colorbar(im, cax=cbar_ax, orientation="horizontal",
             label="Indice de persistance [-]")
fig.tight_layout(rect=[0, 0.08, 1, 1])
fig.savefig(fig_dir / "persistency_comparison.png", bbox_inches="tight")
plt.close(fig)


project.close()
