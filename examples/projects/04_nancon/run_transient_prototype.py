# -*- coding: utf-8 -*-
"""Example 04 - Nancon catchment, transient prototype.

Prototype mode: build objects from the TOML, run MODFLOW-NWT and MODPATH
for 3 different Sy values, compare results.

This script shows how to use HydroModPy without the launcher.

Usage:
    python run_transient_prototype.py
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import hydromodpy as hmp
from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.data import DataManagersPlanner, DataManagersRuntimeLoader
from hydromodpy.spatial.domain import Domain
from hydromodpy.spatial.geographic.structure_binders import (
    apply_catchment_zones_to_domain,
    apply_geology_to_domain,
)
from hydromodpy.process.flow import Flow
from hydromodpy.process.flow.structure_binders import apply_recharge_load_result_to_flow
from hydromodpy.process.transport import Transport
from hydromodpy.core.state.run_state import LauncherRunState
from hydromodpy.core.time import (
    ResolvedSimulationTimeGrid,
    ResolvedSimulationTimeWindow,
    build_simulation_time_boundaries,
)
from hydromodpy.solver.modflow_nwt import (
    Modflow,
    ModflowPreprocessOptions,
    ModflowRunOptions,
    Modpath,
)
from hydromodpy.results.store import ResultStore
from hydromodpy.simulation.results.post_run import post_run_results
from hydromodpy.results.config import BudgetConfig, DerivedConfig, ExportConfig, ResultsConfig
from hydromodpy.spatial.geographic.store_ingestion import persist_geographic_to_store


# =====================================================================
# Config
# =====================================================================

config_path = Path(__file__).parent / "project.toml"
cfg = HydroModPyConfig.from_toml(config_path)

with config_path.open("rb") as fh:
    raw_toml = tomllib.load(fh)


# =====================================================================
# Calibration parameters
# =====================================================================

# Sy values to explore (loop)
SY_VALUES = [0.001, 0.05, 0.30]

# Fixed parameters (read from TOML, can be overridden here)
HK = 5e-5       # m/s
SS = 1e-5       # m-1
THICKNESS = 30  # m
FIRST_CLIM = "first"

# Simulation period
START = "2000-01-01"
END = "2002-12-31"
STEP = "1 month"


# =====================================================================
# 1. Build workspace and geographic objects
# =====================================================================

ws = hmp.Workspace(config=cfg.workspace)
geographic = hmp.Geographic(cfg.geographic, ws)
geo_features = geographic.get_geographic_derived_features()
surface_topo = geo_features.surface_topo

print(f"Catchment area: {geographic.catch_area:.1f} km2")

# Ingest geographic data into the project store
store = ResultStore(ws.project_root)
persist_geographic_to_store(geographic, store)
store.close()


# =====================================================================
# 2. Build domain
# =====================================================================

domain_cfg = cfg.domain.model_copy(deep=True)
if "catchment" not in [z.lower() for z in domain_cfg.zone_ids]:
    domain_cfg.zone_ids.append("catchment")
domain = Domain(config=domain_cfg, surface_topo=surface_topo)
apply_catchment_zones_to_domain(
    domain=domain,
    geographic=geo_features.to_domain_geographic_context(),
)


# =====================================================================
# 3. Load data (geology, hydrography, recharge, etc.)
# =====================================================================

data_plan = DataManagersPlanner().build(
    cfg.data,
    domain_zone_ids=cfg.domain.zone_ids,
    raw_toml=raw_toml,
    flow_active_bc=cfg.flow.active_bc,
)
cfg.data = cfg.data.with_resolved_types(data_plan.types)

run_state = LauncherRunState(
    cfg=cfg,
    config_path=config_path.resolve(),
    raw_toml=raw_toml,
)
run_state.data_plan = data_plan
run_state.setup.workspace = ws
run_state.setup.geographic = geographic
run_state.setup.geographic_features = geo_features
run_state.setup.domain = domain

loader = DataManagersRuntimeLoader(
    config_path=config_path.resolve(),
    data_plan=data_plan,
)
loader.load_all(run_state)
loaded_data = run_state.loaded_data
apply_geology_to_domain(domain=domain, geology=loaded_data.geology)


# =====================================================================
# 4. Build time grid (monthly, 2000-2002)
# =====================================================================

window = ResolvedSimulationTimeWindow(
    start=pd.Timestamp(START),
    end=pd.Timestamp(END),
    step_value=1,
    step_unit="month",
    coverage_policy="warn",
)
boundaries = build_simulation_time_boundaries(window)
perlen_sec = tuple(
    (boundaries[i + 1] - boundaries[i]).total_seconds()
    for i in range(len(boundaries) - 1)
)
time_grid = ResolvedSimulationTimeGrid(
    window=window,
    boundaries=tuple(boundaries),
    period_lengths_seconds=perlen_sec,
)

dates = pd.date_range(start=START, end=END, freq="ME")
nper = len(perlen_sec)
print(f"Time grid: {nper} stress periods ({START} to {END})")


# =====================================================================
# 5. Run loop: MODFLOW + MODPATH for each Sy value
# =====================================================================

results = {}  # {sy_value: {"name": ..., "sim_id": ..., "success": ...}}

for i, sy in enumerate(SY_VALUES):
    model_name = f"nancon_sy_{sy:.4f}"
    sim_id = str(uuid4())

    print("\n" + "=" * 60)
    print(f"  Run {i+1}/{len(SY_VALUES)}: Sy = {sy}")
    print(f"  Model: {model_name}")
    print("=" * 60)

    # -- Build Flow with current Sy --
    flow = Flow(config=cfg.flow)
    flow.parameters["K"].value = HK
    flow.parameters["Sy"].value = sy
    flow.parameters["Ss"].value = SS

    # -- Apply recharge from data managers --
    apply_recharge_load_result_to_flow(
        flow=flow,
        recharge_result=loaded_data.recharge,
        simulation_window=window,
    )

    # -- Build transport --
    transport = Transport(config=cfg.transport)

    # -- MODFLOW-NWT --
    model_modflow = Modflow(
        geographic,
        modflow_config=cfg.modflownwt,
        model_folder=str(ws.solver_scratch_folder),
        model_name=model_name,
        bin_path=str(ws.bin_path),
    )

    model_modflow.pre_processing(
        flow=flow,
        domain=domain,
        options=ModflowPreprocessOptions(
            box=True,
            sink_fill=False,
            check_grid=True,
            time_grid=time_grid,
        ),
    )

    success = model_modflow.processing(
        options=ModflowRunOptions(
            write_model=True,
            run_model=True,
            link_mt3dms=False,
            verbose=False,
        ),
    )

    if not success:
        print(f"  [FAILED] MODFLOW did not converge for Sy={sy}")
        results[sy] = {"name": model_name, "sim_id": sim_id, "success": False}
        continue

    print(f"  [OK] MODFLOW converged")

    # -- MODPATH backward tracking (must run before store ingestion
    #    because it needs the .hds file on disk) --
    # TODO: uncomment when MODPATH is needed
    # solver_dir_mp = Path(model_modflow.full_path)
    # model_modpath = Modpath(
    #     domain,
    #     transport,
    #     model_modflow=model_modflow,
    #     model_folder=str(solver_dir_mp.parent),
    #     model_name=model_name,
    #     bin_path=str(ws.bin_path),
    # )
    # model_modpath.pre_processing()
    # model_modpath.processing(write_model=True, run_model=True)
    # model_modpath.post_processing(
    #     model_modpath,
    #     ending_point=True,
    #     starting_point=True,
    #     pathlines_shp=True,
    #     particles_shp=True,
    # )
    # model_modpath.filt_processing(
    #     model_modpath,
    #     norm_flux=True,
    #     filt_time=True,
    #     filt_seep=True,
    #     filt_inout=True,
    #     calc_rtd=False,
    # )

    # -- Ingest into ResultStore --
    solver_dir = Path(model_modflow.full_path)
    store = ResultStore(ws.project_root)
    try:
        store.register_simulation(
            sim_id=sim_id,
            name=model_name,
            solver="modflownwt",
            n_timesteps=nper,
        )
        results_cfg = ResultsConfig(
            keep_solver_files=True,
            budget=BudgetConfig(spatial_fields=True),
            derived=DerivedConfig(
                accumulation_flux=True,
                outflow_drain=True,
            ),
            export=ExportConfig(netcdf=False, csv_timeseries=False),
        )
        post_run_results(
            sim_id=sim_id,
            solver_name="modflownwt",
            solver_output_dir=solver_dir,
            results_config=results_cfg,
            store=store,
            keep_solver_files=True,
        )
        store.finalize(sim_id, status="completed")
    finally:
        store.close()

    results[sy] = {
        "name": model_name,
        "sim_id": sim_id,
        "success": True,
        "model": model_modflow,
    }
    print(f"  [OK] Results ingested")


# Keep only successful runs
successful = {sy: r for sy, r in results.items() if r["success"]}
print(f"\n{len(successful)}/{len(SY_VALUES)} runs converged.")

if not successful:
    print("No successful runs. Exiting.")
    sys.exit(1)


# =====================================================================
# 6. Figures - setup
# =====================================================================

fig_dir = Path(__file__).parent / "figures"
fig_dir.mkdir(parents=True, exist_ok=True)

# Open store for all figures — geographic data + simulation fields
store = ResultStore(ws.project_root)

# Load DEM and watershed mask from store
dem_data = store.read_geographic_raster("watershed_dem").astype(float)
dem_meta = store.read_geographic_raster_metadata("watershed_dem")
dem_data[dem_data < 0] = np.nan

cell_size = abs(float(dem_meta["transform"][0]))
grid_shape = dem_data.shape
ws_mask = np.isfinite(dem_data) & (dem_data > 0)
active_cells = int(np.sum(ws_mask))
catchment_area_m2 = float(active_cells) * cell_size ** 2
days_in_month = np.array([d.day for d in dates])


# =====================================================================
# Helper: drainage density from store
# =====================================================================

def compute_drainage_density(sim_id, n_timesteps):
    """Drainage density (%) per timestep from seepage_areas (virtual field)."""
    if active_cells == 0:
        return np.zeros(n_timesteps)
    density = np.zeros(n_timesteps)
    for t in range(n_timesteps):
        seepage = store.query_field(sim_id, "seepage_areas", t).reshape(grid_shape)
        wet = int(np.sum((seepage > 0) & ws_mask))
        density[t] = 100.0 * wet / active_cells
    return density


def load_accumulation_flux(sim_id, n_timesteps):
    """Load pre-computed D8-routed accumulation_flux from store."""
    result = {}
    for t in range(n_timesteps):
        acc = store.query_field(sim_id, "accumulation_flux", t).reshape(grid_shape)
        result[t] = acc
    return result


# Pre-compute drainage density (used by cross-section, drainage, saturation)
all_density = {}
for sy, info in successful.items():
    all_density[sy] = compute_drainage_density(info["sim_id"], nper)

# Load routed accumulation_flux from store (computed during derive phase)
all_accflux = {}
for sy, info in successful.items():
    all_accflux[sy] = load_accumulation_flux(info["sim_id"], nper)


# =====================================================================
# 7. Cross section: min and max saturation
# =====================================================================

fig, axes = plt.subplots(len(successful), 1, figsize=(7, 3.5 * len(successful)), dpi=200)
if len(successful) == 1:
    axes = [axes]

for idx, (sy, info) in enumerate(successful.items()):
    ax = axes[idx]
    sim_id = info["sim_id"]
    density = all_density[sy]

    idx_min = int(np.argmin(density))
    idx_max = int(np.argmax(density))

    row = grid_shape[0] // 2
    dem_profile = dem_data[row, :].copy()
    x_dist = np.arange(dem_profile.size) * cell_size

    for k, (label, tidx, color) in enumerate([
        ("Min", idx_min, "navy"),
        ("Max", idx_max, "dodgerblue"),
    ]):
        wt = store.query_field(sim_id, "watertable_elevation", tidx).reshape(grid_shape)
        wt[wt < 0] = np.nan
        wt_profile = wt[row, :]

        ax.fill_between(x_dist, dem_profile - THICKNESS, wt_profile,
                        color=color, alpha=0.4, lw=0)
        ax.plot(x_dist, wt_profile, color=color, lw=1,
                label=f"{label} ({str(dates[tidx])[:7]})")

    # Topography and bedrock
    ax.fill_between(x_dist, wt_profile, dem_profile,
                    color="saddlebrown", alpha=0.3, lw=0)
    ax.plot(x_dist, dem_profile, color="saddlebrown", lw=1.5)
    ax.fill_between(x_dist, 0, dem_profile - THICKNESS,
                    color="lightgrey", alpha=0.5, lw=0)
    ax.plot(x_dist, dem_profile - THICKNESS, color="dimgray", lw=1)

    ax.set_xlim(x_dist[np.isfinite(dem_profile)].min(),
                x_dist[np.isfinite(dem_profile)].max())
    ax.set_ylim(np.nanmin(dem_profile) - THICKNESS - 5,
                np.nanmax(dem_profile) + 5)
    ax.set_xlabel("Distance [m]")
    ax.set_ylabel("Elevation [m]")
    ax.set_title(f"Sy = {sy}", fontsize=10)
    ax.legend(fontsize=8)

fig.tight_layout()
fig.savefig(fig_dir / "cross_section_comparison.png", bbox_inches="tight")
plt.close(fig)
print("[plot] cross_section_comparison.png")


# =====================================================================
# 8. Streamflow: observed vs simulated
# =====================================================================

# Load runoff series (mm/day, added to drain to get total streamflow)
data_root = Path(__file__).parent.parent.parent / "data"
runoff_candidates = list(data_root.glob("runoff/*EX04*.csv"))
runoff_mm_day = None
if runoff_candidates:
    runoff_df = pd.read_csv(runoff_candidates[0], index_col=0, parse_dates=True)
    runoff_mm_day = runoff_df["value"]  # mm/day

# Load observed streamflow
qobs_candidates = list(data_root.glob("hydrometry/*NANCON*.csv"))
Qobs = None
if qobs_candidates:
    Qobs_raw = pd.read_csv(qobs_candidates[0], index_col=0, parse_dates=True)
    Qobs_raw = Qobs_raw.squeeze()
    area_m2 = geographic.catch_area * 1e6
    # m3/s to mm/month
    Qobs = Qobs_raw / area_m2 * 86400  # m3/s -> m/day
    Qobs = Qobs.resample("ME").sum() * 1000  # m/day -> mm/month
    Qobs = Qobs[(Qobs.index.year >= 2000) & (Qobs.index.year <= 2002)]

# Pre-compute all Qmod series to find global min/max
all_qmod = {}
for sy, info in successful.items():
    sim_id = info["sim_id"]
    q_values = []
    for t in range(nper):
        drain = store.query_field(sim_id, "outflow_drain", t).reshape(grid_shape)
        drain[~np.isfinite(drain)] = 0.0
        # Drain flux is negative in MODFLOW (outflow convention) → abs
        masked_sum = float(np.sum(np.abs(drain[ws_mask])))
        q_mm_day = masked_sum / catchment_area_m2 * 86400 * 1000
        q_values.append(q_mm_day)
    drain_mm_day = pd.Series(q_values, index=dates)
    if runoff_mm_day is not None:
        r_aligned = runoff_mm_day.reindex(dates, method="nearest").fillna(0)
        total_mm_day = drain_mm_day + r_aligned.values
    else:
        total_mm_day = drain_mm_day
    all_qmod[sy] = total_mm_day * days_in_month

# Global y-limits from all data
all_values = np.concatenate([q.values for q in all_qmod.values()])
if Qobs is not None:
    all_values = np.concatenate([all_values, Qobs.values])
all_values = all_values[all_values > 0]
y_min = float(np.min(all_values)) * 0.5
y_max = float(np.max(all_values)) * 2.0
scatter_min = max(1, y_min)
scatter_max = y_max

fig, axes = plt.subplots(len(successful), 2, figsize=(12, 3.5 * len(successful)),
                         gridspec_kw={"width_ratios": [3, 1]}, dpi=200)
if len(successful) == 1:
    axes = axes.reshape(1, -1)

for idx, (sy, info) in enumerate(successful.items()):
    Qmod = all_qmod[sy]

    # Time series
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

    # Scatter
    ax = axes[idx, 1]
    if Qobs is not None:
        Qmod_aligned = Qmod.reindex(Qobs.index, method="nearest")
        ax.scatter(Qobs, Qmod_aligned, s=20, alpha=0.7, color="forestgreen", edgecolor="none")
        ax.plot([scatter_min, scatter_max], [scatter_min, scatter_max], color="grey", zorder=-1)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlim(scatter_min, scatter_max)
        ax.set_ylim(scatter_min, scatter_max)
        ax.set_xlabel("Obs [mm/month]")
        ax.set_ylabel("Sim [mm/month]")

fig.tight_layout()
fig.savefig(fig_dir / "streamflow_comparison.png", bbox_inches="tight")
plt.close(fig)
print("[plot] streamflow_comparison.png")


# =====================================================================
# 9. Drainage density time series
# =====================================================================

fig, axes = plt.subplots(len(successful), 1, figsize=(8, 3 * len(successful)), dpi=200)
if len(successful) == 1:
    axes = [axes]

for idx, (sy, info) in enumerate(successful.items()):
    ax = axes[idx]
    accflux = all_accflux[sy]

    # Total drainage density from routed accumulation_flux
    total_areas = np.zeros(nper)
    for t in range(nper):
        total_areas[t] = 100.0 * int(np.sum((accflux[t] > 0) & ws_mask)) / active_cells

    # Perennial part per year: cells with routed accflux > 0 for ALL months of each year
    perennial_areas = np.zeros(nper)
    for year in sorted(set(d.year for d in dates)):
        year_idx = [t for t, d in enumerate(dates) if d.year == year]
        perennial = np.ones(grid_shape, dtype=bool)
        for t in year_idx:
            perennial &= (accflux[t] > 0)
        pct = 100.0 * int(np.sum(perennial & ws_mask)) / active_cells
        for t in year_idx:
            perennial_areas[t] = pct

    ax.fill_between(dates, 0, total_areas, step="pre",
                    color="dodgerblue", alpha=0.5, label="Intermittent part")
    ax.fill_between(dates, 0, perennial_areas, step="pre",
                    color="navy", alpha=0.5, label="Perennial part")
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
# 10. Saturation maps (min and max for each Sy)
# =====================================================================

# Watershed contour from store (raster for overlay on imshow maps)
contour = None
try:
    contour = store.read_geographic_raster("watershed_contour")
    contour = np.ma.masked_where(contour <= 0, contour)
except KeyError:
    pass

# Watershed polygon for vector-based figures (GeoDataFrame)
watershed_gdf = None
try:
    watershed_gdf = store.read_features("watershed")
except KeyError:
    pass

mask = dem_data.copy()

fig, axes = plt.subplots(len(successful), 2, figsize=(8, 4 * len(successful)), dpi=200)
if len(successful) == 1:
    axes = axes.reshape(1, -1)

for idx, (sy, info) in enumerate(successful.items()):
    sim_id = info["sim_id"]
    density = all_density[sy]
    idx_min = int(np.argmin(density))
    idx_max = int(np.argmax(density))

    for k, (tidx, label) in enumerate([(idx_min, "Min"), (idx_max, "Max")]):
        ax = axes[idx, k]
        flux = all_accflux[sy][tidx]

        ax.set_title(f"Sy={sy} {label} ({str(dates[tidx])[:7]}) - Asat={density[tidx]:.1f}%",
                     fontsize=9)

        from matplotlib.colors import ListedColormap
        ax.imshow(np.ma.masked_where(np.isnan(mask), mask),
                  cmap="Greys", alpha=0.5, zorder=0)
        ax.imshow(np.ma.masked_where((flux <= 0) | np.isnan(mask), flux),
                  cmap=ListedColormap(["navy"]), zorder=1)
        if contour is not None:
            ax.imshow(contour, cmap="Greys_r", zorder=2)

        ax.axis("off")

fig.tight_layout()
fig.savefig(fig_dir / "saturation_maps_comparison.png", bbox_inches="tight")
plt.close(fig)
print("[plot] saturation_maps_comparison.png")


# =====================================================================
# 11. Persistency index maps
# =====================================================================

fig, axes = plt.subplots(1, len(successful), figsize=(4 * len(successful), 5), dpi=200)
if len(successful) == 1:
    axes = [axes]

for idx, (sy, info) in enumerate(successful.items()):
    ax = axes[idx]
    sim_id = info["sim_id"]

    # Persistency: fraction of timesteps with routed accumulation > 0
    accflux = all_accflux[sy]
    n_active = np.zeros(grid_shape)
    for t in range(nper):
        n_active += (accflux[t] > 0).astype(float)
    pi = n_active / nper

    pi = np.ma.masked_where((pi <= 0) | np.isnan(mask), pi)

    im = ax.imshow(pi, cmap="jet", vmin=0, vmax=1)
    if contour is not None:
        ax.imshow(contour, cmap="Greys_r")
    ax.set_title(f"Sy = {sy}", fontsize=10)
    ax.axis("off")

cbar_ax = fig.add_axes([0.25, 0.05, 0.5, 0.02])
fig.colorbar(im, cax=cbar_ax, orientation="horizontal",
             label="Persistency index [-]")
fig.tight_layout(rect=[0, 0.08, 1, 1])
fig.savefig(fig_dir / "persistency_comparison.png", bbox_inches="tight")
plt.close(fig)
print("[plot] persistency_comparison.png")

store.close()

# Clean up results_stable/ — all data is in the project store.
from hydromodpy.spatial.geographic.store_ingestion import cleanup_stable_folder
cleanup_stable_folder(geographic)


# =====================================================================
# Done
# =====================================================================

print(f"\nDone. Figures saved in: {fig_dir}")
print(f"Simulation outputs in: {ws.solver_scratch_folder}")
for sy, info in successful.items():
    print(f"  Sy={sy}: {info['name']}")
