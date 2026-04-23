"""Example 01 - Canut catchment, steady-state with hmp.Simulation API.

Runs MODFLOW-NWT in steady state and produces cross-section,
streamflow statistics, and recharge plots.

    python run_steady_prototype.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

import hydromodpy as hmp

project = hmp.Project(Path(__file__).parent / "project.toml")
print(f"Catchment area: {project.geographic.catch_area:.1f} km2")

r = project.run(name="canut_steady")
print(f"Run completed: {r.name}")

catalog = project.store
sz = catalog.open_zarr(r.sim_id)

fig_dir = Path(__file__).parent / "figures"
fig_dir.mkdir(parents=True, exist_ok=True)

# Cross-section (centre row)
try:
    dem_data, dem_meta = sz.read_geographic_raster("watershed_dem")
    dem_data = dem_data.astype(float)
    dem_data[dem_data < 0] = np.nan
    cell_size = abs(float(dem_meta["transform"][0]))

    wt = r.field("watertable_elevation", timestep=0)
    grid_shape = dem_data.shape
    wt = wt.reshape(grid_shape)
    wt[wt < 0] = np.nan

    row = grid_shape[0] // 2
    x_dist = np.arange(grid_shape[1]) * cell_size
    dem_profile = dem_data[row, :]
    wt_profile = wt[row, :]
    thickness = 20.0

    fig, ax = plt.subplots(figsize=(6, 4), dpi=200)
    ax.fill_between(
        x_dist, dem_profile - thickness, wt_profile, color="dodgerblue", alpha=0.4, lw=0
    )
    ax.plot(x_dist, wt_profile, color="navy", lw=1.5, label="Water table")
    ax.fill_between(x_dist, wt_profile, dem_profile, color="saddlebrown", alpha=0.3, lw=0)
    ax.plot(x_dist, dem_profile, color="saddlebrown", lw=1.5, label="Topography")
    ax.fill_between(x_dist, 0, dem_profile - thickness, color="lightgrey", alpha=0.5, lw=0)
    ax.plot(x_dist, dem_profile - thickness, color="dimgray", lw=1)
    valid = np.isfinite(dem_profile)
    ax.set_xlim(x_dist[valid].min(), x_dist[valid].max())
    ax.set_ylim(np.nanmin(dem_profile) - thickness - 5, np.nanmax(dem_profile) + 5)
    ax.set_xlabel("Distance [m]")
    ax.set_ylabel("Elevation [m]")
    ax.set_title("Canut - steady-state cross section")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(fig_dir / "cross_section_steady.png", bbox_inches="tight")
    plt.close(fig)
    print("[plot] cross_section_steady.png")
except Exception as e:
    print(f"[skip] cross-section: {e}")

# Streamflow statistics from observed data
data_path = project.store.workspace_path / "data"
qobs_file = data_path / "hydrometry catchment Canut.csv"
if qobs_file.exists():
    try:
        Qobs = pd.read_csv(qobs_file, sep=";", index_col=0, parse_dates=True).squeeze()
        Qobs = Qobs.rename("Q")
        area_km2 = project.geographic.catch_area
        Qobs = (Qobs / (area_km2 * 1e6)) * 86400 * 1000  # m3/s -> mm/d

        first, last = 1990, 2019
        Qobs = Qobs[(Qobs.index.year >= first) & (Qobs.index.year <= last)]

        grouped = Qobs.groupby([Qobs.index.month, Qobs.index.day])
        mean_interan = grouped.mean().to_frame()
        mean_interan["q10"] = grouped.quantile(0.10).values
        mean_interan["q50"] = grouped.quantile(0.50).values
        mean_interan["q90"] = grouped.quantile(0.90).values
        mean_interan.index.names = ["months", "days"]
        mean_interan = mean_interan.reset_index().sort_values(["months", "days"])
        mean_interan["counts"] = np.arange(1, len(mean_interan) + 1)

        fig, ax = plt.subplots(figsize=(6, 4))
        ax.plot(mean_interan.counts, mean_interan.q50, lw=2, color="darkred", label="Median")
        ax.fill_between(
            mean_interan.counts,
            mean_interan.q10,
            mean_interan.q90,
            color="cyan",
            edgecolor="grey",
            lw=0.5,
            alpha=0.5,
            label="10-90th",
        )
        ax.set_yscale("log")
        ax.set_xlim(0, 366)
        ax.set_ylim(0.01, 10)
        months_ticks = np.linspace(0, 366, 13)
        ax.set_xticks(months_ticks)
        ax.set_xticklabels(["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D", "J"])
        ax.set_xlabel("Months")
        ax.set_ylabel("Q / A [mm/d]")
        ax.set_title(f"Canut [{first} to {last}]")
        ax.grid(alpha=0.25)
        ax.legend(loc="lower left")
        fig.tight_layout()
        fig.savefig(fig_dir / "streamflow_interannual.png", dpi=300, bbox_inches="tight")
        plt.close(fig)
        print("[plot] streamflow_interannual.png")
    except Exception as e:
        print(f"[skip] streamflow: {e}")
else:
    print(f"[skip] streamflow: {qobs_file} not found")

project.close()
print(f"\nDone. Figures in {fig_dir}")
