"""Cross-model transient investigation for one hillslope with a sloping substratum."""

from __future__ import annotations

import argparse
import json
import os
import time
from math import tan
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import tools.investigate_surface_interaction_hillslope_transient as base
from hydromodpy.spatial.domain import Domain
from hydromodpy.spatial.geographic.synthetic.config import SyntheticGeographicConfig
from hydromodpy.spatial.geographic.synthetic.synthetic_geographic import build_synthetic_geographic
from hydromodpy.spatial.surface import Surface
from hydromodpy.physics.flow import Flow
from hydromodpy.solver.modflow6 import Modflow6
from hydromodpy.solver.modflow_common import (
    ModflowPostprocessOptions,
    ModflowPreprocessOptions,
    ModflowRunOptions,
)
from hydromodpy.solver.modflow_nwt import Modflow
from hydromodpy.simulation.adapters.flow.boussinesq import BoussinesqFlowAdapter
from hydromodpy.simulation.planning.plan import ProcessRun, RunContext, SimulationPlan
from hydromodpy.solver.boussinesq.history_contract import (
    build_transient_time_axes,
    elapsed_seconds_for_time_keys,
    write_time_series_npy,
)
from validation_cases.analytical.steady.boussinesq_piecewise import mm_day_to_m_s
from validation_cases.shared import ValidationRunResult, load_case_metadata
from validation_cases.shared.boussinesq_uniform_strip import (
    build_flow_config,
)
from validation_cases.shared.gmsh_irregular_strip import write_irregular_strip_bundle
from validation_cases.shared.runtime import (
    _dump_toml,
    remove_tree_with_retry,
    resolve_model_workspace,
    resolve_validation_results_dir,
    run_example_script,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = (
    REPO_ROOT
    / "validation_cases"
    / "numerical"
    / "transient"
    / "boussinesq_hillslope_sloping_substratum_1d"
)
LAUNCHER_BASE_CASE_DIR = base.CASE_DIR
LAUNCHER_SCRIPT = base.LAUNCHER_SCRIPT

SOLVER_ORDER = ("modflownwt", "modflow6", "modflow6_irregular_tri", "boussinesq")
SOLVER_LABELS = {
    "modflownwt": "MODFLOW-NWT",
    "modflow6": "MODFLOW 6 structured",
    "modflow6_irregular_tri": "MODFLOW 6 irregular triangles",
    "boussinesq": "Boussinesq",
}
SOLVER_COLORS = {
    "modflownwt": "#1f77b4",
    "modflow6": "#ff7f0e",
    "modflow6_irregular_tri": "#9467bd",
    "boussinesq": "#2ca02c",
}

NX = 40
NY = 3
STRUCTURED_NX = 50
STRUCTURED_NY = 6
IRREGULAR_TRI_NX_SEED = 10
IRREGULAR_TRI_NY_SEED = 3
IRREGULAR_TRI_SEED = 20260413
LENGTH_X_M = 100.0
WIDTH_Y_M = 12.0
TOPOGRAPHY_BASE_ELEVATION_M = 5.0
TOPOGRAPHY_SLOPE_DEG = 12.0
BOTTOM_BASE_ELEVATION_M = -15.0
BOTTOM_SLOPE_DEG = 10.0
TOPOGRAPHY_RIGHT_TO_LEFT_AMPLITUDE_M = float(tan(np.deg2rad(TOPOGRAPHY_SLOPE_DEG)) * LENGTH_X_M)
BOTTOM_RIGHT_TO_LEFT_AMPLITUDE_M = float(tan(np.deg2rad(BOTTOM_SLOPE_DEG)) * LENGTH_X_M)
HYDRAULIC_CONDUCTIVITY_M_S = 2.0e-5
SPECIFIC_YIELD = 0.10
SPECIFIC_STORAGE_M_INV = 1.0e-10
DRAINAGE_CONDUCTANCE_M2_S = 1.0e-4
DT_DAYS = 15.0
RECHARGE_SERIES_MM_DAY = (
    0.6,
    0.6,
    1.8,
    1.8,
    3.0,
    3.0,
    4.2,
    4.2,
    5.4,
    5.4,
    7.2,
    7.2,
    6.0,
    6.0,
    4.8,
    4.8,
    3.6,
    3.6,
    2.4,
    2.4,
    1.2,
    1.2,
    0.6,
    0.6,
    0.0,
    0.0,
    0.0,
    0.0,
)
SNAPSHOT_DAYS = (15.0, 90.0, 180.0, 270.0, 360.0, 420.0)
POINT_BANDS = (
    ("upper_slope", "Upper slope", 0.00, 1.0 / 3.0),
    ("mid_slope", "Mid slope", 1.0 / 3.0, 2.0 / 3.0),
    ("near_toe", "Near toe", 2.0 / 3.0, 1.0),
)
INITIAL_HEAD_M = 5.25
EAST_HEAD_M = 5.25
SYNTHETIC_SQUARE_NY = 3
SYNTHETIC_SQUARE_NX = 25
STRUCTURED_CELL_SIZE_M = LENGTH_X_M / float(STRUCTURED_NX)


def build_topography_profile(x_m: np.ndarray | float) -> np.ndarray:
    x = np.asarray(x_m, dtype=float)
    return TOPOGRAPHY_BASE_ELEVATION_M + TOPOGRAPHY_RIGHT_TO_LEFT_AMPLITUDE_M * (
        1.0 - x / float(LENGTH_X_M)
    )


def build_bottom_profile(x_m: np.ndarray | float) -> np.ndarray:
    x = np.asarray(x_m, dtype=float)
    return BOTTOM_BASE_ELEVATION_M + BOTTOM_RIGHT_TO_LEFT_AMPLITUDE_M * (
        1.0 - x / float(LENGTH_X_M)
    )


def _configure_base_module() -> None:
    base.SOLVER_ORDER = SOLVER_ORDER
    base.SOLVER_LABELS = SOLVER_LABELS
    base.SOLVER_COLORS = SOLVER_COLORS
    base.BOUSS_NX = NX
    base.BOUSS_NY = NY
    base.LENGTH_X_M = LENGTH_X_M
    base.WIDTH_Y_M = WIDTH_Y_M
    base.TOPOGRAPHY_BASE_ELEVATION_M = TOPOGRAPHY_BASE_ELEVATION_M
    base.TOPOGRAPHY_RIGHT_TO_LEFT_AMPLITUDE_M = TOPOGRAPHY_RIGHT_TO_LEFT_AMPLITUDE_M
    base.SPECIFIC_YIELD = SPECIFIC_YIELD
    base.SPECIFIC_STORAGE_M_INV = SPECIFIC_STORAGE_M_INV
    base.DRAINAGE_CONDUCTANCE_M2_S = DRAINAGE_CONDUCTANCE_M2_S
    base.DT_DAYS = DT_DAYS
    base.RECHARGE_SERIES_MM_DAY = RECHARGE_SERIES_MM_DAY
    base.SNAPSHOT_DAYS = SNAPSHOT_DAYS
    base.POINT_BANDS = POINT_BANDS
    base.CONTACT_TOLERANCE_M = 0.02


def _build_structured_topography_array() -> np.ndarray:
    x_centers = (np.arange(int(STRUCTURED_NX), dtype=float) + 0.5) * STRUCTURED_CELL_SIZE_M
    profile = build_topography_profile(x_centers).reshape(1, -1)
    return np.repeat(profile, int(STRUCTURED_NY), axis=0)


def _build_structured_bottom_array() -> np.ndarray:
    x_centers = (np.arange(int(STRUCTURED_NX), dtype=float) + 0.5) * STRUCTURED_CELL_SIZE_M
    profile = build_bottom_profile(x_centers).reshape(1, -1)
    return np.repeat(profile, int(STRUCTURED_NY), axis=0)


def _build_structured_geographic(output_dir: Path):
    config = SyntheticGeographicConfig.model_validate(
        {
            "case_id": "sloping_substratum_structured",
            "grid": {
                "length_x": f"{LENGTH_X_M:.1f} m",
                "length_y": f"{WIDTH_Y_M:.1f} m",
                "nx": int(STRUCTURED_NX),
                "ny": int(STRUCTURED_NY),
                "xmin": 0.0,
                "ymin": 0.0,
                "crs": "EPSG:2154",
                "nodata": -9999.0,
            },
            "topography": {
                "kind": "linear",
                "base_elevation": float(TOPOGRAPHY_BASE_ELEVATION_M),
                "right_to_left_amplitude": float(TOPOGRAPHY_RIGHT_TO_LEFT_AMPLITUDE_M),
            },
        }
    )
    geographic = build_synthetic_geographic(
        config=config,
        output_dir=output_dir,
        workspace=None,
    )
    top_values = _build_structured_topography_array()
    geographic.surface_topo = Surface(
        name="surface_topo",
        values=top_values,
        support=geographic.surface_topo.support,
    )
    geographic.dem_box_buff_data = top_values.copy()
    geographic.dem_buff_data = top_values.copy()
    geographic.dem_data = top_values.copy()
    geographic.depressions_data = np.zeros_like(top_values, dtype=float)
    geographic.y_pixel = int(STRUCTURED_NY)
    geographic.x_pixel = int(STRUCTURED_NX)
    geographic.catch_area = float(LENGTH_X_M * WIDTH_Y_M / 1_000_000.0)
    return geographic


def _build_structured_domain(*, geographic, domain_cfg: dict[str, object]) -> Domain:
    domain = Domain(config=domain_cfg, surface_topo=geographic.surface_topo)
    domain.substratum = Surface(
        name="substratum",
        values=_build_structured_bottom_array(),
        support=geographic.surface_topo.support,
    )
    return domain


def _build_structured_flow(*, solver_name: str, run_variant: str) -> Flow:
    metadata = load_case_metadata(LAUNCHER_BASE_CASE_DIR)
    payload = base._load_case_payload_for_solver(metadata, solver_name)
    payload = base._apply_transient_payload(
        payload,
        solver=solver_name,
        hydraulic_conductivity_m_s=HYDRAULIC_CONDUCTIVITY_M_S,
        run_variant=run_variant,
    )
    flow_cfg = build_flow_config(dict(payload.get("flow", {})))
    return Flow(flow_cfg)


def _build_structured_solver_payload(*, solver_name: str, run_variant: str) -> dict[str, object]:
    metadata = load_case_metadata(LAUNCHER_BASE_CASE_DIR)
    payload = base._load_case_payload_for_solver(metadata, solver_name)
    payload = base._apply_transient_payload(
        payload,
        solver=solver_name,
        hydraulic_conductivity_m_s=HYDRAULIC_CONDUCTIVITY_M_S,
        run_variant=run_variant,
    )
    geographic = dict(payload.get("geographic", {}))
    synthetic = dict(geographic.get("synthetic", {}))
    synthetic["grid"] = {
        "length_x": f"{LENGTH_X_M:.1f} m",
        "length_y": f"{WIDTH_Y_M:.1f} m",
        "nx": int(STRUCTURED_NX),
        "ny": int(STRUCTURED_NY),
        "xmin": 0.0,
        "ymin": 0.0,
        "crs": "EPSG:2154",
        "nodata": -9999.0,
    }
    geographic["synthetic"] = synthetic
    payload["geographic"] = geographic
    solver_section = dict(payload.get(solver_name, {}))
    solver_sgrid = dict(solver_section.get("sgrid", {}))
    solver_sgrid["planar"] = {
        "mode": "resample_to_shape",
        "nx": int(STRUCTURED_NX),
        "ny": int(STRUCTURED_NY),
        "resampling": "nearest",
    }
    solver_sgrid["vertical"] = {"nlay": 1}
    solver_section["sgrid"] = solver_sgrid
    solver_section["tgrid"] = {"firstpersteady": False}
    payload[solver_name] = solver_section
    return payload


def _write_irregular_bundle(bundle_dir: Path) -> Path:
    return write_irregular_strip_bundle(
        bundle_dir,
        nx_seed=IRREGULAR_TRI_NX_SEED,
        ny_seed=IRREGULAR_TRI_NY_SEED,
        length_x_m=LENGTH_X_M,
        width_y_m=WIDTH_Y_M,
        z_top_m=build_topography_profile,
        z_bottom_m=build_bottom_profile,
        hydraulic_conductivity_m_s=HYDRAULIC_CONDUCTIVITY_M_S,
        storage_coefficient=SPECIFIC_YIELD,
        seed=IRREGULAR_TRI_SEED,
    )


def _export_boussinesq_irregular_postprocess(*, model, bundle_dir: Path) -> None:
    head_history = np.asarray(model.state.head_history_m, dtype=float)
    time_keys = np.arange(head_history.shape[0], dtype=int)

    cells = np.genfromtxt(
        bundle_dir / "cells.csv",
        delimiter=",",
        names=True,
        dtype=None,
        encoding="utf-8",
    )
    cell_top = np.asarray(cells["z_top_centroid"], dtype=float).reshape(1, -1)
    top_grid = base._interpolate_bundle_history_to_structured_grid(
        cell_top,
        bundle_dir=bundle_dir,
        nx=NX,
        ny=NY,
    )[0]
    head_grids = base._interpolate_bundle_history_to_structured_grid(
        head_history,
        bundle_dir=bundle_dir,
        nx=NX,
        ny=NY,
    )

    elapsed_seconds = elapsed_seconds_for_time_keys(
        build_transient_time_axes(model.state.period_lengths_seconds).snapshot_elapsed_seconds,
        time_keys,
        name="head_history_m",
    )
    elevation_grids: list[np.ndarray] = []
    depth_grids: list[np.ndarray] = []
    for time_index, head_grid in zip(time_keys.tolist(), head_grids, strict=False):
        elevation_grids.append(np.asarray(head_grid, dtype=float))
        depth_grids.append(np.maximum(top_grid - head_grid, 0.0))

    postprocess_dir = Path(model.full_path) / "_postprocess"
    write_time_series_npy(
        postprocess_dir / "watertable_elevation.npy",
        np.stack(elevation_grids, axis=0),
        time_keys=time_keys,
        elapsed_seconds=elapsed_seconds,
    )
    write_time_series_npy(
        postprocess_dir / "watertable_depth.npy",
        np.stack(depth_grids, axis=0),
        time_keys=time_keys,
        elapsed_seconds=elapsed_seconds,
    )


def _run_structured_modflow(
    *,
    solver_name: str,
    timeout: int,
    runtime_configs_dir: Path,
) -> ValidationRunResult:
    payload = _build_structured_solver_payload(
        solver_name=solver_name,
        run_variant=f"{solver_name}_sloping_structured",
    )
    out_path = resolve_validation_results_dir(
        test_file=__file__,
        run_name=f"sloping_substratum_{solver_name}_structured",
    )
    if out_path.exists():
        remove_tree_with_retry(out_path)
    out_path.mkdir(parents=True, exist_ok=True)

    runtime_configs_dir.mkdir(parents=True, exist_ok=True)
    config_path = runtime_configs_dir / f"sloping_substratum__{solver_name}_structured.toml"
    config_path.write_text(_dump_toml(payload), encoding="utf-8", newline="\n")

    geographic = _build_structured_geographic(out_path / "synthetic_geographic")
    domain = _build_structured_domain(
        geographic=geographic,
        domain_cfg=dict(payload.get("domain", {})),
    )
    flow = _build_structured_flow(
        solver_name=solver_name,
        run_variant=f"{solver_name}_sloping_structured",
    )
    period_lengths_seconds = tuple(
        float(DT_DAYS * base.SECONDS_PER_DAY) for _ in RECHARGE_SERIES_MM_DAY
    )
    preprocess_options = ModflowPreprocessOptions(
        time_grid=SimpleNamespace(
            period_lengths_seconds=period_lengths_seconds,
            window=None,
        )
    )
    model_folder = out_path / "results_simulations"
    model_name = f"sloping_substratum_{solver_name}_structured"
    bin_path = str(REPO_ROOT / "bin")
    solver_cfg = dict(payload.get(solver_name, {}))

    if solver_name == "modflownwt":
        model = Modflow(
            geographic,
            modflow_config=solver_cfg,
            model_folder=str(model_folder),
            model_name=model_name,
            bin_path=bin_path,
            preprocess_options=preprocess_options,
        )
    elif solver_name == "modflow6":
        model = Modflow6(
            geographic,
            modflow_config=solver_cfg,
            model_folder=str(model_folder),
            model_name=model_name,
            bin_path=bin_path,
            preprocess_options=preprocess_options,
        )
    else:
        raise ValueError(f"Unsupported structured MODFLOW solver '{solver_name}'.")

    model.pre_processing(
        flow=flow,
        domain=domain,
        options=preprocess_options,
    )
    success = bool(
        model.processing(
            options=ModflowRunOptions(
                write_model=True,
                run_model=True,
                link_mt3dms=False,
                verbose=False,
            )
        )
    )
    if not success:
        raise AssertionError(
            f"Direct structured run failed for {solver_name} on the sloping-substratum case."
        )
    model.post_processing(
        options=ModflowPostprocessOptions(
            watertable_elevation=True,
            watertable_depth=True,
            seepage_areas=False,
            outflow_drain=True,
            outlet_discharge_east_side_m3_s=True,
            groundwater_flux=False,
            groundwater_storage=False,
            accumulation_flux=True,
            native_mesh_npz=False,
            native_mesh_csv=False,
            native_mesh_vtu=False,
            native_mesh_png=False,
        )
    )

    model_ws = Path(model.full_path)
    postprocess_dir = model_ws / "_postprocess"
    return ValidationRunResult(
        case_dir=CASE_DIR,
        solver_name=solver_name,
        out_path=out_path,
        model_ws=model_ws,
        postprocess_dir=postprocess_dir,
        particles_dir=postprocess_dir / "_particles",
        run_returncode=0,
        run_stdout="",
        run_stderr="",
    )


def _run_mf6_irregular(*, timeout: int, runtime_configs_dir: Path) -> ValidationRunResult:
    metadata = load_case_metadata(LAUNCHER_BASE_CASE_DIR)
    out_path = resolve_validation_results_dir(
        test_file=__file__,
        run_name="sloping_substratum_modflow6_irregular_tri",
    )
    if out_path.exists():
        remove_tree_with_retry(out_path)
    out_path.mkdir(parents=True, exist_ok=True)

    payload = base._load_case_payload_for_solver(metadata, "modflow6")
    payload = base._apply_transient_payload(
        payload,
        solver="modflow6",
        hydraulic_conductivity_m_s=HYDRAULIC_CONDUCTIVITY_M_S,
        run_variant="modflow6_irregular_tri",
    )
    geographic = dict(payload.get("geographic", {}))
    synthetic = dict(geographic.get("synthetic", {}))
    synthetic["grid"] = {
        "length_x": f"{LENGTH_X_M:.1f} m",
        "length_y": f"{WIDTH_Y_M:.1f} m",
        "nx": SYNTHETIC_SQUARE_NX,
        "ny": SYNTHETIC_SQUARE_NY,
    }
    geographic["synthetic"] = synthetic
    payload["geographic"] = geographic
    bundle_dir = _write_irregular_bundle(out_path / "mesh_bundle")
    payload["mesh_input"] = {
        "mesh_path": str((bundle_dir / "mesh_2d.msh").resolve()),
        "bundle_dir": str(bundle_dir.resolve()),
    }
    solver_section = dict(payload.get("modflow6", {}))
    solver_sgrid = dict(solver_section.get("sgrid", {}))
    solver_section["sgrid"] = {"vertical": dict(solver_sgrid.get("vertical", {}))}
    payload["modflow6"] = solver_section

    simulation = dict(payload.get("simulation", {}))
    simulation["run_id"] = "sloping_substratum_modflow6_irregular_tri"
    simulation["name"] = "Transient sloping substratum MODFLOW 6 irregular triangles"
    simulation["description"] = (
        "Transient sloping-substratum strip on one irregular triangular mesh."
    )
    payload["simulation"] = simulation

    runtime_configs_dir.mkdir(parents=True, exist_ok=True)
    config_path = runtime_configs_dir / "sloping_substratum__modflow6_irregular_tri.toml"
    config_path.write_text(_dump_toml(payload), encoding="utf-8", newline="\n")

    completed = run_example_script(
        script_path=LAUNCHER_SCRIPT,
        out_path=out_path,
        out_env_var="HYDROMODPY_OUT_PATH",
        extra_env={"MPLBACKEND": "Agg"},
        script_args=[str(config_path)],
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "Launcher run failed for sloping-substratum MF6 irregular case.\n"
            f"Stdout:\n{completed.stdout}\nStderr:\n{completed.stderr}"
        )

    model_ws, postprocess_dir, particles_dir = resolve_model_workspace(
        out_path,
        results_folder_name=str(
            dict(metadata.get("workspace", {})).get("results_folder_name", "results_simulations")
        ),
    )
    return ValidationRunResult(
        case_dir=CASE_DIR,
        solver_name="modflow6_irregular_tri",
        out_path=out_path,
        model_ws=model_ws,
        postprocess_dir=postprocess_dir,
        particles_dir=particles_dir,
        run_returncode=int(completed.returncode),
        run_stdout=str(completed.stdout),
        run_stderr=str(completed.stderr),
    )


def _run_boussinesq_irregular(*, timeout: int) -> ValidationRunResult:
    del timeout
    out_path = resolve_validation_results_dir(
        test_file=__file__,
        run_name="sloping_substratum_boussinesq_irregular_tri",
    )
    if out_path.exists():
        remove_tree_with_retry(out_path)
    out_path.mkdir(parents=True, exist_ok=True)
    bundle_dir = _write_irregular_bundle(out_path / "mesh_bundle")

    flow_section = {
        "runtime_backend": "local",
        "flow_regime": "transient",
        "runtime_max_iterations": 80,
        "runtime_tol_residual_inf": 1.0e-7,
        "ic": {"type": "custom", "value": INITIAL_HEAD_M},
        "active_sinks_sources": ["recharge"],
        "active_bc": ["east_side", "drainage"],
        "sinks_sources": {
            "recharge": {
                "values": [mm_day_to_m_s(float(value)) for value in RECHARGE_SERIES_MM_DAY],
                "first_clim": "first",
            }
        },
        "bc": {
            "dirichlet": {"east_side": {"type": "dirichlet", "value": EAST_HEAD_M}},
            "cauchy": {
                "drainage": {
                    "application_domain": "top",
                    "type": "cauchy",
                    "value": DRAINAGE_CONDUCTANCE_M2_S,
                }
            },
        },
    }

    state = SimpleNamespace(
        setup=SimpleNamespace(
            mesh_bundle=None,
            mesh_summary={"output_exchange_bundle_dir": str(bundle_dir)},
            flow=Flow(build_flow_config(flow_section)),
            domain=None,
            time_grid=SimpleNamespace(
                period_lengths_seconds=tuple(float(DT_DAYS * base.SECONDS_PER_DAY) for _ in RECHARGE_SERIES_MM_DAY),
                window=None,
            ),
            workspace=SimpleNamespace(simulations_folder=out_path / "results_simulations"),
        ),
    )
    run = ProcessRun(
        id="flow_validation::boussinesq",
        process_id="flow_validation",
        process_type="flow",
        solver="boussinesq",
    )
    ctx = RunContext(
        plan=SimulationPlan(
            name="Transient sloping substratum Boussinesq irregular triangles",
            description="Transient sloping-substratum strip on one irregular triangular mesh.",
            runs=(run,),
        ),
        run=run,
        state=state,
    )
    result = BoussinesqFlowAdapter().execute(ctx)
    model = result.primary_model
    _export_boussinesq_irregular_postprocess(model=model, bundle_dir=bundle_dir)
    model_ws = Path(model.full_path)
    postprocess_dir = model_ws / "_postprocess"
    return ValidationRunResult(
        case_dir=CASE_DIR,
        solver_name="boussinesq",
        out_path=out_path,
        model_ws=model_ws,
        postprocess_dir=postprocess_dir,
        particles_dir=postprocess_dir / "_particles",
        run_returncode=0,
        run_stdout="",
        run_stderr="",
    )


def _write_summary(results: list[base.TransientResult], output_md: Path, figures_dir: Path) -> None:
    ordered = sorted(results, key=lambda item: SOLVER_ORDER.index(item.solver))
    lines = [
        "# Sloping-Substratum Transient Intercomparison",
        "",
        "Comparison on one explicit irregular triangular mesh with `z_bottom(x)` sloping by `10 deg`.",
        "",
        "- topography slope: `12 deg`",
        "- substratum slope: `10 deg`",
        f"- hydraulic conductivity: `{HYDRAULIC_CONDUCTIVITY_M_S:.3g} m/s`",
        f"- drainage conductance: `{DRAINAGE_CONDUCTANCE_M2_S:.3g} m2/s`",
        f"- time step: `{DT_DAYS:.1f} day`",
        f"- recharge series [mm/day]: `{list(RECHARGE_SERIES_MM_DAY)}`",
        "- west boundary is omitted here because the case keeps the divide/no-flow setting.",
        "- `MODFLOW-NWT` and `MODFLOW 6 structured` are run on one sloping structured support.",
        "- `MODFLOW 6 irregular triangles` and `Boussinesq` are run on one explicit irregular triangular bundle.",
        "",
        "| Solver | Onset day [d] | Peak drainage flux [m3/day] | Peak total outflow [m3/day] | Max clearance [m] | Wall time [s] | Results dir |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in ordered:
        wall_time_text = "n/a" if item.wall_time_seconds is None else f"{item.wall_time_seconds:.2f}"
        lines.append(
            f"| {SOLVER_LABELS[item.solver]} | {item.onset_day:.1f} | {item.peak_drainage_flux_m3_day:.4f} | {item.peak_total_outflow_m3_day:.4f} | {item.max_clearance_m:.4f} | {wall_time_text} | `{item.out_path}` |"
        )
    lines.extend(
        [
            "",
            f"Head snapshots: `{figures_dir / 'head_snapshots.png'}`",
            f"Head point time series: `{figures_dir / 'head_point_timeseries.png'}`",
            f"Flux chronicle: `{figures_dir / 'flux_timeseries.png'}`",
            f"Total outflow overlay: `{figures_dir / 'total_outflow_overlay.png'}`",
            f"Outflow components: `{figures_dir / 'outflow_components.png'}`",
            f"Complete flux budget: `{figures_dir / 'flux_budget_comparison.png'}`",
            f"Execution times: `{figures_dir / 'execution_times.png'}`",
            "",
        ]
    )
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text("\n".join(lines), encoding="utf-8")


def _select_informative_points_mixed(
    results: list[base.TransientResult],
) -> list[tuple[str, str, float]]:
    ordered = sorted(results, key=lambda item: SOLVER_ORDER.index(item.solver))
    reference_x = np.asarray(ordered[0].x, dtype=float)
    amplitude_by_solver: list[np.ndarray] = []
    for item in ordered:
        amplitude = np.ptp(np.asarray(item.head_profiles, dtype=float), axis=0)
        item_x = np.asarray(item.x, dtype=float)
        if item_x.shape != reference_x.shape or not np.allclose(item_x, reference_x):
            amplitude = np.interp(reference_x, item_x, amplitude)
        amplitude_by_solver.append(np.asarray(amplitude, dtype=float))
    combined_amplitude = np.mean(np.vstack(amplitude_by_solver), axis=0)

    selected: list[tuple[str, str, float]] = []
    for point_id, point_label, left_frac, right_frac in POINT_BANDS:
        left_x = float(reference_x[0]) + left_frac * float(reference_x[-1] - reference_x[0])
        right_x = float(reference_x[0]) + right_frac * float(reference_x[-1] - reference_x[0])
        mask = (reference_x >= left_x) & (reference_x <= right_x)
        if not np.any(mask):
            idx = int(np.argmax(combined_amplitude))
        else:
            local_indices = np.flatnonzero(mask)
            idx = int(local_indices[int(np.argmax(combined_amplitude[mask]))])
        selected.append((point_id, point_label, float(reference_x[idx])))
    return selected


def _write_head_point_figure_mixed(
    results: list[base.TransientResult],
    output_png: Path,
) -> list[dict[str, object]]:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)
    ordered = sorted(results, key=lambda item: SOLVER_ORDER.index(item.solver))
    point_specs = _select_informative_points_mixed(ordered)
    fig, axes = base.plt.subplots(4, 1, figsize=(11.0, 10.4), sharex=True, constrained_layout=True)

    recharge = np.asarray(RECHARGE_SERIES_MM_DAY, dtype=float)
    elapsed_days = ordered[0].elapsed_days
    axes[0].step(
        elapsed_days,
        recharge,
        where="mid",
        color="#444444",
        linewidth=2.0,
    )
    axes[0].set_ylabel("Recharge\n[mm/day]")
    axes[0].grid(alpha=0.25, linewidth=0.6)

    rows: list[dict[str, object]] = []
    for ax, (point_id, point_label, target_x_m) in zip(axes[1:], point_specs, strict=False):
        topo_value_m: float | None = None
        for item in ordered:
            idx = int(np.argmin(np.abs(np.asarray(item.x, dtype=float) - float(target_x_m))))
            x_value = float(np.asarray(item.x, dtype=float)[idx])
            head_series = np.asarray(item.head_profiles[:, idx], dtype=float)
            clearance_series = np.asarray(item.clearance_profiles[:, idx], dtype=float)
            ax.plot(
                item.elapsed_days,
                head_series,
                label=SOLVER_LABELS[item.solver],
                **base._comparison_plot_style(item.solver),
            )
            for t_day, head_m, clearance_m in zip(item.elapsed_days, head_series, clearance_series, strict=False):
                rows.append(
                    {
                        "point_id": point_id,
                        "point_label": point_label,
                        "x_m": x_value,
                        "solver": item.solver,
                        "solver_label": SOLVER_LABELS[item.solver],
                        "elapsed_days": float(t_day),
                        "head_m": float(head_m),
                        "clearance_m": float(clearance_m),
                    }
                )
            if topo_value_m is None:
                topo_value_m = float(np.asarray(item.topography_profile, dtype=float)[idx])
        if topo_value_m is not None:
            ax.axhline(
                topo_value_m,
                color="#222222",
                linewidth=1.2,
                linestyle="--",
                label="Topography" if point_id == point_specs[0][0] else None,
            )
        ax.set_ylabel("Head [m]")
        ax.set_title(f"{point_label} (x ~ {target_x_m:.0f} m)", fontsize=10.0)
        ax.grid(alpha=0.25, linewidth=0.6)

    axes[1].legend(loc="upper left", fontsize=8.8, frameon=False, ncols=4)
    axes[-1].set_xlabel("Time [days]")
    fig.suptitle("Recharge ramp then dry recovery: head time series at selected hillslope points", fontsize=11.0)
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    base.plt.close(fig)
    return rows


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a transient cross-model benchmark with a 10-degree sloping substratum."
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / "out" / "sih_sloping_substratum_10deg_20260413",
        help="Directory where the report and run artifacts are written.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=2400,
        help="Per-solver timeout in seconds.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_base_module()
    parser = _build_parser()
    args = parser.parse_args(argv)
    output_root = Path(args.output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    os.environ["HYDROMODPY_OUT_PATH"] = str(output_root)

    runtime_configs_dir = output_root / "runtime_configs"
    results: list[base.TransientResult] = []

    t0 = time.perf_counter()
    nwt_result = _run_structured_modflow(
        solver_name="modflownwt",
        timeout=int(args.timeout),
        runtime_configs_dir=runtime_configs_dir,
    )
    results.append(base._build_result(nwt_result, wall_time_seconds=time.perf_counter() - t0))

    t0 = time.perf_counter()
    mf6_structured_result = _run_structured_modflow(
        solver_name="modflow6",
        timeout=int(args.timeout),
        runtime_configs_dir=runtime_configs_dir,
    )
    results.append(
        base._build_result(
            mf6_structured_result,
            wall_time_seconds=time.perf_counter() - t0,
        )
    )

    t0 = time.perf_counter()
    mf6_result = _run_mf6_irregular(timeout=int(args.timeout), runtime_configs_dir=runtime_configs_dir)
    results.append(base._build_result(mf6_result, wall_time_seconds=time.perf_counter() - t0))

    t0 = time.perf_counter()
    bouss_result = _run_boussinesq_irregular(timeout=int(args.timeout))
    results.append(base._build_result(bouss_result, wall_time_seconds=time.perf_counter() - t0))

    timeseries_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []
    execution_rows: list[dict[str, object]] = []
    for item in sorted(results, key=lambda row: SOLVER_ORDER.index(row.solver)):
        for idx, day in enumerate(item.elapsed_days.tolist()):
            row: dict[str, object] = {
                "solver": item.solver,
                "solver_label": SOLVER_LABELS[item.solver],
                "elapsed_days": float(day),
                "recharge_mm_day": float(RECHARGE_SERIES_MM_DAY[idx]),
                "recharge_flux_m3_day": float(item.recharge_flux_m3_day[idx]),
                "drainage_flux_m3_day": float(item.drainage_flux_m3_day[idx]),
                "east_boundary_outflow_m3_day": float(item.east_boundary_outflow_m3_day[idx]),
                "total_outflow_m3_day": float(item.total_outflow_m3_day[idx]),
                "storage_balance_m3_day": float(item.storage_balance_m3_day[idx]),
                "max_clearance_m": float(np.max(item.clearance_profiles[idx])),
            }
            if item.bouss_surface_flux_m3_day is not None:
                row["surface_excess_flux_m3_day"] = float(item.bouss_surface_flux_m3_day[idx])
            if item.accumulation_proxy_m3_day is not None:
                row["accumulation_proxy_m3_day"] = float(item.accumulation_proxy_m3_day[idx])
            timeseries_rows.append(row)
        summary_rows.append(
            {
                "solver": item.solver,
                "solver_label": SOLVER_LABELS[item.solver],
                "onset_day": item.onset_day,
                "peak_drainage_flux_m3_day": item.peak_drainage_flux_m3_day,
                "peak_drainage_day": item.peak_drainage_day,
                "peak_total_outflow_m3_day": item.peak_total_outflow_m3_day,
                "peak_total_outflow_day": item.peak_total_outflow_day,
                "max_clearance_m": item.max_clearance_m,
                "wall_time_seconds": item.wall_time_seconds,
                "results_dir": str(item.out_path),
                "postprocess_dir": str(item.postprocess_dir),
            }
        )
        execution_rows.append(
            {
                "solver": item.solver,
                "solver_label": SOLVER_LABELS[item.solver],
                "wall_time_seconds": item.wall_time_seconds,
                "results_dir": str(item.out_path),
            }
        )

    base._write_csv(output_root / "timeseries.csv", timeseries_rows)
    base._write_csv(output_root / "summary_metrics.csv", summary_rows)
    base._write_csv(output_root / "execution_times.csv", execution_rows)

    figures_dir = output_root / "figures"
    base._write_head_snapshots(results, figures_dir / "head_snapshots.png")
    base._write_flux_figure(results, figures_dir / "flux_timeseries.png")
    base._write_total_outflow_overlay_figure(results, figures_dir / "total_outflow_overlay.png")
    base._write_outflow_components_figure(results, figures_dir / "outflow_components.png")
    base._write_flux_budget_figure(results, figures_dir / "flux_budget_comparison.png")
    base._write_execution_times_figure(results, figures_dir / "execution_times.png")
    head_point_rows = _write_head_point_figure_mixed(results, figures_dir / "head_point_timeseries.png")
    base._write_csv(output_root / "head_point_timeseries.csv", head_point_rows)
    _write_summary(results, output_root / "summary.md", figures_dir)
    (output_root / "summary.json").write_text(
        json.dumps(
            {
                "summary_md": str(output_root / "summary.md"),
                "timeseries_csv": str(output_root / "timeseries.csv"),
                "head_point_timeseries_csv": str(output_root / "head_point_timeseries.csv"),
                "summary_metrics_csv": str(output_root / "summary_metrics.csv"),
                "execution_times_csv": str(output_root / "execution_times.csv"),
                "total_outflow_overlay_png": str(figures_dir / "total_outflow_overlay.png"),
                "figures_dir": str(figures_dir),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
