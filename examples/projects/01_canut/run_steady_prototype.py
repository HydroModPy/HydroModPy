# -*- coding: utf-8 -*-
"""Example 01 — Canut catchment (prototype / Python-first approach).

Les paramètres (flow, transport, solver) sont lus depuis le TOML.
Seule l'exécution (appel aux solveurs Modflow, Modpath) est pilotée
depuis ce script Python — pas de section [simulation] dans le TOML.

Le script montre aussi comment surcharger un paramètre depuis Python
avant de lancer la simulation.

Usage::

    python run_steady_prototype.py
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import imageio.v2 as imageio
import flopy

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import hydromodpy as hmp
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.data_managers import DataManagersPlanner, DataManagersRuntimeLoader
from hydromodpy.domain import Domain
from hydromodpy.domain.structure_binders import (
    apply_catchment_zones_to_domain,
    apply_geology_to_domain,
)
from hydromodpy.process.flow import Flow
from hydromodpy.process.flow.structure_binders import apply_recharge_load_result_to_flow
from hydromodpy.process.transport import Transport
from hydromodpy.simulation.state.run_state import LauncherRunState
from hydromodpy.solver.modflow_nwt import (
    Modflow,
    ModflowPostprocessOptions,
    ModflowPreprocessOptions,
    ModflowRunOptions,
    Modpath,
)
from hydromodpy.simulation.time import ResolvedSteadySimulationTimeGrid
from hydromodpy.display import visualization_watershed, visualization_results, export_vtuvtk


# =====================================================================
# 1. CHARGER LE TOML & CONSTRUIRE LES OBJETS STRUCTURELS
# =====================================================================

config_path = Path(__file__).parent / "project.toml"
cfg = HydroModPyConfig.from_toml(config_path)

with config_path.open("rb") as fh:
    raw_toml = tomllib.load(fh)

# -- Workspace & Geographic --
ws = hmp.Workspace(config=cfg.workspace)
geographic = hmp.Geographic(cfg.geographic, ws)
domain_geo = geographic.get_domain_geographic_context()
surface_topo = domain_geo.surface_topo

# -- Domain (ajouter la zone "catchment" comme le fait le launcher) --
domain_cfg = cfg.domain.model_copy(deep=True)
if "catchment" not in [z.lower() for z in domain_cfg.zone_ids]:
    domain_cfg.zone_ids.append("catchment")
domain = Domain(config=domain_cfg, surface_topo=surface_topo)
apply_catchment_zones_to_domain(domain=domain, geographic=domain_geo)

# -- Chargement des données (géologie, hydrographie, intermittence) --
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
run_state.setup.domain_geographic = domain_geo
run_state.setup.domain = domain

loader = DataManagersRuntimeLoader(
    config_path=config_path.resolve(),
    data_plan=data_plan,
)
loader.load_all(run_state)

loaded_data = run_state.loaded_data
apply_geology_to_domain(domain=domain, geology=loaded_data.geology)


# =====================================================================
# 2. CONSTRUIRE FLOW & TRANSPORT DEPUIS LE TOML
# =====================================================================

# Les paramètres flow et transport viennent du TOML (cfg.flow, cfg.transport)
flow = Flow(config=cfg.flow)
transport = Transport(config=cfg.transport)

# -- Exemple de surcharge d'un paramètre depuis Python --
# (décommenter pour expérimenter)
# flow.parameters["K"].field_homogeneous.value = 2.0
# flow.config.flow_regime = "transient"

# -- Recharge (via LoadResult from data managers) --
apply_recharge_load_result_to_flow(flow=flow, recharge_result=loaded_data.recharge)


# =====================================================================
# 3. EXÉCUTER MODFLOW-NWT
# =====================================================================

model_name = cfg.workspace.catch_name

model_modflow = Modflow(
    geographic,
    modflow_config=cfg.modflownwt,
    model_folder=str(ws.simulations_folder),
    model_name=model_name,
    bin_path=str(ws.bin_path),
)

print("\n" + "=" * 60)
print(f"  Simulation : {model_name}")
print(f"  Flow regime: {cfg.flow.flow_regime}")
print(f"  Output dir : {ws.simulations_folder / model_name}")
print("=" * 60 + "\n")

model_modflow.pre_processing(
    flow=flow,
    domain=domain,
    options=ModflowPreprocessOptions(
        box=True, sink_fill=False, check_grid=True,
        time_grid=ResolvedSteadySimulationTimeGrid(),
    ),
)

success = model_modflow.processing(
    options=ModflowRunOptions(write_model=True, run_model=True, link_mt3dms=True, verbose=True),
)

if not success:
    print("[ERROR] MODFLOW-NWT n'a pas convergé.")
    sys.exit(1)

model_modflow.post_processing(
    options=ModflowPostprocessOptions(
        watertable_elevation=True,
        watertable_depth=True,
        seepage_areas=True,
        outflow_drain=True,
        groundwater_flux=True,
        groundwater_storage=True,
        accumulation_flux=True,
    ),
)


# =====================================================================
# 4. EXÉCUTER MODPATH (traçage de particules backward)
# =====================================================================

model_modpath = Modpath(
    domain,
    transport,
    model_modflow=model_modflow,
    model_folder=str(ws.simulations_folder),
    model_name=model_name,
    bin_path=str(ws.bin_path),
)

model_modpath.pre_processing()
model_modpath.processing(write_model=True, run_model=True)
model_modpath.post_processing(
    model_modpath,
    ending_point=True,
    starting_point=True,
    pathlines_shp=True,
    particles_shp=True,
)
model_modpath.filt_processing(
    model_modpath,
    norm_flux=True,
    filt_time=True,
    filt_seep=True,
    filt_inout=True,
    calc_rtd=False,
)


# =====================================================================
# Raccourcis pour les sections de visualisation
# =====================================================================

data_path = cfg.workspace.data_path
stable_folder = ws.stable_folder
sim_folder = ws.simulations_folder / model_name
fig_dir = sim_folder / "_postprocess" / "_figures"
fig_dir.mkdir(parents=True, exist_ok=True)


# =====================================================================
# 5. VISUALISATION DU BASSIN VERSANT
# =====================================================================

try:
    visualization_watershed.watershed_local(cfg.geographic.dem_init_path, ws, geographic)
except Exception as exc:
    print(f"[skip] watershed_local: {exc}")

try:
    visualization_watershed.watershed_geology(ws, geographic, loaded_data.geology)
except Exception as exc:
    print(f"[skip] watershed_geology: {exc}")

try:
    visualization_watershed.watershed_dem(ws, geographic)
except Exception as exc:
    print(f"[skip] watershed_dem: {exc}")


# =====================================================================
# 6. DÉBITS — Statistiques interannuelles
# =====================================================================

qobs_file = data_path / "hydrometry catchment Canut.csv"
if qobs_file.exists():
    Qobs = pd.read_csv(qobs_file, sep=";", index_col=0, parse_dates=True)
    Qobs = Qobs.squeeze()
    Qobs = Qobs.rename("Q")

    first, last = 1990, 2019
    Qobs = Qobs[(Qobs.index.year >= first) & (Qobs.index.year <= last)]

    # m3/s -> mm/d  (area is in km2, so * 1e6 for m2)
    area_km2 = geographic.catch_area
    Qobs = (Qobs / (area_km2 * 1e6)) * 86400 * 1000

    data_index = Qobs.copy()
    grouped = data_index.groupby([data_index.index.month, data_index.index.day])
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
        mean_interan.counts, mean_interan.q10, mean_interan.q90,
        color="cyan", edgecolor="grey", lw=0.5, alpha=0.5, label="10-90th",
    )
    ax.set_yscale("log")
    ax.set_xlim(0, 366)
    ax.set_ylim(0.01, 10)
    ax.tick_params(axis="both", which="major", pad=10)
    months_ticks = np.linspace(0, 366, 13)
    ax.set_xticks(months_ticks)
    ax.set_xticklabels(["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D", "J"])
    ax.set_xlabel("Months", labelpad=10)
    ax.set_ylabel("Q / A [mm/d]", labelpad=10)
    ax.set_title(f"{model_name} [{first} to {last}]")
    ax.grid(alpha=0.25, zorder=0)

    year = 2017
    one_year = data_index[data_index.index.year == year].to_frame()
    one_year = one_year.groupby([one_year.index.month, one_year.index.day]).mean()
    one_year["counts"] = np.arange(1, len(one_year) + 1)
    ax.plot(one_year.counts, one_year["Q"], color="blue", lw=1, label=str(year))
    ax.legend(loc="lower left")
    plt.tight_layout()
    fig.savefig(fig_dir / "streamflow_interannual.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    print("[plot] streamflow_interannual.png")
else:
    print(f"[skip] streamflow: {qobs_file} not found")


# =====================================================================
# 7. RECHARGE — Chronique journalière depuis réanalyse CSV
# =====================================================================

reanalysis_file = data_path / "_climate_REANALYSIS.csv"
if reanalysis_file.exists():
    try:
        _df = pd.read_csv(reanalysis_file, sep=";", index_col=0, dayfirst=True, parse_dates=True)
        _col = next((c for c in _df.columns if "REC_REA" in c or c.startswith("REA_")), _df.columns[0])
        R = _df[_col].dropna()
        R = R[(R.index.year >= 1990) & (R.index.year <= 2019)]
        R = R.resample("D").mean().ffill()

        fig, ax = plt.subplots(1, 1, figsize=(6, 2), dpi=300)
        ax.patch.set_visible(False)
        ax.plot(R.index, R, color="blue", lw=1, clip_on=True)
        ax.fill_between(R.index, R * 0, R, color="skyblue", alpha=1, clip_on=True)
        ax.set_xlabel("Date")
        ax.xaxis.set(minor_locator=mdates.YearLocator(1), major_locator=mdates.YearLocator(5))
        ax.set_ylim(0, 8)
        ax.set_xlim(pd.to_datetime("2000"), pd.to_datetime("2020"))
        ax.set_yticks([0, 2, 4, 6, 8])
        ax.grid(which="both", axis="x")
        ax.invert_yaxis()
        ax.set_title("Recharge [mm/d]", color="blue")
        plt.tight_layout()
        fig.savefig(fig_dir / "input_recharge.png", dpi=300, bbox_inches="tight")
        plt.close(fig)
        print("[plot] input_recharge.png")
    except Exception as exc:
        print(f"[skip] recharge plot: {exc}")
else:
    print(f"[skip] recharge plot: {reanalysis_file} not found")


# =====================================================================
# 8. COUPES DU MAILLAGE — HK et Sy via FloPy
# =====================================================================

nam_file = sim_folder / f"{model_name}.nam"

if nam_file.exists():
    mf = flopy.modflow.Modflow.load(str(nam_file), check=False)
    grid = mf.modelgrid
    hk = mf.upw.hk
    sy = mf.upw.sy

    fig, axs = plt.subplots(1, 2, figsize=(12, 4), sharey=True)

    ax = axs[0]
    xsect = flopy.plot.PlotCrossSection(model=mf, line={"Row": grid.shape[1] // 2})
    val = hk.array / 86400  # m/d -> m/s
    try:
        for i in range(val.shape[0]):
            val[i][val[i] <= np.nanmin(val[i])] = np.nanmin(val[i][np.nonzero(val[i])])
    except Exception:
        pass
    cb = xsect.plot_array(val, ax=ax, cmap="viridis", lw=0.5, norm=mpl.colors.LogNorm(vmin=1e-8, vmax=1e-3))
    ax.set_title("Hydraulic conductivity [m/s] — W to E (center)", fontsize=12)
    ax.set_xlim(0, 9000)
    ax.set_ylim(40, 150)
    ax.set_xticks([0, 2000, 4000, 6000, 8000])
    ax.set_yticks([50, 75, 100, 125, 150])
    ax.set_xlabel("Distance [m]")
    ax.set_ylabel("Elevation [m]")
    fig.colorbar(cb, ax=ax)

    ax = axs[1]
    xsect = flopy.plot.PlotCrossSection(model=mf, line={"Column": grid.shape[2] // 2})
    cb = xsect.plot_array(sy.array * 100, ax=ax, cmap="viridis", lw=0.5, norm=mpl.colors.LogNorm(vmin=0.1, vmax=10))
    ax.set_title("Specific yield [%] — N to S (center)", fontsize=12)
    ax.set_xlim(0, 5500)
    ax.set_ylim(40, 150)
    ax.set_xticks([0, 1000, 2000, 3000, 4000, 5000])
    ax.set_yticks([50, 75, 100, 125, 150])
    ax.set_xlabel("Distance [m]")
    fig.suptitle(model_name.upper(), fontsize=8)
    fig.colorbar(cb, ax=ax)
    plt.tight_layout()
    fig.savefig(fig_dir / "mesh_cross.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    print("[plot] mesh_cross.png")
else:
    print("[skip] mesh cross-sections: NAM file not found")


# =====================================================================
# 9. COUPE FIXE — MNT vs. surface piézométrique
# =====================================================================

wt_path = sim_folder / "_postprocess" / "watertable_elevation.npy"
dem_tif = stable_folder / "geographic" / "watershed_dem.tif"

if wt_path.exists() and dem_tif.exists():
    dem_data = imageio.imread(str(dem_tif))
    wt_dict = np.load(str(wt_path), allow_pickle=True).item()
    wt_data = wt_dict[0]

    wt_prof = wt_data.astype(float)
    wt_prof[wt_prof < 0] = np.nan
    dem_prof = dem_data.astype(float)
    dem_prof[dem_prof < 0] = np.nan

    cur_x = 65
    cell_size = 75
    x = np.arange(dem_prof.shape[0]) * cell_size
    dem_slice = dem_prof[:, cur_x]
    dem_slice[dem_slice == 0] = np.nan
    wt_slice = wt_prof[:, cur_x]
    wt_slice[wt_slice == 0] = np.nan

    fig, ax = plt.subplots(figsize=(6, 4), dpi=300)
    ax.fill_between(x, dem_slice - 20, wt_slice, color="dodgerblue", alpha=0.5, lw=0)
    ax.plot(x, wt_slice, color="navy", lw=1.5)
    ax.fill_between(x, wt_slice, dem_slice, color="saddlebrown", alpha=0.5, lw=0)
    ax.plot(x, dem_slice, "saddlebrown", lw=1.5)
    ax.fill_between(x, 0, dem_slice - 20, color="lightgrey", alpha=0.5, lw=0)
    ax.plot(x, dem_slice - 20, color="dimgray", lw=1.5)
    ax.set_xlim(1000, 4000)
    ax.set_ylim(90, 130)
    ax.set_yticks([90, 100, 110, 120, 130])
    ax.set_xlabel("Distance [m]")
    ax.set_ylabel("Elevation [m]")
    plt.tight_layout()
    fig.savefig(fig_dir / "cross_section_watertable.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    print("[plot] cross_section_watertable.png")
else:
    print("[skip] cross-section: watertable or DEM raster not found")


# =====================================================================
# 10. VISUALISATION 2D
# =====================================================================

try:
    hydrography = loaded_data.hydrography
    visu = visualization_results.Visualization(ws, geographic, hydrography, model_name)
    visu.visual2D(
        object_list=[
            "map", "grid", "watertable", "watertable_depth",
            "drain_flow", "surface_flow", "pathlines", "residence_times",
        ],
        color_scale=[
            (None, None), (80, 150), (80, 150), (0, 10),
            (0, 200), (0, 30000), (0, 3), (0, 3),
        ],
        lines=1000,
    )
    print("[plot] 2D visualization")
except Exception as exc:
    print(f"[skip] 2D visualization: {exc}")


# =====================================================================
# 11. EXPORT 3D / VTK
# =====================================================================

try:
    export_vtuvtk.VTK(ws, geographic, hydrography, model_name)
    print("[vtk]  VTK files exported")
except Exception as exc:
    print(f"[skip] VTK export: {exc}")

try:
    visu = visualization_results.Visualization(ws, geographic, hydrography, model_name)
    visu.visual3D(
        interactive=True,
        object_list=["grid", "watertable", "watertable_depth", "surface_flow", "drain_flow", "pathlines"],
        view="south-west",
        lines=None,
        cloc=(0.7, 0.1),
        z_scale=10,
    )
    print("[plot] 3D visualization")
except Exception as exc:
    print(f"[skip] 3D visualization: {exc}")


# =====================================================================
# 12. COUPE INTERACTIVE
# =====================================================================

# Décommenter pour activer (nécessite un backend GUI) :
#
# dem_box = imageio.imread(str(stable_folder / "geographic" / "watershed_box_buff_dem.tif"))
# stream = imageio.imread(str(stable_folder / "hydrography" / "regional stream network.tif"))
# wt_raster = imageio.imread(str(sim_folder / "_postprocess" / "_rasters" / "watertable_elevation_t(0).tif"))
# visu = visualization_results.Visualization(ws, geographic, hydrography, model_name)
# visu.interactive_cross_section(dem_box, wt_raster, stream, interactive=True)


print(f"\nDone — all outputs at: {sim_folder}")
