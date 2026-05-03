"""Transient cross-solver hillslope investigation with a progressive recharge ramp."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]

from hydromodpy.core.config.toml_loader import merge_toml_payloads
from hydromodpy.physics.flow.history_contract import write_time_series_npy
from hydromodpy.results.derived import (
    drain_budget_to_positive_outflow,
    find_drain_budget_key,
)
from tools.surface_interaction_reporting import (
    write_csv as reporting_write_csv,
)
from tools.surface_interaction_reporting import (
    write_execution_times_figure as reporting_write_execution_times_figure,
)
from tools.surface_interaction_reporting import (
    write_flux_budget_figure as reporting_write_flux_budget_figure,
)
from tools.surface_interaction_reporting import (
    write_flux_figure as reporting_write_flux_figure,
)
from tools.surface_interaction_reporting import (
    write_head_point_figure as reporting_write_head_point_figure,
)
from tools.surface_interaction_reporting import (
    write_head_snapshots as reporting_write_head_snapshots,
)
from tools.surface_interaction_reporting import (
    write_markdown_summary as reporting_write_markdown_summary,
)
from tools.surface_interaction_reporting import (
    write_outflow_components_figure as reporting_write_outflow_components_figure,
)
from tools.surface_interaction_reporting import (
    write_total_outflow_overlay_figure as reporting_write_total_outflow_overlay_figure,
)
from validation_cases.analytical.steady.boussinesq_piecewise import mm_day_to_m_s
from validation_cases.analytical.steady.linearized_unconfined_hillslope_drainage_1d.reference import (
    build_linear_topography_values,
)
from validation_cases.shared import (
    ValidationRunResult,
    align_snapshot_series_to_expected_count,
    load_case_config,
    load_case_metadata,
    load_npy_time_series_arrays,
    load_npy_time_series_arrays_with_elapsed_seconds,
)
from validation_cases.shared.boussinesq_budget import (
    compute_free_control_volume_budget,
)
from validation_cases.shared.boussinesq_uniform_strip import (
    run_boussinesq_uniform_strip_case,
)
from validation_cases.shared.gmsh_irregular_strip import write_irregular_strip_bundle
from validation_cases.shared.runtime import (
    _dump_toml,
    _discover_result_store,
    remove_tree_with_retry,
    resolve_model_workspace,
    resolve_validation_results_dir,
    run_example_script,
)

CASE_DIR = (
    REPO_ROOT
    / "validation_cases"
    / "analytical"
    / "steady"
    / "linearized_unconfined_hillslope_drainage_1d"
)
LAUNCHER_SCRIPT = (
    REPO_ROOT / "examples" / "projects" / "launcher_simulation" / "launcher_simulation.py"
)
SOLVER_ORDER = (
    "modflownwt",
    "modflow6",
    "modflow6_irregular_tri",
    "boussinesq",
    "petsc_partition",
    "petsc",
)
SOLVER_LABELS = {
    "modflownwt": "MODFLOW-NWT",
    "modflow6": "MODFLOW 6",
    "modflow6_irregular_tri": "MODFLOW 6 irregular triangles",
    "boussinesq": "Boussinesq",
    "petsc_partition": "Boussinesq PETSc partition",
    "petsc": "Boussinesq PETSc complementarity",
}
SOLVER_COLORS = {
    "modflownwt": "#1f77b4",
    "modflow6": "#ff7f0e",
    "modflow6_irregular_tri": "#9467bd",
    "boussinesq": "#2ca02c",
    "petsc_partition": "#17becf",
    "petsc": "#d62728",
}
BOUSS_NX = 40
BOUSS_NY = 3
IRREGULAR_TRI_NX_SEED = 10
IRREGULAR_TRI_NY_SEED = 3
IRREGULAR_TRI_SEED = 20260413
LENGTH_X_M = 400.0
WIDTH_Y_M = 30.0
TOPOGRAPHY_BASE_ELEVATION_M = 5.0
TOPOGRAPHY_RIGHT_TO_LEFT_AMPLITUDE_M = 5.0
AQUIFER_THICKNESS_M = 20.0
EAST_HEAD_M = TOPOGRAPHY_BASE_ELEVATION_M + (
    TOPOGRAPHY_RIGHT_TO_LEFT_AMPLITUDE_M / (2.0 * BOUSS_NX)
)
INITIAL_HEAD_M = EAST_HEAD_M
HYDRAULIC_CONDUCTIVITY_SCALE = 0.2
SPECIFIC_YIELD = 0.10
SPECIFIC_STORAGE_M_INV = 1.0e-10
DRAINAGE_CONDUCTANCE_M2_S = 1.0e-4
DT_DAYS = 15.0
YEAR_1_RECHARGE_SERIES_MM_DAY_30D = (
    0.6,
    1.8,
    3.0,
    4.2,
    5.4,
    7.2,
    6.0,
    4.8,
    3.6,
    2.4,
    1.2,
    0.6,
)
YEAR_1_RECHARGE_SERIES_MM_DAY = tuple(
    value for value in YEAR_1_RECHARGE_SERIES_MM_DAY_30D for _ in range(2)
)
DRY_RECOVERY_PERIODS = 24
RECHARGE_SERIES_MM_DAY = YEAR_1_RECHARGE_SERIES_MM_DAY + (0.0,) * DRY_RECOVERY_PERIODS
SNAPSHOT_DAYS = (30.0, 180.0, 360.0, 450.0, 540.0, 720.0)
POINT_BANDS = (
    ("upper_slope", "Upper slope", 0.00, 1.0 / 3.0),
    ("mid_slope", "Mid slope", 1.0 / 3.0, 2.0 / 3.0),
    ("near_toe", "Near toe", 2.0 / 3.0, 1.0),
)
CONTACT_TOLERANCE_M = 0.02
SECONDS_PER_DAY = 86_400.0


def _comparison_plot_style(solver: str) -> dict[str, Any]:
    if solver == "modflownwt":
        return {
            "color": SOLVER_COLORS[solver],
            "linestyle": "None",
            "linewidth": 0.0,
            "marker": "o",
            "markersize": 4.2,
            "markerfacecolor": SOLVER_COLORS[solver],
            "markeredgecolor": SOLVER_COLORS[solver],
            "markeredgewidth": 0.0,
            "markevery": 1,
            "zorder": 5,
        }
    if solver == "modflow6":
        return {
            "color": SOLVER_COLORS[solver],
            "linewidth": 2.2,
            "zorder": 3,
        }
    if solver == "petsc":
        return {
            "color": SOLVER_COLORS[solver],
            "linewidth": 2.0,
            "linestyle": "--",
            "zorder": 4,
        }
    return {
        "color": SOLVER_COLORS[solver],
        "linewidth": 2.0,
        "zorder": 4,
    }


def _recharge_total_flux_m3_day() -> np.ndarray:
    area_m2 = float(LENGTH_X_M) * float(WIDTH_Y_M)
    recharge_m_day = np.asarray(RECHARGE_SERIES_MM_DAY, dtype=float) / 1000.0
    return recharge_m_day * area_m2


def _hydraulic_conductivity_scale_from_args(args: argparse.Namespace) -> float:
    return float(getattr(args, "hydraulic_conductivity_scale", HYDRAULIC_CONDUCTIVITY_SCALE))


def _topography_base_elevation_from_args(args: argparse.Namespace) -> float:
    return float(TOPOGRAPHY_BASE_ELEVATION_M) + float(getattr(args, "topography_offset_m", 0.0))


@dataclass(frozen=True, slots=True)
class TransientResult:
    solver: str
    out_path: Path
    postprocess_dir: Path
    elapsed_days: np.ndarray
    x: np.ndarray
    topography_profile: np.ndarray
    head_profiles: np.ndarray
    clearance_profiles: np.ndarray
    drainage_flux_m3_day: np.ndarray
    east_boundary_inflow_m3_day: np.ndarray
    east_boundary_outflow_m3_day: np.ndarray
    total_inflow_m3_day: np.ndarray
    total_outflow_m3_day: np.ndarray
    recharge_flux_m3_day: np.ndarray
    net_inflow_m3_day: np.ndarray
    storage_change_m3_day: np.ndarray
    residual_m3_day: np.ndarray
    max_clearance_m: float
    onset_day: float
    peak_drainage_flux_m3_day: float
    peak_drainage_day: float
    peak_total_outflow_m3_day: float
    peak_total_outflow_day: float
    bouss_surface_flux_m3_day: np.ndarray | None = None
    accumulation_proxy_m3_day: np.ndarray | None = None
    wall_time_seconds: float | None = None

    @property
    def storage_balance_m3_day(self) -> np.ndarray:
        return self.storage_change_m3_day


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value.lower()).strip("_")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    reporting_write_csv(path, rows)


def _align_series_lengths(reference: np.ndarray, *series: np.ndarray) -> tuple[np.ndarray, ...]:
    arrays = [np.asarray(reference, dtype=float).reshape(-1)]
    arrays.extend(np.asarray(item, dtype=float).reshape(-1) for item in series)
    expected = int(arrays[0].size)
    mismatches = [array.size for array in arrays[1:] if int(array.size) != expected]
    if mismatches:
        raise ValueError(
            "Transient comparison series must already be aligned before plotting. "
            f"Expected {expected} rows for every series, got {mismatches}."
        )
    return tuple(np.asarray(array, dtype=float) for array in arrays)


def _load_case_payload_for_solver(metadata: dict[str, Any], solver: str) -> dict[str, Any]:
    config_files = dict(metadata.get("config_files", {}))
    config_name = str(config_files[solver])
    base_config_name = str(metadata.get("base_config", "")).strip()
    if base_config_name and config_name != base_config_name:
        base_payload = load_case_config(CASE_DIR, base_config_name)
        solver_payload = load_case_config(CASE_DIR, config_name)
        return merge_toml_payloads(base_payload, solver_payload)
    return load_case_config(CASE_DIR, config_name)


def _transient_end_datetime() -> str:
    total_days = int(len(RECHARGE_SERIES_MM_DAY) * DT_DAYS)
    start = datetime(2003, 1, 1, 0, 0, 0)
    end_inclusive = start + timedelta(days=total_days - 1)
    return end_inclusive.strftime("%Y-%m-%d %H:%M:%S")


def _apply_transient_payload(
    payload: dict[str, Any],
    *,
    solver: str,
    hydraulic_conductivity_m_s: float,
    topography_base_elevation_m: float = TOPOGRAPHY_BASE_ELEVATION_M,
    run_variant: str | None = None,
) -> dict[str, Any]:
    run_token = solver if run_variant is None else str(run_variant)
    run_id = f"hillslope_surface_transient_{run_token}"
    geographic = dict(payload.get("geographic", {}))
    geographic_synthetic = dict(geographic.get("synthetic", {}))
    geographic_synthetic["case_id"] = f"val_hillslope_surface_transient_{run_token}"
    geographic_synthetic["grid"] = {
        "length_x": f"{LENGTH_X_M:.1f} m",
        "length_y": f"{WIDTH_Y_M:.1f} m",
        "nx": BOUSS_NX,
        "ny": BOUSS_NY,
    }
    geographic_synthetic["topography"] = {
        "kind": "linear",
        "base_elevation": float(topography_base_elevation_m),
        "right_to_left_amplitude": TOPOGRAPHY_RIGHT_TO_LEFT_AMPLITUDE_M,
    }
    geographic["synthetic"] = geographic_synthetic

    domain = dict(payload.get("domain", {}))
    domain["depth_model"] = {
        "type": "constant_thickness",
        "thickness": f"{AQUIFER_THICKNESS_M:.1f} m",
    }

    flow = dict(payload.get("flow", {}))
    param = dict(flow.get("param", {}))
    param_k = dict(param.get("K", {}))
    param_k["field"] = {"id": "K", "kind": "homogeneous"}
    param_k["field_homogeneous"] = {"value": f"{hydraulic_conductivity_m_s:.12g} m/s"}
    param_ss = dict(param.get("Ss", {}))
    param_ss["field"] = {"id": "Ss", "kind": "homogeneous"}
    param_ss["field_homogeneous"] = {"value": f"{SPECIFIC_STORAGE_M_INV:.12g} m-1"}
    param_sy = dict(param.get("Sy", {}))
    param_sy["field"] = {"id": "Sy", "kind": "homogeneous"}
    param_sy["field_homogeneous"] = {"value": f"{SPECIFIC_YIELD:.12g} -"}
    param["K"] = param_k
    param["Ss"] = param_ss
    param["Sy"] = param_sy
    flow["param"] = param
    flow["param_list"] = ["K", "Ss", "Sy"]
    flow["flow_regime"] = "transient"
    flow["active_sinks_sources"] = ["recharge"]
    flow["active_bc"] = ["east_side", "drainage"]
    flow["ic"] = {"type": "custom", "value": f"{INITIAL_HEAD_M:.6f} m"}
    flow["sinks_sources"] = {"recharge": {"first_clim": "first"}}

    bc = dict(flow.get("bc", {}))
    dirichlet = dict(bc.get("dirichlet", {}))
    cauchy = dict(bc.get("cauchy", {}))
    dirichlet.pop("west_side", None)
    dirichlet["east_side"] = {
        **dict(dirichlet.get("east_side", {})),
        "type": "dirichlet",
        "value": f"{EAST_HEAD_M:.6f} m",
    }
    cauchy["drainage"] = {
        **dict(cauchy.get("drainage", {})),
        "application_domain": "top",
        "type": "cauchy",
        "value": f"{DRAINAGE_CONDUCTANCE_M2_S:.12g} m2/s",
    }
    bc["dirichlet"] = dirichlet
    bc["cauchy"] = cauchy
    flow["bc"] = bc

    data = dict(payload.get("data", {}))
    data["types"] = ["recharge"]
    data["inference_mode"] = "warn"
    data["recharge"] = {
        "sources": [
            {
                "source": "synthetic",
                "values": [float(value) for value in RECHARGE_SERIES_MM_DAY],
                "freq": f"{int(DT_DAYS)}D",
                "runoff_ratio": 0.0,
            }
        ]
    }

    simulation = dict(payload.get("simulation", {}))
    simulation["run_id"] = run_id
    simulation["name"] = f"Transient hillslope surface interaction {run_token}"
    simulation["description"] = (
        "West divide, east fixed head, progressive recharge ramp, top drainage."
    )
    simulation["time"] = {
        "start_datetime": "2003-01-01 00:00:00",
        "end_datetime": _transient_end_datetime(),
        "step_value": f"{int(DT_DAYS)} day",
        "coverage_policy": "ignore",
    }
    simulation_results = dict(simulation.get("results", {}))
    derived_results = dict(simulation_results.get("derived", {}))
    derived_results.update(
        {
            "watertable_elevation": True,
            "watertable_depth": True,
            "seepage_areas": True,
            "accumulation_flux": False,
            "outflow_drain": True,
        }
    )
    simulation_results["derived"] = derived_results
    simulation["results"] = simulation_results

    payload["simulation"] = simulation
    payload["geographic"] = geographic
    payload["domain"] = domain
    payload["flow"] = flow
    payload["data"] = data

    solver_section = dict(payload.get(solver, {}))
    solver_sgrid = dict(solver_section.get("sgrid", {}))
    solver_sgrid["planar"] = {
        "mode": "resample_to_shape",
        "nx": BOUSS_NX,
        "ny": BOUSS_NY,
        "resampling": "nearest",
    }
    solver_sgrid["vertical"] = {"nlay": 1}
    solver_section["sgrid"] = solver_sgrid
    solver_section["tgrid"] = {"firstpersteady": False}
    payload[solver] = solver_section
    return payload


def _catalog_structured_shape(store: Any, sim_id: str) -> tuple[int, int] | None:
    try:
        geographic_metadata = store.read_geographic_metadata(sim_id)
        nrow = int(float(geographic_metadata.get("nrow", 0)))
        ncol = int(float(geographic_metadata.get("ncol", 0)))
    except Exception:
        return None
    if nrow <= 0 or ncol <= 0:
        return None
    return nrow, ncol


def _catalog_array(store: Any, sim_id: str, field_name: str) -> np.ndarray:
    grp = store.open_zarr_group(sim_id)
    for loc in (grp, grp.get("derived"), grp.get("budget")):
        if loc is not None and field_name in loc:
            return np.asarray(loc[field_name][:], dtype=float)
    raise KeyError(f"SimulationCatalog field not found: {field_name}")


def _catalog_drain_outflow_history(store: Any, sim_id: str) -> np.ndarray:
    grp = store.open_zarr_group(sim_id)
    budget_grp = grp.get("budget")
    if budget_grp is None:
        raise KeyError("SimulationCatalog budget group not found.")
    drn_key = find_drain_budget_key(budget_grp)
    if drn_key is None:
        raise KeyError("SimulationCatalog drain budget field not found.")

    drain_budget = np.asarray(budget_grp[drn_key][:], dtype=float)
    head = np.asarray(grp["head"][:], dtype=float)
    n_cells = int(head.shape[-1])
    return np.stack(
        [
            drain_budget_to_positive_outflow(drain_budget[t], n_cells=n_cells)
            for t in range(int(drain_budget.shape[0]))
        ],
        axis=0,
    )


def _legacy_spatial_history_from_catalog(
    store: Any,
    sim_id: str,
    field_name: str,
) -> np.ndarray:
    try:
        data = _catalog_array(store, sim_id, field_name)
    except KeyError:
        if field_name not in {"accumulation_flux", "outflow_drain"}:
            raise
        data = _catalog_drain_outflow_history(store, sim_id)
    if data.ndim == 3 and data.shape[1] == 1:
        data = data[:, 0, :]

    structured_shape = _catalog_structured_shape(store, sim_id)
    if structured_shape is None or data.ndim != 2:
        return np.asarray(data, dtype=float)

    nrow, ncol = structured_shape
    if int(data.shape[1]) != nrow * ncol:
        return np.asarray(data, dtype=float)
    return np.asarray(data, dtype=float).reshape(int(data.shape[0]), nrow, ncol)


def _constant_head_outflow_from_catalog(
    store: Any,
    sim_id: str,
    *,
    n_steps: int,
) -> np.ndarray:
    budgets = store.query_budget(sim_id)
    values = np.zeros(int(n_steps), dtype=float)
    if budgets.empty:
        return values

    component = budgets["component"].astype(str).str.lower()
    constant_head = budgets.loc[component.isin(("constant head", "chd"))]
    if constant_head.empty:
        return values

    grouped = constant_head.groupby("timestep", sort=True)["flux_out"].sum()
    for timestep, flux_out in grouped.items():
        index = int(timestep)
        if 0 <= index < values.size:
            values[index] = float(flux_out)
    return values


def _materialize_launcher_catalog_postprocess(
    *,
    store: Any,
    sim_id: str,
    out_path: Path,
) -> tuple[Path, Path]:
    postprocess_dir = out_path / "_postprocess"
    postprocess_dir.mkdir(parents=True, exist_ok=True)

    histories: dict[str, np.ndarray] = {}
    for field_name in ("watertable_elevation", "outflow_drain", "accumulation_flux"):
        histories[field_name] = _legacy_spatial_history_from_catalog(
            store,
            sim_id,
            field_name,
        )

    n_steps = int(histories["watertable_elevation"].shape[0])
    time_keys = np.arange(n_steps, dtype=int)
    elapsed_seconds = np.arange(1, n_steps + 1, dtype=float) * DT_DAYS * SECONDS_PER_DAY

    for field_name, values in histories.items():
        write_time_series_npy(
            postprocess_dir / f"{field_name}.npy",
            values,
            time_keys=time_keys,
            elapsed_seconds=elapsed_seconds,
        )

    write_time_series_npy(
        postprocess_dir / "outlet_discharge_east_side_m3_s.npy",
        _constant_head_outflow_from_catalog(store, sim_id, n_steps=n_steps),
        time_keys=time_keys,
        elapsed_seconds=elapsed_seconds,
    )

    particles_dir = postprocess_dir / "_particles"
    particles_dir.mkdir(parents=True, exist_ok=True)
    return postprocess_dir, particles_dir


def _run_launcher_solver(
    *,
    metadata: dict[str, Any],
    solver: str,
    solver_key: str | None = None,
    hydraulic_conductivity_m_s: float,
    topography_base_elevation_m: float,
    timeout: int,
    runtime_configs_dir: Path,
) -> ValidationRunResult:
    normalized_solver_key = solver if solver_key is None else str(solver_key).strip().lower()
    out_path = resolve_validation_results_dir(
        test_file=__file__,
        run_name=f"transient_{normalized_solver_key}",
    )
    if out_path.exists():
        remove_tree_with_retry(out_path)
    out_path.mkdir(parents=True, exist_ok=True)

    payload = _load_case_payload_for_solver(metadata, solver)
    payload = _apply_transient_payload(
        payload,
        solver=solver,
        hydraulic_conductivity_m_s=hydraulic_conductivity_m_s,
        topography_base_elevation_m=topography_base_elevation_m,
        run_variant=normalized_solver_key,
    )
    if normalized_solver_key == "modflow6_irregular_tri":
        bundle_dir = write_irregular_strip_bundle(
            out_path / "mesh_bundle",
            nx_seed=IRREGULAR_TRI_NX_SEED,
            ny_seed=IRREGULAR_TRI_NY_SEED,
            length_x_m=LENGTH_X_M,
            width_y_m=WIDTH_Y_M,
            z_top_m=lambda x_m: build_linear_topography_values(
                x_m=np.asarray(x_m, dtype=float),
                xmin=0.0,
                xmax=LENGTH_X_M,
                topography_base_elevation_m=float(topography_base_elevation_m),
                topography_right_to_left_amplitude_m=TOPOGRAPHY_RIGHT_TO_LEFT_AMPLITUDE_M,
            ),
            z_bottom_m=lambda x_m: (
                build_linear_topography_values(
                    x_m=np.asarray(x_m, dtype=float),
                    xmin=0.0,
                    xmax=LENGTH_X_M,
                    topography_base_elevation_m=float(topography_base_elevation_m),
                    topography_right_to_left_amplitude_m=TOPOGRAPHY_RIGHT_TO_LEFT_AMPLITUDE_M,
                )
                - AQUIFER_THICKNESS_M
            ),
            hydraulic_conductivity_m_s=hydraulic_conductivity_m_s,
            storage_coefficient=SPECIFIC_YIELD,
            seed=IRREGULAR_TRI_SEED,
        )
        payload["mesh_input"] = {
            "mesh_path": str((bundle_dir / "mesh_2d.msh").resolve()),
            "bundle_dir": str(bundle_dir.resolve()),
        }
        solver_section = dict(payload.get("modflow6", {}))
        solver_sgrid = dict(solver_section.get("sgrid", {}))
        solver_section["sgrid"] = {"vertical": dict(solver_sgrid.get("vertical", {}))}
        payload["modflow6"] = solver_section
    runtime_configs_dir.mkdir(parents=True, exist_ok=True)
    config_path = runtime_configs_dir / f"transient__{normalized_solver_key}.toml"
    config_path.write_text(_dump_toml(payload), encoding="utf-8", newline="\n")

    env = os.environ.copy()
    env["HYDROMODPY_OUT_PATH"] = str(out_path)
    env["HYDROMODPY_PROJECT_ROOT"] = str(out_path)
    env["HYDROMODPY_WORKSPACE"] = str(out_path)
    env.setdefault("MPLBACKEND", "Agg")
    completed = subprocess.run(
        [sys.executable, "-m", "hydromodpy", "run", str(config_path)],
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"Launcher run failed for {solver} with return code {completed.returncode}.\n"
            f"Stdout:\n{completed.stdout}\nStderr:\n{completed.stderr}"
        )

    store, sim_id = _discover_result_store(out_path)
    if store is not None and sim_id is not None:
        try:
            postprocess_dir, particles_dir = _materialize_launcher_catalog_postprocess(
                store=store,
                sim_id=sim_id,
                out_path=out_path,
            )
        finally:
            store.close()
        return ValidationRunResult(
            case_dir=CASE_DIR,
            solver_name=normalized_solver_key,
            out_path=out_path,
            model_ws=out_path,
            postprocess_dir=postprocess_dir,
            particles_dir=particles_dir,
            run_returncode=int(completed.returncode),
            run_stdout=str(completed.stdout),
            run_stderr=str(completed.stderr),
        )

    model_ws, postprocess_dir, particles_dir = resolve_model_workspace(
        out_path,
        results_folder_name=str(
            dict(metadata.get("workspace", {})).get("results_folder_name", "results_simulations")
        ),
    )
    return ValidationRunResult(
        case_dir=CASE_DIR,
        solver_name=normalized_solver_key,
        out_path=out_path,
        model_ws=model_ws,
        postprocess_dir=postprocess_dir,
        particles_dir=particles_dir,
        run_returncode=int(completed.returncode),
        run_stdout=str(completed.stdout),
        run_stderr=str(completed.stderr),
    )


def _run_boussinesq(
    *,
    solver_key: str = "boussinesq",
    hydraulic_conductivity_m_s: float,
    topography_base_elevation_m: float,
    timeout: int,
) -> ValidationRunResult:
    normalized_solver_key = str(solver_key).strip().lower()
    if normalized_solver_key not in {"boussinesq", "petsc_partition", "petsc"}:
        raise ValueError(f"Unsupported Boussinesq solver '{solver_key}'.")
    recharge_series_m_s = [mm_day_to_m_s(float(value)) for value in RECHARGE_SERIES_MM_DAY]
    runtime_backend = "local"
    surface_interaction_model = "regularized_partition"
    runtime_max_iterations = 80
    runtime_tol_residual_inf = 1.0e-7
    if normalized_solver_key == "petsc_partition":
        runtime_backend = "petsc"
        runtime_max_iterations = 300
        runtime_tol_residual_inf = 1.0e-6
    elif normalized_solver_key == "petsc":
        runtime_backend = "petsc"
        surface_interaction_model = "complementarity"
        runtime_max_iterations = 1000
        runtime_tol_residual_inf = 1.0e-6

    result = run_boussinesq_uniform_strip_case(
        case_dir=CASE_DIR,
        case_id=f"hillslope_surface_transient_{normalized_solver_key}",
        caller_file=__file__,
        timeout=timeout,
        nx=BOUSS_NX,
        ny=BOUSS_NY,
        nper=len(RECHARGE_SERIES_MM_DAY),
        dt_seconds=DT_DAYS * SECONDS_PER_DAY,
        length_x_m=LENGTH_X_M,
        width_y_m=WIDTH_Y_M,
        z_top_m=lambda x_m: build_linear_topography_values(
            x_m=np.asarray(x_m, dtype=float),
            xmin=0.0,
            xmax=LENGTH_X_M,
            topography_base_elevation_m=float(topography_base_elevation_m),
            topography_right_to_left_amplitude_m=TOPOGRAPHY_RIGHT_TO_LEFT_AMPLITUDE_M,
        ),
        z_bottom_m=lambda x_m: (
            build_linear_topography_values(
                x_m=np.asarray(x_m, dtype=float),
                xmin=0.0,
                xmax=LENGTH_X_M,
                topography_base_elevation_m=float(topography_base_elevation_m),
                topography_right_to_left_amplitude_m=TOPOGRAPHY_RIGHT_TO_LEFT_AMPLITUDE_M,
            )
            - AQUIFER_THICKNESS_M
        ),
        hydraulic_conductivity_m_s=hydraulic_conductivity_m_s,
        storage_coefficient=SPECIFIC_YIELD,
        flow_section={
            "runtime_backend": runtime_backend,
            "surface_interaction_model": surface_interaction_model,
            "flow_regime": "transient",
            "runtime_max_iterations": runtime_max_iterations,
            "runtime_tol_residual_inf": runtime_tol_residual_inf,
            "ic": {"type": "custom", "value": INITIAL_HEAD_M},
            "active_sinks_sources": ["recharge"],
            "active_bc": ["east_side", "drainage"],
            "sinks_sources": {
                "recharge": {
                    "values": recharge_series_m_s,
                    "first_clim": "first",
                    "units": "m/s",
                }
            },
            "bc": {
                "dirichlet": {
                    "east_side": {
                        "type": "dirichlet",
                        "value": EAST_HEAD_M,
                    }
                },
                "cauchy": {
                    "drainage": {
                        "application_domain": "top",
                        "type": "cauchy",
                        "value": DRAINAGE_CONDUCTANCE_M2_S,
                    }
                },
            },
        },
        plan_name="Transient hillslope surface interaction",
        plan_description="Progressive recharge ramp on a sloping strip with top drainage.",
        flow_regime="transient",
    )
    return ValidationRunResult(
        case_dir=result.case_dir,
        solver_name=normalized_solver_key,
        out_path=result.out_path,
        model_ws=result.model_ws,
        postprocess_dir=result.postprocess_dir,
        particles_dir=result.particles_dir,
        run_returncode=result.run_returncode,
        run_stdout=result.run_stdout,
        run_stderr=result.run_stderr,
    )


def _elapsed_days_from_steps(n_steps: int) -> np.ndarray:
    return np.arange(1, int(n_steps) + 1, dtype=float) * DT_DAYS


def _load_bundle_cell_centroids(bundle_dir: Path) -> tuple[np.ndarray, np.ndarray]:
    cells = np.genfromtxt(
        bundle_dir / "cells.csv",
        delimiter=",",
        names=True,
        dtype=None,
        encoding="utf-8",
    )
    return (
        np.asarray(cells["centroid_x"], dtype=float).reshape(-1),
        np.asarray(cells["centroid_y"], dtype=float).reshape(-1),
    )


def _load_boussinesq_east_boundary_edge_mask(bundle_dir: Path) -> np.ndarray:
    nodes = np.genfromtxt(
        bundle_dir / "nodes.csv",
        delimiter=",",
        names=True,
        dtype=None,
        encoding="utf-8",
    )
    edges = np.genfromtxt(
        bundle_dir / "edges.csv",
        delimiter=",",
        names=True,
        dtype=None,
        encoding="utf-8",
    )

    node_ids = np.asarray(nodes["node_id"], dtype=int).reshape(-1)
    node_x = np.asarray(nodes["x"], dtype=float).reshape(-1)
    edge_node_a = np.asarray(edges["node_a"], dtype=int).reshape(-1)
    edge_node_b = np.asarray(edges["node_b"], dtype=int).reshape(-1)
    edge_kind = np.asarray(edges["edge_kind"]).reshape(-1)

    node_x_by_id = {
        int(node_id): float(x_coord) for node_id, x_coord in zip(node_ids.tolist(), node_x.tolist())
    }
    midpoint_x = np.asarray(
        [
            0.5 * (node_x_by_id[int(node_a)] + node_x_by_id[int(node_b)])
            for node_a, node_b in zip(edge_node_a.tolist(), edge_node_b.tolist())
        ],
        dtype=float,
    )
    east_x = float(np.max(node_x)) if node_x.size else 0.0
    boundary_mask = np.asarray(edge_kind == "boundary", dtype=bool)
    east_mask = np.isclose(midpoint_x, east_x, atol=1.0e-9, rtol=0.0)
    return np.asarray(boundary_mask & east_mask, dtype=bool)


def _interpolate_bundle_history_to_structured_grid(
    values: np.ndarray,
    *,
    bundle_dir: Path,
    nx: int,
    ny: int,
) -> np.ndarray:
    history = np.asarray(values, dtype=float)
    if history.ndim == 1:
        history = history.reshape(1, -1)
    if history.ndim != 2:
        raise ValueError("Bundle interpolation expects a time-cell history array.")

    centroid_x, centroid_y = _load_bundle_cell_centroids(bundle_dir)
    if history.shape[1] != centroid_x.size:
        raise ValueError(
            f"History cell count {history.shape[1]} does not match bundle cell count {centroid_x.size}."
        )

    dx = float(LENGTH_X_M) / float(nx)
    dy = float(WIDTH_Y_M) / float(ny)
    x_centers = (np.arange(int(nx), dtype=float) + 0.5) * dx
    y_centers = (np.arange(int(ny), dtype=float) + 0.5) * dy
    nearest_indices = np.zeros((int(ny), int(nx)), dtype=int)
    for row_idx, y_center in enumerate(y_centers):
        for col_idx, x_center in enumerate(x_centers):
            squared_distance = (centroid_x - float(x_center)) ** 2 + (
                centroid_y - float(y_center)
            ) ** 2
            nearest_indices[row_idx, col_idx] = int(np.argmin(squared_distance))
    return history[:, nearest_indices].reshape(history.shape[0], int(ny), int(nx))


def _integrate_structured_flux_m3_day(
    values: np.ndarray, *, dx_m: float, dy_m: float
) -> np.ndarray:
    data = np.asarray(values, dtype=float)
    if data.ndim != 3:
        raise ValueError("Structured flux integration expects a time-y-x array.")
    # MODFLOW postprocess flux rasters are already cell-integrated flows in m3/s.
    _ = (dx_m, dy_m)
    return np.sum(np.nan_to_num(data, nan=0.0), axis=(1, 2), dtype=float) * SECONDS_PER_DAY


def _load_scalar_series_m3_day(postprocess_dir: Path, observable_name: str) -> np.ndarray:
    _, values = load_npy_time_series_arrays(postprocess_dir, observable_name)
    data = np.asarray(values, dtype=float)
    if data.ndim == 1:
        series_m3_s = data
    elif data.ndim == 2 and data.shape[1] == 1:
        series_m3_s = data[:, 0]
    else:
        raise ValueError(
            f"{observable_name}.npy must contain one scalar value per timestep, got {data.shape}."
        )
    return np.asarray(series_m3_s, dtype=float) * SECONDS_PER_DAY


def _align_step_history(values: np.ndarray, *, n_steps: int) -> np.ndarray:
    data = np.asarray(values, dtype=float)
    if data.ndim == 1:
        data = data.reshape(-1, 1)
    if data.shape[0] == int(n_steps) + 1:
        return data[1:]
    if data.shape[0] == int(n_steps):
        return data
    if data.shape[0] > int(n_steps):
        return data[-int(n_steps) :]
    raise ValueError(f"History has {data.shape[0]} steps but {n_steps} were expected.")


def _compute_structured_storage_change_flux_m3_day(
    head_grids: np.ndarray,
    *,
    initial_head_m: float,
    storage_coefficient: float,
    dt_days: float,
) -> np.ndarray:
    grids = np.asarray(head_grids, dtype=float)
    if grids.ndim != 3:
        raise ValueError("Structured storage change expects a time-y-x head grid.")
    cell_area_m2 = (float(LENGTH_X_M) * float(WIDTH_Y_M)) / float(grids.shape[1] * grids.shape[2])
    previous = np.full_like(grids[0], float(initial_head_m), dtype=float)
    storage_change_flux_m3_day = np.zeros(grids.shape[0], dtype=float)
    for idx, current in enumerate(grids):
        delta_storage_m3 = float(
            np.sum(
                (np.asarray(current, dtype=float) - previous)
                * cell_area_m2
                * float(storage_coefficient)
            )
        )
        storage_change_flux_m3_day[idx] = delta_storage_m3 / float(dt_days)
        previous = np.asarray(current, dtype=float)
    return storage_change_flux_m3_day


def _select_snapshot_indices(
    elapsed_days: np.ndarray, snapshot_days: tuple[float, ...]
) -> list[int]:
    times = np.asarray(elapsed_days, dtype=float).reshape(-1)
    selected: list[int] = []
    for day in snapshot_days:
        idx = int(np.argmin(np.abs(times - float(day))))
        if idx not in selected:
            selected.append(idx)
    return sorted(selected)


def _first_contact_day(clearance_profiles: np.ndarray, *, elapsed_days: np.ndarray) -> float:
    mask = np.any(np.asarray(clearance_profiles, dtype=float) >= -CONTACT_TOLERANCE_M, axis=1)
    if not np.any(mask):
        return float("nan")
    elapsed = np.asarray(elapsed_days, dtype=float).reshape(-1)
    if elapsed.size != mask.size:
        raise ValueError("clearance_profiles and elapsed_days must share the same time length.")
    return float(elapsed[int(np.argmax(mask))])


def _build_result(
    result: ValidationRunResult,
    *,
    hydraulic_conductivity_scale: float,
    topography_base_elevation_m: float,
    wall_time_seconds: float | None = None,
) -> TransientResult:
    period_indices, heads, explicit_elapsed_seconds = (
        load_npy_time_series_arrays_with_elapsed_seconds(
            result.postprocess_dir,
            "watertable_elevation",
        )
    )
    del period_indices
    heads = np.asarray(heads, dtype=float)
    if heads.ndim == 3:
        head_grids = heads
    elif heads.ndim == 2:
        head_grids = _interpolate_bundle_history_to_structured_grid(
            heads,
            bundle_dir=result.out_path / "mesh_bundle",
            nx=BOUSS_NX,
            ny=BOUSS_NY,
        )
    else:
        raise ValueError("Expected watertable_elevation to be a time-y-x or time-cell array.")
    head_profiles = np.mean(head_grids, axis=1)
    if explicit_elapsed_seconds is None:
        elapsed_days = _elapsed_days_from_steps(head_profiles.shape[0])
    else:
        elapsed_days = np.asarray(explicit_elapsed_seconds, dtype=float) / SECONDS_PER_DAY
    dx = LENGTH_X_M / float(head_profiles.shape[1])
    x = (np.arange(head_profiles.shape[1], dtype=float) + 0.5) * dx
    topography_profile = build_linear_topography_values(
        x_m=x,
        xmin=0.0,
        xmax=LENGTH_X_M,
        topography_base_elevation_m=float(topography_base_elevation_m),
        topography_right_to_left_amplitude_m=TOPOGRAPHY_RIGHT_TO_LEFT_AMPLITUDE_M,
    )
    clearance_profiles = head_profiles - topography_profile[None, :]

    bouss_surface_flux_m3_day: np.ndarray | None = None
    accumulation_proxy_m3_day: np.ndarray | None = None
    storage_change_m3_day: np.ndarray
    east_boundary_inflow_m3_day: np.ndarray
    recharge_flux_m3_day: np.ndarray
    if result.solver_name in {"boussinesq", "petsc_partition", "petsc"}:
        bundle_dir = result.out_path / "mesh_bundle"
        with np.load(result.model_ws / "_boussinesq_state_history.npz") as payload:
            state_history = {key: np.asarray(payload[key]) for key in payload.files}
        budget = compute_free_control_volume_budget(
            bundle_dir=bundle_dir,
            state_history=state_history,
            seconds_per_day=SECONDS_PER_DAY,
            dt_days=DT_DAYS,
        )
        recharge_flux_m3_day = budget.recharge_flux_m3_day
        drainage_flux_m3_day = budget.drainage_flux_m3_day
        bouss_surface_flux_m3_day = budget.surface_excess_flux_m3_day
        east_boundary_inflow_m3_day = budget.east_boundary_inflow_m3_day
        east_boundary_outflow_m3_day = budget.east_boundary_outflow_m3_day
        storage_change_m3_day = budget.storage_change_m3_day
        _time_keys, head_grids, explicit_elapsed_seconds = align_snapshot_series_to_expected_count(
            np.arange(head_grids.shape[0], dtype=int),
            head_grids,
            explicit_elapsed_seconds,
            expected_count=int(storage_change_m3_day.size),
            name="watertable_elevation",
        )
        head_profiles = np.mean(np.asarray(head_grids, dtype=float), axis=1)
        elapsed_days = (
            _elapsed_days_from_steps(head_profiles.shape[0])
            if explicit_elapsed_seconds is None
            else np.asarray(explicit_elapsed_seconds, dtype=float) / SECONDS_PER_DAY
        )
        clearance_profiles = head_profiles - topography_profile[None, :]
    else:
        _, outflow_drain = load_npy_time_series_arrays(result.postprocess_dir, "outflow_drain")
        outflow_drain = np.asarray(outflow_drain, dtype=float)
        if outflow_drain.ndim == 2:
            drainage_flux_m3_day = (
                np.sum(np.nan_to_num(outflow_drain, nan=0.0), axis=1, dtype=float) * SECONDS_PER_DAY
            )
        else:
            drainage_flux_m3_day = _integrate_structured_flux_m3_day(
                outflow_drain,
                dx_m=LENGTH_X_M / float(BOUSS_NX),
                dy_m=WIDTH_Y_M / float(BOUSS_NY),
            )
        east_boundary_inflow_m3_day = np.zeros_like(drainage_flux_m3_day, dtype=float)
        east_boundary_outflow_m3_day = _load_scalar_series_m3_day(
            result.postprocess_dir,
            "outlet_discharge_east_side_m3_s",
        )
        _, accumulation_flux = load_npy_time_series_arrays(
            result.postprocess_dir, "accumulation_flux"
        )
        accumulation_flux = np.asarray(accumulation_flux, dtype=float)
        if accumulation_flux.ndim == 2:
            accumulation_proxy_m3_day = (
                np.sum(np.nan_to_num(accumulation_flux, nan=0.0), axis=1, dtype=float)
                * SECONDS_PER_DAY
            )
        else:
            accumulation_proxy_m3_day = _integrate_structured_flux_m3_day(
                accumulation_flux,
                dx_m=LENGTH_X_M / float(BOUSS_NX),
                dy_m=WIDTH_Y_M / float(BOUSS_NY),
            )
        storage_change_m3_day = _compute_structured_storage_change_flux_m3_day(
            head_grids,
            initial_head_m=INITIAL_HEAD_M,
            storage_coefficient=SPECIFIC_YIELD,
            dt_days=DT_DAYS,
        )
        recharge_flux_m3_day = _recharge_total_flux_m3_day()

    total_inflow_m3_day = np.asarray(
        recharge_flux_m3_day + east_boundary_inflow_m3_day,
        dtype=float,
    )
    total_outflow_m3_day = np.asarray(
        drainage_flux_m3_day + east_boundary_outflow_m3_day,
        dtype=float,
    )
    if bouss_surface_flux_m3_day is not None:
        total_outflow_m3_day = total_outflow_m3_day + np.asarray(
            bouss_surface_flux_m3_day,
            dtype=float,
        )
    net_inflow_m3_day = np.asarray(
        total_inflow_m3_day - total_outflow_m3_day,
        dtype=float,
    )
    (
        elapsed_days,
        drainage_flux_m3_day,
        east_boundary_inflow_m3_day,
        east_boundary_outflow_m3_day,
        total_inflow_m3_day,
        total_outflow_m3_day,
        recharge_flux_m3_day,
        net_inflow_m3_day,
        storage_change_m3_day,
    ) = _align_series_lengths(
        elapsed_days,
        drainage_flux_m3_day,
        east_boundary_inflow_m3_day,
        east_boundary_outflow_m3_day,
        total_inflow_m3_day,
        total_outflow_m3_day,
        recharge_flux_m3_day,
        net_inflow_m3_day,
        storage_change_m3_day,
    )
    head_profiles = np.asarray(head_profiles[: elapsed_days.size], dtype=float)
    clearance_profiles = np.asarray(clearance_profiles[: elapsed_days.size], dtype=float)
    if bouss_surface_flux_m3_day is not None:
        bouss_surface_flux_m3_day = np.asarray(
            bouss_surface_flux_m3_day[: elapsed_days.size],
            dtype=float,
        )
    if accumulation_proxy_m3_day is not None:
        accumulation_proxy_m3_day = np.asarray(
            accumulation_proxy_m3_day[: elapsed_days.size],
            dtype=float,
        )
    residual_m3_day = np.asarray(
        net_inflow_m3_day - storage_change_m3_day,
        dtype=float,
    )
    peak_idx = int(np.argmax(drainage_flux_m3_day))
    peak_total_idx = int(np.argmax(total_outflow_m3_day))
    return TransientResult(
        solver=result.solver_name,
        out_path=result.out_path,
        postprocess_dir=result.postprocess_dir,
        elapsed_days=elapsed_days,
        x=x,
        topography_profile=topography_profile,
        head_profiles=head_profiles,
        clearance_profiles=clearance_profiles,
        drainage_flux_m3_day=drainage_flux_m3_day,
        east_boundary_inflow_m3_day=east_boundary_inflow_m3_day,
        east_boundary_outflow_m3_day=east_boundary_outflow_m3_day,
        total_inflow_m3_day=total_inflow_m3_day,
        total_outflow_m3_day=total_outflow_m3_day,
        recharge_flux_m3_day=recharge_flux_m3_day,
        net_inflow_m3_day=net_inflow_m3_day,
        storage_change_m3_day=np.asarray(storage_change_m3_day, dtype=float),
        residual_m3_day=residual_m3_day,
        max_clearance_m=float(np.max(clearance_profiles)),
        onset_day=_first_contact_day(clearance_profiles, elapsed_days=elapsed_days),
        peak_drainage_flux_m3_day=float(drainage_flux_m3_day[peak_idx]),
        peak_drainage_day=float(elapsed_days[peak_idx]),
        peak_total_outflow_m3_day=float(total_outflow_m3_day[peak_total_idx]),
        peak_total_outflow_day=float(elapsed_days[peak_total_idx]),
        bouss_surface_flux_m3_day=bouss_surface_flux_m3_day,
        accumulation_proxy_m3_day=accumulation_proxy_m3_day,
        wall_time_seconds=wall_time_seconds,
    )


def _write_head_snapshots(results: list[TransientResult], output_png: Path) -> None:
    reporting_write_head_snapshots(
        results,
        output_png,
        solver_order=SOLVER_ORDER,
        solver_labels=SOLVER_LABELS,
        snapshot_days=SNAPSHOT_DAYS,
    )


def _write_flux_figure(results: list[TransientResult], output_png: Path) -> None:
    reporting_write_flux_figure(
        results,
        output_png,
        solver_order=SOLVER_ORDER,
        solver_labels=SOLVER_LABELS,
        recharge_series_mm_day=RECHARGE_SERIES_MM_DAY,
        style_fn=_comparison_plot_style,
    )


def _write_total_outflow_overlay_figure(results: list[TransientResult], output_png: Path) -> None:
    reporting_write_total_outflow_overlay_figure(
        results,
        output_png,
        solver_order=SOLVER_ORDER,
        solver_labels=SOLVER_LABELS,
        style_fn=_comparison_plot_style,
    )


def _write_outflow_components_figure(results: list[TransientResult], output_png: Path) -> None:
    reporting_write_outflow_components_figure(
        results,
        output_png,
        solver_order=SOLVER_ORDER,
        solver_labels=SOLVER_LABELS,
        solver_colors=SOLVER_COLORS,
    )


def _write_flux_budget_figure(results: list[TransientResult], output_png: Path) -> None:
    reporting_write_flux_budget_figure(
        results,
        output_png,
        solver_order=SOLVER_ORDER,
        solver_labels=SOLVER_LABELS,
        style_fn=_comparison_plot_style,
    )


def _write_execution_times_figure(results: list[TransientResult], output_png: Path) -> None:
    reporting_write_execution_times_figure(
        results,
        output_png,
        solver_order=SOLVER_ORDER,
        solver_labels=SOLVER_LABELS,
        solver_colors=SOLVER_COLORS,
    )


def _select_informative_points(results: list[TransientResult]) -> list[tuple[str, str, float]]:
    ordered = sorted(results, key=lambda item: SOLVER_ORDER.index(item.solver))
    x = np.asarray(ordered[0].x, dtype=float)
    amplitude_by_solver = np.vstack(
        [np.ptp(np.asarray(item.head_profiles, dtype=float), axis=0) for item in ordered]
    )
    combined_amplitude = np.mean(amplitude_by_solver, axis=0)
    selected: list[tuple[str, str, float]] = []
    for point_id, point_label, left_frac, right_frac in POINT_BANDS:
        left_x = float(x[0]) + left_frac * float(x[-1] - x[0])
        right_x = float(x[0]) + right_frac * float(x[-1] - x[0])
        mask = (x >= left_x) & (x <= right_x)
        if not np.any(mask):
            idx = int(np.argmax(combined_amplitude))
        else:
            local_indices = np.flatnonzero(mask)
            idx = int(local_indices[int(np.argmax(combined_amplitude[mask]))])
        selected.append((point_id, point_label, float(x[idx])))
    return selected


def _write_head_point_figure(
    results: list[TransientResult], output_png: Path
) -> list[dict[str, Any]]:
    return reporting_write_head_point_figure(
        results,
        output_png,
        solver_order=SOLVER_ORDER,
        solver_labels=SOLVER_LABELS,
        recharge_series_mm_day=RECHARGE_SERIES_MM_DAY,
        point_bands=POINT_BANDS,
        style_fn=_comparison_plot_style,
    )


def _write_markdown_summary(
    results: list[TransientResult],
    output_md: Path,
    figures_dir: Path,
    *,
    hydraulic_conductivity_scale: float,
    topography_base_elevation_m: float,
) -> None:
    reporting_write_markdown_summary(
        results,
        output_md,
        figures_dir,
        solver_order=SOLVER_ORDER,
        solver_labels=SOLVER_LABELS,
        recharge_series_mm_day=RECHARGE_SERIES_MM_DAY,
        hydraulic_conductivity_scale=hydraulic_conductivity_scale,
        topography_base_elevation_m=topography_base_elevation_m,
        drainage_conductance_m2_s=DRAINAGE_CONDUCTANCE_M2_S,
        dt_days=DT_DAYS,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a transient hillslope surface-interaction investigation with progressive recharge."
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / "out" / "sih_transient_ramp_20260413",
        help="Directory where the report and run artifacts are written.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=2400,
        help="Per-solver timeout in seconds.",
    )
    parser.add_argument(
        "--solvers",
        type=str,
        nargs="+",
        default=list(SOLVER_ORDER),
        help=(
            "Subset of solvers to run. Choices: modflownwt modflow6 "
            "modflow6_irregular_tri boussinesq petsc_partition petsc"
        ),
    )
    parser.add_argument(
        "--hydraulic-conductivity-scale",
        type=float,
        default=HYDRAULIC_CONDUCTIVITY_SCALE,
        help="Multiplier applied to the reference hydraulic conductivity.",
    )
    parser.add_argument(
        "--topography-offset-m",
        type=float,
        default=0.0,
        help="Vertical offset added to the whole topography, without changing the imposed head.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    output_root = Path(args.output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    os.environ["HYDROMODPY_OUT_PATH"] = str(output_root)

    metadata = load_case_metadata(CASE_DIR)
    reference_cfg = dict(metadata.get("reference", {}))
    hydraulic_conductivity_scale = _hydraulic_conductivity_scale_from_args(args)
    topography_base_elevation_m = _topography_base_elevation_from_args(args)
    hydraulic_conductivity_m_s = (
        float(reference_cfg["hydraulic_conductivity_m_per_s"]) * hydraulic_conductivity_scale
    )

    runtime_configs_dir = output_root / "runtime_configs"
    results: list[TransientResult] = []
    requested_solvers = tuple(str(value).strip().lower() for value in args.solvers)
    launcher_specs = (
        ("modflownwt", "modflownwt"),
        ("modflow6", "modflow6"),
        ("modflow6_irregular_tri", "modflow6"),
    )
    for solver_key, launcher_solver in launcher_specs:
        if solver_key not in requested_solvers:
            continue
        t0 = time.perf_counter()
        run_result = _run_launcher_solver(
            metadata=metadata,
            solver=launcher_solver,
            solver_key=solver_key,
            hydraulic_conductivity_m_s=hydraulic_conductivity_m_s,
            topography_base_elevation_m=topography_base_elevation_m,
            timeout=int(args.timeout),
            runtime_configs_dir=runtime_configs_dir,
        )
        results.append(
            _build_result(
                run_result,
                hydraulic_conductivity_scale=hydraulic_conductivity_scale,
                topography_base_elevation_m=topography_base_elevation_m,
                wall_time_seconds=time.perf_counter() - t0,
            )
        )
    for bouss_solver in ("boussinesq", "petsc_partition", "petsc"):
        if bouss_solver not in requested_solvers:
            continue
        t0 = time.perf_counter()
        bouss_result = _run_boussinesq(
            solver_key=bouss_solver,
            hydraulic_conductivity_m_s=hydraulic_conductivity_m_s,
            topography_base_elevation_m=topography_base_elevation_m,
            timeout=int(args.timeout),
        )
        results.append(
            _build_result(
                bouss_result,
                hydraulic_conductivity_scale=hydraulic_conductivity_scale,
                topography_base_elevation_m=topography_base_elevation_m,
                wall_time_seconds=time.perf_counter() - t0,
            )
        )
    if not results:
        raise ValueError("No valid solvers were selected.")

    timeseries_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    execution_rows: list[dict[str, Any]] = []
    for item in sorted(results, key=lambda row: SOLVER_ORDER.index(row.solver)):
        for idx, day in enumerate(item.elapsed_days.tolist()):
            row: dict[str, Any] = {
                "solver": item.solver,
                "solver_label": SOLVER_LABELS[item.solver],
                "elapsed_days": float(day),
                "recharge_mm_day": float(RECHARGE_SERIES_MM_DAY[idx]),
                "recharge_flux_m3_day": float(item.recharge_flux_m3_day[idx]),
                "east_boundary_inflow_m3_day": float(item.east_boundary_inflow_m3_day[idx]),
                "drainage_flux_m3_day": float(item.drainage_flux_m3_day[idx]),
                "east_boundary_outflow_m3_day": float(item.east_boundary_outflow_m3_day[idx]),
                "total_inflow_m3_day": float(item.total_inflow_m3_day[idx]),
                "total_outflow_m3_day": float(item.total_outflow_m3_day[idx]),
                "net_inflow_m3_day": float(item.net_inflow_m3_day[idx]),
                "storage_change_m3_day": float(item.storage_change_m3_day[idx]),
                "residual_m3_day": float(item.residual_m3_day[idx]),
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

    _write_csv(output_root / "timeseries.csv", timeseries_rows)
    _write_csv(output_root / "summary_metrics.csv", summary_rows)
    _write_csv(output_root / "execution_times.csv", execution_rows)

    figures_dir = output_root / "figures"
    _write_head_snapshots(results, figures_dir / "head_snapshots.png")
    _write_flux_figure(results, figures_dir / "flux_timeseries.png")
    _write_total_outflow_overlay_figure(results, figures_dir / "total_outflow_overlay.png")
    _write_outflow_components_figure(results, figures_dir / "outflow_components.png")
    _write_flux_budget_figure(results, figures_dir / "flux_budget_comparison.png")
    _write_execution_times_figure(results, figures_dir / "execution_times.png")
    head_point_rows = _write_head_point_figure(results, figures_dir / "head_point_timeseries.png")
    _write_csv(output_root / "head_point_timeseries.csv", head_point_rows)
    _write_markdown_summary(
        results,
        output_root / "summary.md",
        figures_dir,
        hydraulic_conductivity_scale=hydraulic_conductivity_scale,
        topography_base_elevation_m=topography_base_elevation_m,
    )
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
