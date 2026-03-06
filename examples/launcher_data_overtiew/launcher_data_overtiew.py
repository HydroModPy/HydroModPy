# -*- coding: utf-8 -*-
"""launcher_data_overtiew: setup + data loading only (no process execution).

This script is intentionally "data-only":
- build workspace/geographic/domain contexts,
- load and bind data managers,
- print an activation summary,
- optionally plot watershed data overlays,
- never execute flow/transport simulation solvers.
"""

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
    # 1) Parse and validate TOML into the canonical HydroModPy config object.
    cfg = HydroModPyConfig.from_toml(config_path)

    # Optional output override for test runs and CI.
    if out_override := os.environ.get("HYDROMODPY_OUT_PATH"):
        cfg.workspace.out_dir_path = Path(out_override)

    # Keep raw TOML for planner diagnostics and compatibility checks.
    with config_path.open("rb") as stream:
        raw_toml = tomllib.load(stream)

    # 2) Resolve active data-manager families (explicit + inferred).
    data_plan = DataManagersPlanner().build(
        cfg.data,
        domain_zone_ids=cfg.domain.zone_ids,
        raw_toml=raw_toml,
        flow_active_bc=cfg.flow.active_bc,
    )
    cfg.data = cfg.data.with_resolved_types(data_plan.types)

    # 3) Create one shared launcher state object.
    run_state = LauncherRunState(
        cfg=cfg,
        config_path=config_path,
        raw_toml=raw_toml,
        data_plan=data_plan,
    )

    # 4) Build setup contexts required by data loaders and visualizations.
    workspace = hmp.Workspace(config=cfg.workspace)
    geographic = hmp.Geographic(cfg.geographic, workspace)
    domain = None
    # Domain is optional for this data-overview launcher.
    # Build it only when explicitly configured or when geology is active.
    if "domain" in raw_toml or "geology" in data_plan.types:
        surface_topo = geographic.get_domain_surface_topo()
        domain = Domain(config=cfg.domain, surface_topo=surface_topo)

    run_state.setup.workspace = workspace
    run_state.setup.geographic = geographic
    run_state.setup.domain = domain

    return run_state


def _load_data(run_state: LauncherRunState) -> None:
    if run_state.data_plan is None:
        raise ValueError("Data plan is missing.")

    # Load all active data managers declared/resolved in the data plan.
    loader = DataManagersRuntimeLoader(
        config_path=run_state.config_path,
        data_plan=run_state.data_plan,
    )
    loader.load_all(run_state)

    # Bind loaded geology object to Domain.zones when a domain exists.
    if run_state.setup.domain is not None:
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
    # Headless switch used by tests/CI to skip plotting side effects.
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
    # Example-local configuration entry point.
    config_path = Path(__file__).parent / "config.toml"
    run_state = _build_run_state(config_path)

    watershed_name = run_state.cfg.workspace.catch_name
    print(f"##### {watershed_name.upper()} #####")

    # Data overview workflow only: setup + data + display.
    _load_data(run_state)
    _show_summary(run_state)
    _plot_watershed_overview(run_state)


if __name__ == "__main__":
    main()
