# -*- coding: utf-8 -*-
"""launcher_data_overtiew: setup + data loading only (no process execution)."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import hydromodpy as hmp
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.data_managers import DataManagersPlanner, DataManagersRuntimeLoader
from hydromodpy.display import visualization_watershed
from hydromodpy.domain import Domain
from hydromodpy.domain.structure_binders import apply_geology_to_domain
from hydromodpy.simulation.state.run_state import LauncherRunState


def _build_run_state(config_path: Path) -> LauncherRunState:
    cfg = HydroModPyConfig.from_toml(config_path)

    if out_override := os.environ.get("HYDROMODPY_OUT_PATH"):
        cfg.workspace.out_dir_path = Path(out_override)

    with config_path.open("rb") as stream:
        raw_toml = tomllib.load(stream)

    data_plan = DataManagersPlanner().build(
        cfg.data,
        domain_zone_ids=cfg.domain.zone_ids,
        raw_toml=raw_toml,
        flow_active_bc=cfg.flow.active_bc,
    )
    cfg.data = cfg.data.with_resolved_types(data_plan.types)

    run_state = LauncherRunState(
        cfg=cfg,
        config_path=config_path,
        raw_toml=raw_toml,
        data_plan=data_plan,
    )

    workspace = hmp.Workspace(config=cfg.workspace)
    geographic = hmp.Geographic(cfg.geographic, workspace)
    surface_topo = geographic.get_domain_surface_topo()
    domain = Domain(config=cfg.domain, surface_topo=surface_topo)

    run_state.setup.workspace = workspace
    run_state.setup.geographic = geographic
    run_state.setup.domain = domain

    return run_state


def _load_data(run_state: LauncherRunState) -> None:
    if run_state.data_plan is None:
        raise ValueError("Data plan is missing.")

    loader = DataManagersRuntimeLoader(
        config_path=run_state.config_path,
        data_plan=run_state.data_plan,
    )
    loader.load_all(run_state)

    if run_state.setup.domain is None:
        raise ValueError("Domain was not initialized.")

    apply_geology_to_domain(
        domain=run_state.setup.domain,
        geology=run_state.loaded_data.geology,
    )


def _show_summary(run_state: LauncherRunState) -> None:
    plan = run_state.data_plan
    if plan is None:
        return

    active = ", ".join(plan.types) if plan.types else "none"
    print(f"Data managers active: {active}")

    if plan.inferred_types:
        print("Inferred data types:")
        for type_name in plan.inferred_types:
            reasons = "; ".join(plan.reasons_for(type_name))
            print(f"- {type_name}: {reasons}")


def _plot_watershed_overview(run_state: LauncherRunState) -> None:
    if os.environ.get("HYDROMODPY_NO_DISPLAY") == "1":
        return

    workspace = run_state.setup.workspace
    geographic = run_state.setup.geographic
    data = run_state.loaded_data

    if workspace is None or geographic is None:
        raise ValueError("Workspace or geographic context missing.")

    visualization_watershed.watershed_local(
        run_state.cfg.geographic.dem_init_path,
        workspace,
        geographic,
    )
    visualization_watershed.watershed_dem(
        workspace,
        geographic,
        hydrography=data.hydrography,
        piezometry=data.piezometry,
        intermittency=data.intermittency,
        hydrometry=data.hydrometry,
    )


def main() -> None:
    config_path = Path(__file__).parent / "config.toml"
    run_state = _build_run_state(config_path)

    watershed_name = run_state.cfg.workspace.catch_name
    print(f"##### {watershed_name.upper()} #####")

    _load_data(run_state)
    _show_summary(run_state)
    _plot_watershed_overview(run_state)


if __name__ == "__main__":
    main()
