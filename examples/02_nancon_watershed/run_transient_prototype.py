# -*- coding: utf-8 -*-
"""Nançon — sensibilité à la porosité de drainage (Sy).

Montre comment piloter HydroModPy depuis un script et comment retaper
dans le catalogue (DuckDB + Zarr) pour rejouer des figures a posteriori.

    python run_transient_prototype.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import ListedColormap

import hydromodpy as hmp


# ---------------------------------------------------------------------
# 1. Lancement des trois simulations
# ---------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
SY_VALUES = [0.001, 0.05, 0.30]
K_VALUE = 5e-5           # m/s (fixé)
SS_VALUE = 1e-5          # 1/m (fixé)
THICKNESS = 30.0         # m

project = hmp.Simulation(HERE / "project.toml")
print(f"Bassin du Nançon — surface = {project.geographic.catch_area:.1f} km²")

runs: dict[float, "hmp.SimulationResult"] = {}
for i, sy in enumerate(SY_VALUES, start=1):
    label = f"nancon_sy_{sy:.4f}"
    print(f"\nRun {i}/{len(SY_VALUES)} — Sy={sy}  ({label})")
    try:
        runs[sy] = project.run(Sy=sy, K=K_VALUE, Ss=SS_VALUE, name=label)
        print("  convergé")
    except Exception as err:
        print(f"  ÉCHEC : {err}")

if not runs:
    sys.exit("Aucun run convergé.")

print(f"\n{len(runs)}/{len(SY_VALUES)} runs convergés.")


# ---------------------------------------------------------------------
# 2. Lecture de la géométrie et du contour depuis le catalogue
# ---------------------------------------------------------------------

first_run = next(iter(runs.values()))
catalog = project.store
zarr_store = catalog.open_zarr(first_run.sim_id)

dem, dem_meta = zarr_store.read_geographic_raster("watershed_dem")
dem = dem.astype(float)
dem[dem < 0] = np.nan

cell_size = abs(float(dem_meta["transform"][0]))
grid_shape = dem.shape
catchment_mask = np.isfinite(dem) & (dem > 0)
n_active_cells = int(catchment_mask.sum())
catchment_area_m2 = n_active_cells * cell_size ** 2

# extent (xmin, xmax, ymin, ymax) pour imshow en CRS : permet de
# superposer directement les GeoDataFrames (pas de rasterisation).
t = dem_meta["transform"]
xmin, ymax = t[2], t[5]
xmax = xmin + grid_shape[1] * t[0]
ymin = ymax + grid_shape[0] * t[4]
crs_extent = (xmin, xmax, ymin, ymax)

contour_gdf = catalog.read_geographic_feature(first_run.sim_id, "watershed_contour")


# ---------------------------------------------------------------------
# 3. Séries temporelles par run (lues depuis le Zarr)
# ---------------------------------------------------------------------

n_periods = project.time_grid.nper
dates = pd.date_range(start="2000-01-01", end="2002-12-31", freq="ME")
days_in_month = np.array([d.day for d in dates])

fig_dir = HERE / "figures"
fig_dir.mkdir(parents=True, exist_ok=True)


def rasters(run, variable: str) -> np.ndarray:
    """Pile 3D (n_periods, nrow, ncol) pour une variable cell-based."""
    return np.stack([
        run.field(variable, t).reshape(grid_shape) for t in range(n_periods)
    ])


# Vues lazy : seepage_areas et drainage_density sont réduits à la volée
# depuis les rasters `derived/` (pas matérialisés dans DuckDB).
saturated_fraction = {sy: catalog[run.sim_id].saturated_fraction().values
                      for sy, run in runs.items()}
drainage_density = {sy: catalog[run.sim_id].drainage_density().values
                    for sy, run in runs.items()}

# accumulation_flux (raster) reste nécessaire pour les cartes de
# saturation et l'indice de persistance (calcul spatial par cellule).
accumulation_flux = {sy: rasters(run, "accumulation_flux") for sy, run in runs.items()}


# ---------------------------------------------------------------------
# 4. Coupes transversales (min/max Asat)
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
        wt_profile = wt[mid_row, :]
        ax.fill_between(distance, dem_profile - THICKNESS, wt_profile,
                        color=color, alpha=0.4, lw=0)
        ax.plot(distance, wt_profile, color=color, lw=1,
                label=f"{label} ({dates[tidx]:%Y-%m})")

    ax.fill_between(distance, wt_profile, dem_profile, color="saddlebrown", alpha=0.3, lw=0)
    ax.plot(distance, dem_profile, color="saddlebrown", lw=1.5)
    ax.fill_between(distance, 0, dem_profile - THICKNESS, color="lightgrey", alpha=0.5, lw=0)
    ax.plot(distance, dem_profile - THICKNESS, color="dimgray", lw=1)

    valid = np.isfinite(dem_profile)
    ax.set_xlim(distance[valid].min(), distance[valid].max())
    ax.set_ylim(np.nanmin(dem_profile) - THICKNESS - 5,
                np.nanmax(dem_profile) + 5)
    ax.set_xlabel("Distance [m]")
    ax.set_ylabel("Élévation [m]")
    ax.set_title(f"Sy = {sy}", fontsize=10)
    ax.legend(fontsize=8)

fig.tight_layout()
fig.savefig(fig_dir / "cross_section_comparison.png", bbox_inches="tight")
plt.close(fig)
print("[plot] cross_section_comparison.png")


# ---------------------------------------------------------------------
# 5. Débits : sim vs obs
# ---------------------------------------------------------------------
# Recharge : relue depuis le Zarr du run (`forcing/recharge/<station>`),
# mais non utilisée dans la figure pour rester simple.
#
# Débit observé : pas encore persisté dans le catalogue v0.5 pour un run
# hors `[observations]`/calibration. On lit donc le CSV d'origine.
# À remplacer par `sim.observations("discharge", "NANCON")` quand l'API
# sera disponible.

obs_csv = HERE.parent / "data/hydrometry/hydrometry_custom_NANCON_19820201_20220125_D.csv"
Q_obs = None
if obs_csv.exists():
    q_raw = pd.read_csv(obs_csv, index_col=0, parse_dates=True).squeeze()
    area_m2 = project.geographic.catch_area * 1e6
    Q_obs = (q_raw / area_m2 * 86400).resample("ME").sum() * 1000  # mm/mois
    Q_obs = Q_obs[(Q_obs.index.year >= 2000) & (Q_obs.index.year <= 2002)]

Q_sim = {}
for sy, run in runs.items():
    drain = rasters(run, "outflow_drain")
    drain[~np.isfinite(drain)] = 0.0
    q_daily = np.abs(drain * catchment_mask).sum(axis=(1, 2)) / catchment_area_m2 * 86400 * 1000
    Q_sim[sy] = pd.Series(q_daily * days_in_month, index=dates)  # mm/mois

pos = np.concatenate([q.values for q in Q_sim.values()] + ([Q_obs.values] if Q_obs is not None else []))
pos = pos[pos > 0]
y_min, y_max = float(pos.min()) * 0.5, float(pos.max()) * 2.0

fig, axes = plt.subplots(
    len(runs), 2, figsize=(12, 3.5 * len(runs)),
    gridspec_kw={"width_ratios": [3, 1]}, dpi=200,
)
axes = axes.reshape(len(runs), 2)

for row_axes, (sy, q_sim) in zip(axes, Q_sim.items()):
    ax_ts, ax_sc = row_axes

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
    else:
        ax_sc.text(0.5, 0.5, "pas d'obs", ha="center", va="center",
                   transform=ax_sc.transAxes, color="grey")

fig.tight_layout()
fig.savefig(fig_dir / "streamflow_comparison.png", bbox_inches="tight")
plt.close(fig)
print("[plot] streamflow_comparison.png")


# ---------------------------------------------------------------------
# 6. Densité de drainage (intermittent vs pérenne, par année)
# ---------------------------------------------------------------------

fig, axes = plt.subplots(len(runs), 1, figsize=(8, 3 * len(runs)), dpi=200)
axes = np.atleast_1d(axes)

for ax, (sy, intermittent) in zip(axes, drainage_density.items()):
    # Pérenne = cellules actives tous les pas d'une même année. Métrique
    # dérivée temporellement, gardée côté script (pas d'agrégation
    # année-aware dans le pipeline pour l'instant).
    accflux_stack = accumulation_flux[sy]
    active = (accflux_stack > 0) & catchment_mask
    perennial = np.zeros(n_periods)
    for year in sorted({d.year for d in dates}):
        year_ts = [t for t, d in enumerate(dates) if d.year == year]
        always_active = active[year_ts].all(axis=0)
        perennial[year_ts] = 100.0 * (always_active & catchment_mask).sum() / n_active_cells

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
print("[plot] drainage_density_comparison.png")


# ---------------------------------------------------------------------
# 7. Cartes de saturation (min/max) — overlay contour vectoriel
# ---------------------------------------------------------------------

fig, axes = plt.subplots(len(runs), 2, figsize=(8, 4 * len(runs)), dpi=200)
axes = axes.reshape(len(runs), 2)

for row_axes, (sy, run) in zip(axes, runs.items()):
    density = saturated_fraction[sy]
    t_min, t_max = int(density.argmin()), int(density.argmax())

    for ax, (tidx, label) in zip(row_axes, [(t_min, "Min"), (t_max, "Max")]):
        flux = accumulation_flux[sy][tidx]
        ax.set_title(
            f"Sy={sy}  {label} ({dates[tidx]:%Y-%m})  Asat={density[tidx]:.1f}%",
            fontsize=9,
        )
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
print("[plot] saturation_maps_comparison.png")


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
print("[plot] persistency_comparison.png")


# ---------------------------------------------------------------------
project.close()
print(f"\nFini. Figures dans {fig_dir}")
for sy, run in runs.items():
    print(f"  Sy={sy}: {run.name}  (sim_id={run.sim_id[:8]}…)")
