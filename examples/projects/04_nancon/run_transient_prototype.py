# -*- coding: utf-8 -*-
"""Exemple 04 — Bassin du Nancon, simulation transitoire (prototypage).

Les parametres (flow, transport, solver) sont lus depuis le TOML.
L'execution est pilotee ici : on construit les objets, on lance
MODFLOW-NWT en transitoire, puis MODPATH pour le tracage de particules.

Ce mode permet de surcharger des parametres depuis Python et de
personnaliser le post-traitement.

Usage::

    python run_transient_prototype.py
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

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
from hydromodpy.simulation.time import (
    ResolvedSimulationTimeGrid,
    ResolvedSimulationTimeWindow,
    build_simulation_time_boundaries,
)
from hydromodpy.solver.modflow_nwt import (
    Modflow,
    ModflowPostprocessOptions,
    ModflowPreprocessOptions,
    ModflowRunOptions,
    Modpath,
)
from hydromodpy.display import visualization_watershed, visualization_results


# =====================================================================
# 1. Charger le TOML et construire les objets structurels
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

# -- Domain --
domain_cfg = cfg.domain.model_copy(deep=True)
if "catchment" not in [z.lower() for z in domain_cfg.zone_ids]:
    domain_cfg.zone_ids.append("catchment")
domain = Domain(config=domain_cfg, surface_topo=surface_topo)
apply_catchment_zones_to_domain(domain=domain, geographic=domain_geo)

# -- Chargement des donnees (geologie, hydrographie, intermittence, recharge) --
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
# 2. Construire Flow & Transport depuis le TOML
# =====================================================================

flow = Flow(config=cfg.flow)
transport = Transport(config=cfg.transport)

# -- Exemple : surcharger un parametre depuis Python --
# flow.parameters["K"].field_homogeneous.value = 1e-4
# flow.parameters["Sy"].field_homogeneous.value = 0.10

# -- Appliquer la recharge depuis les data managers --
apply_recharge_load_result_to_flow(flow=flow, recharge_result=loaded_data.recharge)


# =====================================================================
# 3. Definir la grille temporelle en transitoire
# =====================================================================

# En mode prototype, c'est nous qui construisons le time grid.
# On reproduit le comportement du launcher : mensuel de 2000 a 2002.
window = ResolvedSimulationTimeWindow(
    start=pd.Timestamp("2000-01-01"),
    end=pd.Timestamp("2002-12-31"),
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


# =====================================================================
# 4. Executer MODFLOW-NWT
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
print(f"  Regime     : {cfg.flow.flow_regime}")
print(f"  Periode    : 2000-01 -> 2002-12 (mensuel)")
print(f"  Sortie     : {ws.simulations_folder / model_name}")
print("=" * 60 + "\n")

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
        verbose=True,
    ),
)

if not success:
    print("[ERREUR] MODFLOW-NWT n'a pas converge.")
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
        persistency_index=True,
        intermittency_monthly=True,
    ),
)


# =====================================================================
# 5. Executer MODPATH (tracage backward)
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
# 6. Visualisation du bassin versant
# =====================================================================

sim_folder = ws.simulations_folder / model_name
fig_dir = sim_folder / "_postprocess" / "_figures"
fig_dir.mkdir(parents=True, exist_ok=True)

try:
    visualization_watershed.watershed_local(cfg.geographic.dem_init_path, ws, geographic)
except Exception as exc:
    print(f"[skip] watershed_local: {exc}")

try:
    visualization_watershed.watershed_geology(ws, geographic, loaded_data.geology)
except Exception as exc:
    print(f"[skip] watershed_geology: {exc}")


# =====================================================================
# 7. Recharge et debits : graphiques rapides
# =====================================================================

# -- Recharge (depuis les donnees chargees) --
if loaded_data.recharge is not None:
    rec_points = loaded_data.recharge.points
    if rec_points:
        rec_series = rec_points[0].data.set_index("datetime")["value"]
        fig, ax = plt.subplots(figsize=(6, 2.5))
        ax.bar(rec_series.index, rec_series, width=25, color="dodgerblue", alpha=0.8)
        ax.set_ylabel("Recharge [mm/j]")
        ax.set_title("Recharge mensuelle (Nancon, 2000-2002)")
        plt.tight_layout()
        fig.savefig(fig_dir / "input_recharge.png", dpi=200, bbox_inches="tight")
        plt.close(fig)
        print("[plot] input_recharge.png")

# -- Debits observes --
data_path = cfg.workspace.data_path
qobs_file = "hydrometry/hydrometry_custom_NANCON_19820201_20220125_D.csv"
qobs_abs = (data_path / qobs_file).resolve() if data_path else None

if qobs_abs is not None and qobs_abs.exists():
    Qobs = pd.read_csv(qobs_abs, sep=";", index_col=0, parse_dates=True).squeeze()
    Qobs = Qobs[(Qobs.index.year >= 2000) & (Qobs.index.year <= 2002)]
    Qobs_month = Qobs.resample("ME").mean()

    fig, ax = plt.subplots(figsize=(6, 2.5))
    ax.plot(Qobs_month, color="k", lw=1.5, label="Q obs")
    ax.set_ylabel("Q [m3/s]")
    ax.set_title("Debits mensuels observes (Nancon)")
    ax.legend()
    plt.tight_layout()
    fig.savefig(fig_dir / "streamflow_obs.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("[plot] streamflow_obs.png")


# =====================================================================
# 8. Visualisation 2D des resultats
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
            (None, None), (80, 250), (80, 250), (0, 30),
            (0, 200), (0, 30000), (0, 3), (0, 3),
        ],
        lines=1000,
    )
    print("[plot] 2D visualization")
except Exception as exc:
    print(f"[skip] 2D visualization: {exc}")


print(f"\nTermine. Resultats dans : {sim_folder}")
