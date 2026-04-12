# -*- coding: utf-8 -*-
"""Example 04 - Nancon catchment, transient Sy sensitivity.

Run MODFLOW-NWT for 3 specific yield values and compare results.
Demonstrates the Project API: setup once, run many.

Usage:
    python run_transient_prototype.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.colors import ListedColormap

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import hydromodpy as hmp


# =====================================================================
# Parameters
# =====================================================================

SY_VALUES = [0.001, 0.05, 0.30]
HK = 5e-5       # m/s
SS = 1e-5        # m-1
THICKNESS = 30   # m


# =====================================================================
# Project setup (geographic + domain + data loaded once)
# =====================================================================

project = hmp.Project(Path(__file__).parent / "project.toml")
print(f"Catchment area: {project.geographic.catch_area:.1f} km2")


# =====================================================================
# Run loop
# =====================================================================

results = {}
for i, sy in enumerate(SY_VALUES):
    name = f"nancon_sy_{sy:.4f}"
    print(f"\n{'='*60}\n  Run {i+1}/{len(SY_VALUES)}: Sy = {sy}  ({name})\n{'='*60}")
    try:
        r = project.run(Sy=sy, K=HK, Ss=SS, name=name)
        results[sy] = r
        print("  [OK] converged")
    except Exception as e:
        print(f"  [FAILED] {e}")

print(f"\n{len(results)}/{len(SY_VALUES)} runs converged.")
if not results:
    sys.exit(1)


# =====================================================================
# Figure helpers
# =====================================================================

store = project.store
dem_data = store.read_geographic_raster("watershed_dem").astype(float)
dem_meta = store.read_geographic_raster_metadata("watershed_dem")
dem_data[dem_data < 0] = np.nan

cell_size = abs(float(dem_meta["transform"][0]))
grid_shape = dem_data.shape
ws_mask = np.isfinite(dem_data) & (dem_data > 0)
active_cells = int(np.sum(ws_mask))
catchment_area_m2 = float(active_cells) * cell_size ** 2

nper = project.time_grid.nper
dates = pd.date_range(start="2000-01-01", end="2002-12-31", freq="ME")
days_in_month = np.array([d.day for d in dates])

fig_dir = Path(__file__).parent / "figures"
fig_dir.mkdir(parents=True, exist_ok=True)


def drainage_density(r, n):
    """Drainage density (%) per timestep."""
    d = np.zeros(n)
    for t in range(n):
        seepage = r.field("seepage_areas", t).reshape(grid_shape)
        d[t] = 100.0 * int(np.sum((seepage > 0) & ws_mask)) / active_cells
    return d


def load_accflux(r, n):
    """Load routed accumulation_flux per timestep."""
    return {t: r.field("accumulation_flux", t).reshape(grid_shape) for t in range(n)}


# Pre-compute
all_density = {sy: drainage_density(r, nper) for sy, r in results.items()}
all_accflux = {sy: load_accflux(r, nper) for sy, r in results.items()}


# =====================================================================
# 1. Cross section
# =====================================================================

fig, axes = plt.subplots(len(results), 1, figsize=(7, 3.5 * len(results)), dpi=200)
if len(results) == 1:
    axes = [axes]

for idx, (sy, r) in enumerate(results.items()):
    ax = axes[idx]
    density = all_density[sy]
    idx_min, idx_max = int(np.argmin(density)), int(np.argmax(density))
    row = grid_shape[0] // 2
    dem_profile = dem_data[row, :].copy()
    x_dist = np.arange(dem_profile.size) * cell_size

    for label, tidx, color in [("Min", idx_min, "navy"), ("Max", idx_max, "dodgerblue")]:
        wt = r.field("watertable_elevation", tidx).reshape(grid_shape)
        wt[wt < 0] = np.nan
        wt_profile = wt[row, :]
        ax.fill_between(x_dist, dem_profile - THICKNESS, wt_profile, color=color, alpha=0.4, lw=0)
        ax.plot(x_dist, wt_profile, color=color, lw=1, label=f"{label} ({str(dates[tidx])[:7]})")

    ax.fill_between(x_dist, wt_profile, dem_profile, color="saddlebrown", alpha=0.3, lw=0)
    ax.plot(x_dist, dem_profile, color="saddlebrown", lw=1.5)
    ax.fill_between(x_dist, 0, dem_profile - THICKNESS, color="lightgrey", alpha=0.5, lw=0)
    ax.plot(x_dist, dem_profile - THICKNESS, color="dimgray", lw=1)
    ax.set_xlim(x_dist[np.isfinite(dem_profile)].min(), x_dist[np.isfinite(dem_profile)].max())
    ax.set_ylim(np.nanmin(dem_profile) - THICKNESS - 5, np.nanmax(dem_profile) + 5)
    ax.set_xlabel("Distance [m]")
    ax.set_ylabel("Elevation [m]")
    ax.set_title(f"Sy = {sy}", fontsize=10)
    ax.legend(fontsize=8)

fig.tight_layout()
fig.savefig(fig_dir / "cross_section_comparison.png", bbox_inches="tight")
plt.close(fig)
print("[plot] cross_section_comparison.png")


# =====================================================================
# 2. Streamflow
# =====================================================================

data_root = Path(__file__).parent.parent.parent / "data"

runoff_mm_day = None
runoff_candidates = list(data_root.glob("runoff/*EX04*.csv"))
if runoff_candidates:
    runoff_mm_day = pd.read_csv(runoff_candidates[0], index_col=0, parse_dates=True)["value"]

Qobs = None
qobs_candidates = list(data_root.glob("hydrometry/*NANCON*.csv"))
if qobs_candidates:
    Qobs_raw = pd.read_csv(qobs_candidates[0], index_col=0, parse_dates=True).squeeze()
    area_m2 = project.geographic.catch_area * 1e6
    Qobs = Qobs_raw / area_m2 * 86400
    Qobs = Qobs.resample("ME").sum() * 1000
    Qobs = Qobs[(Qobs.index.year >= 2000) & (Qobs.index.year <= 2002)]

all_qmod = {}
for sy, r in results.items():
    q = []
    for t in range(nper):
        drain = r.field("outflow_drain", t).reshape(grid_shape)
        drain[~np.isfinite(drain)] = 0.0
        q.append(float(np.sum(np.abs(drain[ws_mask]))) / catchment_area_m2 * 86400 * 1000)
    drain_mm_day = pd.Series(q, index=dates)
    if runoff_mm_day is not None:
        drain_mm_day += runoff_mm_day.reindex(dates, method="nearest").fillna(0).values
    all_qmod[sy] = drain_mm_day * days_in_month

all_values = np.concatenate([q.values for q in all_qmod.values()])
if Qobs is not None:
    all_values = np.concatenate([all_values, Qobs.values])
all_values = all_values[all_values > 0]
y_min, y_max = float(np.min(all_values)) * 0.5, float(np.max(all_values)) * 2.0

fig, axes = plt.subplots(len(results), 2, figsize=(12, 3.5 * len(results)),
                         gridspec_kw={"width_ratios": [3, 1]}, dpi=200)
if len(results) == 1:
    axes = axes.reshape(1, -1)

for idx, (sy, _) in enumerate(results.items()):
    Qmod = all_qmod[sy]
    ax = axes[idx, 0]
    if Qobs is not None:
        ax.plot(Qobs, color="k", lw=2, label="Observed")
    ax.plot(Qmod, color="red", lw=2, label="Simulated")
    ax.set_ylabel("Q/A [mm/month]")
    ax.set_yscale("log")
    ax.set_ylim(y_min, y_max)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.set_xlim(pd.Timestamp("1999"), pd.Timestamp("2004"))
    ax.legend(fontsize=8)
    ax.set_title(f"Sy = {sy}", fontsize=10)

    ax = axes[idx, 1]
    if Qobs is not None:
        Qmod_aligned = Qmod.reindex(Qobs.index, method="nearest")
        ax.scatter(Qobs, Qmod_aligned, s=20, alpha=0.7, color="forestgreen", edgecolor="none")
        ax.plot([max(1, y_min), y_max], [max(1, y_min), y_max], color="grey", zorder=-1)
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_xlim(max(1, y_min), y_max); ax.set_ylim(max(1, y_min), y_max)
        ax.set_xlabel("Obs [mm/month]"); ax.set_ylabel("Sim [mm/month]")

fig.tight_layout()
fig.savefig(fig_dir / "streamflow_comparison.png", bbox_inches="tight")
plt.close(fig)
print("[plot] streamflow_comparison.png")


# =====================================================================
# 3. Drainage density
# =====================================================================

fig, axes = plt.subplots(len(results), 1, figsize=(8, 3 * len(results)), dpi=200)
if len(results) == 1:
    axes = [axes]

for idx, (sy, _) in enumerate(results.items()):
    ax = axes[idx]
    accflux = all_accflux[sy]

    total = np.array([100.0 * int(np.sum((accflux[t] > 0) & ws_mask)) / active_cells for t in range(nper)])
    perennial = np.zeros(nper)
    for year in sorted(set(d.year for d in dates)):
        yi = [t for t, d in enumerate(dates) if d.year == year]
        mask_p = np.ones(grid_shape, dtype=bool)
        for t in yi:
            mask_p &= (accflux[t] > 0)
        pct = 100.0 * int(np.sum(mask_p & ws_mask)) / active_cells
        for t in yi:
            perennial[t] = pct

    ax.fill_between(dates, 0, total, step="pre", color="dodgerblue", alpha=0.5, label="Intermittent")
    ax.fill_between(dates, 0, perennial, step="pre", color="navy", alpha=0.5, label="Perennial")
    ax.set_ylabel("Drainage density [%]")
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


# =====================================================================
# 4. Saturation maps
# =====================================================================

contour = None
try:
    contour = store.read_geographic_raster("watershed_contour")
    contour = np.ma.masked_where(contour <= 0, contour)
except KeyError:
    pass

mask = dem_data.copy()
fig, axes = plt.subplots(len(results), 2, figsize=(8, 4 * len(results)), dpi=200)
if len(results) == 1:
    axes = axes.reshape(1, -1)

for idx, (sy, r) in enumerate(results.items()):
    density = all_density[sy]
    idx_min, idx_max = int(np.argmin(density)), int(np.argmax(density))
    for k, (tidx, label) in enumerate([(idx_min, "Min"), (idx_max, "Max")]):
        ax = axes[idx, k]
        flux = all_accflux[sy][tidx]
        ax.set_title(f"Sy={sy} {label} ({str(dates[tidx])[:7]}) - Asat={density[tidx]:.1f}%", fontsize=9)
        ax.imshow(np.ma.masked_where(np.isnan(mask), mask), cmap="Greys", alpha=0.5, zorder=0)
        ax.imshow(np.ma.masked_where((flux <= 0) | np.isnan(mask), flux), cmap=ListedColormap(["navy"]), zorder=1)
        if contour is not None:
            ax.imshow(contour, cmap="Greys_r", zorder=2)
        ax.axis("off")

fig.tight_layout()
fig.savefig(fig_dir / "saturation_maps_comparison.png", bbox_inches="tight")
plt.close(fig)
print("[plot] saturation_maps_comparison.png")


# =====================================================================
# 5. Persistency index
# =====================================================================

fig, axes = plt.subplots(1, len(results), figsize=(4 * len(results), 5), dpi=200)
if len(results) == 1:
    axes = [axes]

for idx, (sy, _) in enumerate(results.items()):
    ax = axes[idx]
    accflux = all_accflux[sy]
    n_active = np.zeros(grid_shape)
    for t in range(nper):
        n_active += (accflux[t] > 0).astype(float)
    pi = np.ma.masked_where((n_active <= 0) | np.isnan(mask), n_active / nper)
    im = ax.imshow(pi, cmap="jet", vmin=0, vmax=1)
    if contour is not None:
        ax.imshow(contour, cmap="Greys_r")
    ax.set_title(f"Sy = {sy}", fontsize=10)
    ax.axis("off")

cbar_ax = fig.add_axes([0.25, 0.05, 0.5, 0.02])
fig.colorbar(im, cax=cbar_ax, orientation="horizontal", label="Persistency index [-]")
fig.tight_layout(rect=[0, 0.08, 1, 1])
fig.savefig(fig_dir / "persistency_comparison.png", bbox_inches="tight")
plt.close(fig)
print("[plot] persistency_comparison.png")

project.close()
print(f"\nDone. Figures saved in: {fig_dir}")
for sy, r in results.items():
    print(f"  Sy={sy}: {r.name}")
