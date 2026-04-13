"""Transient cross-solver hillslope investigation with a progressive recharge ramp."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.core.config.toml_loader import merge_toml_payloads
from validation_cases.analytical.steady.boussinesq_piecewise import mm_day_to_m_s
from validation_cases.analytical.steady.linearized_unconfined_hillslope_drainage_1d.reference import (
    build_linear_topography_values,
)
from validation_cases.shared import (
    ValidationRunResult,
    load_case_config,
    load_case_metadata,
    load_npy_time_series_arrays,
)
from validation_cases.shared.boussinesq_uniform_strip import (
    run_boussinesq_uniform_strip_case,
)
from validation_cases.shared.gmsh_irregular_strip import write_irregular_strip_bundle
from validation_cases.shared.runtime import (
    _dump_toml,
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
    REPO_ROOT
    / "examples"
    / "projects"
    / "launcher_simulation"
    / "launcher_simulation.py"
)
SOLVER_ORDER = ("modflownwt", "modflow6", "modflow6_irregular_tri", "boussinesq")
SOLVER_LABELS = {
    "modflownwt": "MODFLOW-NWT",
    "modflow6": "MODFLOW 6",
    "modflow6_irregular_tri": "MODFLOW 6 irregular triangles",
    "boussinesq": "Boussinesq",
}
SOLVER_COLORS = {
    "modflownwt": "#1f77b4",
    "modflow6": "#ff7f0e",
    "modflow6_irregular_tri": "#9467bd",
    "boussinesq": "#2ca02c",
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
    value
    for value in YEAR_1_RECHARGE_SERIES_MM_DAY_30D
    for _ in range(2)
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
    return {
        "color": SOLVER_COLORS[solver],
        "linewidth": 2.0,
        "zorder": 4,
    }


def _recharge_total_flux_m3_day() -> np.ndarray:
    area_m2 = float(LENGTH_X_M) * float(WIDTH_Y_M)
    recharge_m_day = np.asarray(RECHARGE_SERIES_MM_DAY, dtype=float) / 1000.0
    return recharge_m_day * area_m2


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
    east_boundary_outflow_m3_day: np.ndarray
    total_outflow_m3_day: np.ndarray
    recharge_flux_m3_day: np.ndarray
    storage_balance_m3_day: np.ndarray
    max_clearance_m: float
    onset_day: float
    peak_drainage_flux_m3_day: float
    peak_drainage_day: float
    peak_total_outflow_m3_day: float
    peak_total_outflow_day: float
    bouss_surface_flux_m3_day: np.ndarray | None = None
    accumulation_proxy_m3_day: np.ndarray | None = None
    wall_time_seconds: float | None = None


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value.lower()).strip("_")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


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
        "base_elevation": TOPOGRAPHY_BASE_ELEVATION_M,
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
    flow["sinks_sources"] = {"recharge": {"first_clim": "first", "negative_to_evt": False}}

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


def _run_launcher_solver(
    *,
    metadata: dict[str, Any],
    solver: str,
    solver_key: str | None = None,
    hydraulic_conductivity_m_s: float,
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
                topography_base_elevation_m=TOPOGRAPHY_BASE_ELEVATION_M,
                topography_right_to_left_amplitude_m=TOPOGRAPHY_RIGHT_TO_LEFT_AMPLITUDE_M,
            ),
            z_bottom_m=lambda x_m: build_linear_topography_values(
                x_m=np.asarray(x_m, dtype=float),
                xmin=0.0,
                xmax=LENGTH_X_M,
                topography_base_elevation_m=TOPOGRAPHY_BASE_ELEVATION_M,
                topography_right_to_left_amplitude_m=TOPOGRAPHY_RIGHT_TO_LEFT_AMPLITUDE_M,
            )
            - AQUIFER_THICKNESS_M,
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

    completed = run_example_script(
        script_path=LAUNCHER_SCRIPT,
        out_path=out_path,
        out_env_var="HYDROMODPY_OUT_PATH",
        extra_env={
            "HYDROMODPY_NO_DISPLAY": "1",
            "HYDROMODPY_NO_SAVE": "1",
            "MPLBACKEND": "Agg",
        },
        script_args=[str(config_path)],
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"Launcher run failed for {solver}.\nStdout:\n{completed.stdout}\nStderr:\n{completed.stderr}"
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
    hydraulic_conductivity_m_s: float,
    timeout: int,
) -> ValidationRunResult:
    recharge_series_m_s = [mm_day_to_m_s(float(value)) for value in RECHARGE_SERIES_MM_DAY]
    return run_boussinesq_uniform_strip_case(
        case_dir=CASE_DIR,
        case_id="hillslope_surface_transient",
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
            topography_base_elevation_m=TOPOGRAPHY_BASE_ELEVATION_M,
            topography_right_to_left_amplitude_m=TOPOGRAPHY_RIGHT_TO_LEFT_AMPLITUDE_M,
        ),
        z_bottom_m=lambda x_m: build_linear_topography_values(
            x_m=np.asarray(x_m, dtype=float),
            xmin=0.0,
            xmax=LENGTH_X_M,
            topography_base_elevation_m=TOPOGRAPHY_BASE_ELEVATION_M,
            topography_right_to_left_amplitude_m=TOPOGRAPHY_RIGHT_TO_LEFT_AMPLITUDE_M,
        )
        - AQUIFER_THICKNESS_M,
        hydraulic_conductivity_m_s=hydraulic_conductivity_m_s,
        storage_coefficient=SPECIFIC_YIELD,
        flow_section={
            "runtime_backend": "local",
            "flow_regime": "transient",
            "runtime_max_iterations": 80,
            "runtime_tol_residual_inf": 1.0e-7,
            "ic": {"type": "custom", "value": INITIAL_HEAD_M},
            "active_sinks_sources": ["recharge"],
            "active_bc": ["east_side", "drainage"],
            "sinks_sources": {
                "recharge": {
                    "values": recharge_series_m_s,
                    "first_clim": "first",
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
        export_initial_state=False,
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
            squared_distance = (centroid_x - float(x_center)) ** 2 + (centroid_y - float(y_center)) ** 2
            nearest_indices[row_idx, col_idx] = int(np.argmin(squared_distance))
    return history[:, nearest_indices].reshape(history.shape[0], int(ny), int(nx))


def _integrate_structured_flux_m3_day(values: np.ndarray, *, dx_m: float, dy_m: float) -> np.ndarray:
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
    raise ValueError(
        f"History has {data.shape[0]} steps but {n_steps} were expected."
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
    node_x = np.asarray(nodes["x"], dtype=float)
    edge_kind = np.asarray(edges["edge_kind"])
    node_a = np.asarray(edges["node_a"], dtype=int)
    node_b = np.asarray(edges["node_b"], dtype=int)
    max_x = float(np.max(node_x))
    return (
        np.asarray(edge_kind == "boundary", dtype=bool)
        & np.isclose(node_x[node_a], max_x)
        & np.isclose(node_x[node_b], max_x)
    )


def _select_snapshot_indices(elapsed_days: np.ndarray, snapshot_days: tuple[float, ...]) -> list[int]:
    times = np.asarray(elapsed_days, dtype=float).reshape(-1)
    selected: list[int] = []
    for day in snapshot_days:
        idx = int(np.argmin(np.abs(times - float(day))))
        if idx not in selected:
            selected.append(idx)
    return sorted(selected)


def _first_contact_day(clearance_profiles: np.ndarray) -> float:
    mask = np.any(np.asarray(clearance_profiles, dtype=float) >= -CONTACT_TOLERANCE_M, axis=1)
    if not np.any(mask):
        return float("nan")
    return float(_elapsed_days_from_steps(mask.size)[int(np.argmax(mask))])


def _build_result(
    result: ValidationRunResult,
    *,
    wall_time_seconds: float | None = None,
) -> TransientResult:
    period_indices, heads = load_npy_time_series_arrays(result.postprocess_dir, "watertable_elevation")
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
    elapsed_days = _elapsed_days_from_steps(head_profiles.shape[0])
    dx = LENGTH_X_M / float(head_profiles.shape[1])
    x = (np.arange(head_profiles.shape[1], dtype=float) + 0.5) * dx
    topography_profile = build_linear_topography_values(
        x_m=x,
        xmin=0.0,
        xmax=LENGTH_X_M,
        topography_base_elevation_m=TOPOGRAPHY_BASE_ELEVATION_M,
        topography_right_to_left_amplitude_m=TOPOGRAPHY_RIGHT_TO_LEFT_AMPLITUDE_M,
    )
    clearance_profiles = head_profiles - topography_profile[None, :]

    bouss_surface_flux_m3_day: np.ndarray | None = None
    accumulation_proxy_m3_day: np.ndarray | None = None
    if result.solver_name == "boussinesq":
        with np.load(result.model_ws / "_boussinesq_state_history.npz") as payload:
            drainage_history = _align_step_history(
                payload["drainage_flux_history_m3_s"],
                n_steps=head_profiles.shape[0],
            )
            saturation_excess_history = _align_step_history(
                payload["saturation_excess_history_m_s"],
                n_steps=head_profiles.shape[0],
            )
            imposed_head_history = _align_step_history(
                payload["imposed_head_edge_flux_history_m3_s"],
                n_steps=head_profiles.shape[0],
            )
        drainage_flux_m3_day = np.sum(drainage_history, axis=1, dtype=float) * SECONDS_PER_DAY
        cells = np.genfromtxt(
            result.out_path / "mesh_bundle" / "cells.csv",
            delimiter=",",
            names=True,
            dtype=float,
            encoding="utf-8",
        )
        cell_area_m2 = np.asarray(cells["area_m2"], dtype=float).reshape(-1)
        bouss_surface_flux_m3_day = (
            np.sum(saturation_excess_history * cell_area_m2[None, :], axis=1, dtype=float)
            * SECONDS_PER_DAY
        )
        east_edge_mask = _load_boussinesq_east_boundary_edge_mask(result.out_path / "mesh_bundle")
        east_boundary_outflow_m3_day = (
            -np.sum(np.minimum(imposed_head_history[:, east_edge_mask], 0.0), axis=1, dtype=float)
            * SECONDS_PER_DAY
        )
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
        east_boundary_outflow_m3_day = _load_scalar_series_m3_day(
            result.postprocess_dir,
            "outlet_discharge_east_side_m3_s",
        )
        _, accumulation_flux = load_npy_time_series_arrays(result.postprocess_dir, "accumulation_flux")
        accumulation_flux = np.asarray(accumulation_flux, dtype=float)
        if accumulation_flux.ndim == 2:
            accumulation_proxy_m3_day = (
                np.sum(np.nan_to_num(accumulation_flux, nan=0.0), axis=1, dtype=float) * SECONDS_PER_DAY
            )
        else:
            accumulation_proxy_m3_day = _integrate_structured_flux_m3_day(
                accumulation_flux,
                dx_m=LENGTH_X_M / float(BOUSS_NX),
                dy_m=WIDTH_Y_M / float(BOUSS_NY),
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
    recharge_flux_m3_day = _recharge_total_flux_m3_day()
    storage_balance_m3_day = np.asarray(
        recharge_flux_m3_day - total_outflow_m3_day,
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
        east_boundary_outflow_m3_day=east_boundary_outflow_m3_day,
        total_outflow_m3_day=total_outflow_m3_day,
        recharge_flux_m3_day=recharge_flux_m3_day,
        storage_balance_m3_day=storage_balance_m3_day,
        max_clearance_m=float(np.max(clearance_profiles)),
        onset_day=_first_contact_day(clearance_profiles),
        peak_drainage_flux_m3_day=float(drainage_flux_m3_day[peak_idx]),
        peak_drainage_day=float(elapsed_days[peak_idx]),
        peak_total_outflow_m3_day=float(total_outflow_m3_day[peak_total_idx]),
        peak_total_outflow_day=float(elapsed_days[peak_total_idx]),
        bouss_surface_flux_m3_day=bouss_surface_flux_m3_day,
        accumulation_proxy_m3_day=accumulation_proxy_m3_day,
        wall_time_seconds=wall_time_seconds,
    )


def _write_head_snapshots(results: list[TransientResult], output_png: Path) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)
    ordered = sorted(results, key=lambda item: SOLVER_ORDER.index(item.solver))
    snapshot_idx = _select_snapshot_indices(ordered[0].elapsed_days, SNAPSHOT_DAYS)
    colors = plt.cm.cividis(np.linspace(0.12, 0.88, len(snapshot_idx)))

    fig, axes = plt.subplots(len(ordered), 1, figsize=(10.8, 8.8), sharex=True, constrained_layout=True)
    if len(ordered) == 1:
        axes = [axes]
    for ax, item in zip(axes, ordered, strict=False):
        ax.plot(
            item.x,
            item.topography_profile,
            color="#222222",
            linewidth=1.8,
            linestyle="--",
            label="Topography",
        )
        for color, idx in zip(colors, snapshot_idx, strict=False):
            ax.plot(
                item.x,
                item.head_profiles[idx],
                color=color,
                linewidth=1.9,
                label=f"t={item.elapsed_days[idx]:.0f} d",
            )
        ax.set_ylabel("Head [m]")
        ax.set_title(SOLVER_LABELS[item.solver], fontsize=10.5)
        ax.grid(alpha=0.25, linewidth=0.6)
    axes[0].legend(loc="upper right", fontsize=8.8, frameon=False, ncols=3)
    axes[-1].set_xlabel("x [m]")
    fig.suptitle("Recharge ramp then dry recovery: head profiles at selected times", fontsize=11.0)
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _write_flux_figure(results: list[TransientResult], output_png: Path) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)
    ordered = sorted(results, key=lambda item: SOLVER_ORDER.index(item.solver))
    fig, axes = plt.subplots(2, 1, figsize=(10.6, 7.8), sharex=True, constrained_layout=True)

    elapsed_days = ordered[0].elapsed_days
    recharge = np.asarray(RECHARGE_SERIES_MM_DAY, dtype=float)
    axes[0].step(
        elapsed_days,
        recharge,
        where="mid",
        color="#444444",
        linewidth=2.0,
    )
    axes[0].set_ylabel("Recharge [mm/day]")
    axes[0].grid(alpha=0.25, linewidth=0.6)

    for item in ordered:
        axes[1].plot(
            item.elapsed_days,
            item.total_outflow_m3_day,
            label=f"{SOLVER_LABELS[item.solver]} total outflow",
            **_comparison_plot_style(item.solver),
        )
    axes[1].set_xlabel("Time [days]")
    axes[1].set_ylabel("Flux [m3/day]")
    axes[1].grid(alpha=0.25, linewidth=0.6)
    axes[1].legend(loc="upper left", fontsize=8.8, frameon=False)

    fig.suptitle("Recharge ramp then dry recovery: recharge and total outflow", fontsize=11.0)
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _write_total_outflow_overlay_figure(results: list[TransientResult], output_png: Path) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)
    ordered = sorted(results, key=lambda item: SOLVER_ORDER.index(item.solver))
    fig, ax = plt.subplots(figsize=(10.4, 4.8), constrained_layout=True)

    for item in ordered:
        ax.plot(
            item.elapsed_days,
            item.total_outflow_m3_day,
            label=SOLVER_LABELS[item.solver],
            **_comparison_plot_style(item.solver),
        )
    ax.set_xlabel("Time [days]")
    ax.set_ylabel("Total Outflow [m3/day]")
    ax.set_title("Total Outflow Overlay", fontsize=10.8)
    ax.grid(alpha=0.25, linewidth=0.6)
    ax.legend(loc="upper left", fontsize=8.8, frameon=False, ncols=3)

    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _write_outflow_components_figure(results: list[TransientResult], output_png: Path) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)
    ordered = sorted(results, key=lambda item: SOLVER_ORDER.index(item.solver))
    fig, axes = plt.subplots(len(ordered), 1, figsize=(11.0, 8.8), sharex=True, constrained_layout=True)
    if len(ordered) == 1:
        axes = [axes]
    for ax, item in zip(axes, ordered, strict=False):
        ax.plot(
            item.elapsed_days,
            item.total_outflow_m3_day,
            color="#111111",
            linewidth=2.2,
            label="Total outflow",
        )
        ax.plot(
            item.elapsed_days,
            item.east_boundary_outflow_m3_day,
            color="#7f7f7f",
            linewidth=1.8,
            linestyle="-.",
            label="East boundary",
        )
        ax.plot(
            item.elapsed_days,
            item.drainage_flux_m3_day,
            color=SOLVER_COLORS[item.solver],
            linewidth=2.0,
            label="Drainage",
        )
        if item.bouss_surface_flux_m3_day is not None:
            ax.plot(
                item.elapsed_days,
                item.bouss_surface_flux_m3_day,
                color="#d62728",
                linewidth=1.8,
                linestyle="--",
                label="Surface excess",
            )
        ax.set_ylabel("Flux [m3/day]")
        ax.set_title(SOLVER_LABELS[item.solver], fontsize=10.5)
        ax.grid(alpha=0.25, linewidth=0.6)
    axes[0].legend(loc="upper left", fontsize=8.8, frameon=False, ncols=4)
    axes[-1].set_xlabel("Time [days]")
    fig.suptitle("Outflow components by solver", fontsize=11.0)
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _write_flux_budget_figure(results: list[TransientResult], output_png: Path) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)
    ordered = sorted(results, key=lambda item: SOLVER_ORDER.index(item.solver))
    elapsed_days = ordered[0].elapsed_days

    fig, axes = plt.subplots(3, 2, figsize=(12.4, 9.8), sharex=True, constrained_layout=True)
    flat_axes = list(np.asarray(axes).reshape(-1))

    recharge_ax = flat_axes[0]
    recharge_ax.step(
        elapsed_days,
        ordered[0].recharge_flux_m3_day,
        where="mid",
        color="#222222",
        linewidth=2.0,
    )
    recharge_ax.set_title("Recharge Input", fontsize=10.2)
    recharge_ax.set_ylabel("Flux [m3/day]")
    recharge_ax.grid(alpha=0.25, linewidth=0.6)

    panel_specs: list[tuple[Any, str]] = [
        (lambda item: item.storage_balance_m3_day, "Storage Balance"),
        (lambda item: item.drainage_flux_m3_day, "Drainage Outflow"),
        (lambda item: item.east_boundary_outflow_m3_day, "East Boundary Outflow"),
        (
            lambda item: (
                np.zeros_like(item.elapsed_days, dtype=float)
                if item.bouss_surface_flux_m3_day is None
                else np.asarray(item.bouss_surface_flux_m3_day, dtype=float)
            ),
            "Surface Excess Outflow",
        ),
        (lambda item: item.total_outflow_m3_day, "Total Outflow"),
    ]

    for ax, (series_getter, title) in zip(flat_axes[1:], panel_specs, strict=False):
        for item in ordered:
            ax.plot(
                item.elapsed_days,
                np.asarray(series_getter(item), dtype=float),
                label=SOLVER_LABELS[item.solver],
                **_comparison_plot_style(item.solver),
            )
        if title == "Storage Balance":
            ax.axhline(0.0, color="#444444", linewidth=1.0, linestyle="--")
        ax.set_title(title, fontsize=10.2)
        ax.set_ylabel("Flux [m3/day]")
        ax.grid(alpha=0.25, linewidth=0.6)

    flat_axes[1].legend(loc="upper right", fontsize=8.4, frameon=False)
    flat_axes[-2].set_xlabel("Time [days]")
    flat_axes[-1].set_xlabel("Time [days]")
    fig.suptitle("Complete Flux Budget Comparison", fontsize=11.0)
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _write_execution_times_figure(results: list[TransientResult], output_png: Path) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)
    ordered = sorted(results, key=lambda item: SOLVER_ORDER.index(item.solver))
    labels = [SOLVER_LABELS[item.solver] for item in ordered]
    values = [
        float(item.wall_time_seconds) if item.wall_time_seconds is not None else float("nan")
        for item in ordered
    ]
    colors = [SOLVER_COLORS[item.solver] for item in ordered]
    ypos = np.arange(len(ordered), dtype=float)

    fig, ax = plt.subplots(figsize=(8.4, 3.8), constrained_layout=True)
    bars = ax.barh(ypos, values, color=colors, edgecolor="#222222", linewidth=0.6)
    ax.set_yticks(ypos, labels)
    ax.set_xlabel("Wall Time [s]")
    ax.set_title("Execution Time Comparison", fontsize=10.8)
    ax.grid(axis="x", alpha=0.25, linewidth=0.6)

    for bar, value in zip(bars, values, strict=False):
        if not np.isfinite(value):
            continue
        ax.text(
            float(bar.get_width()) + max(values) * 0.015,
            float(bar.get_y()) + float(bar.get_height()) * 0.5,
            f"{value:.2f} s",
            va="center",
            ha="left",
            fontsize=8.8,
        )
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _select_informative_points(results: list[TransientResult]) -> list[tuple[str, str, float]]:
    ordered = sorted(results, key=lambda item: SOLVER_ORDER.index(item.solver))
    x = np.asarray(ordered[0].x, dtype=float)
    amplitude_by_solver = np.vstack(
        [
            np.ptp(np.asarray(item.head_profiles, dtype=float), axis=0)
            for item in ordered
        ]
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


def _write_head_point_figure(results: list[TransientResult], output_png: Path) -> list[dict[str, Any]]:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)
    ordered = sorted(results, key=lambda item: SOLVER_ORDER.index(item.solver))
    point_specs = _select_informative_points(ordered)
    fig, axes = plt.subplots(4, 1, figsize=(11.0, 10.4), sharex=True, constrained_layout=True)

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

    rows: list[dict[str, Any]] = []
    for ax, (point_id, point_label, target_x_m) in zip(axes[1:], point_specs, strict=False):
        topo_value_m: float | None = None
        for item in ordered:
            idx = int(np.argmin(np.abs(item.x - float(target_x_m))))
            x_value = float(item.x[idx])
            head_series = np.asarray(item.head_profiles[:, idx], dtype=float)
            clearance_series = np.asarray(item.clearance_profiles[:, idx], dtype=float)
            ax.plot(
                item.elapsed_days,
                head_series,
                label=SOLVER_LABELS[item.solver],
                **_comparison_plot_style(item.solver),
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
                topo_value_m = float(item.topography_profile[idx])
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
    plt.close(fig)
    return rows


def _write_markdown_summary(results: list[TransientResult], output_md: Path, figures_dir: Path) -> None:
    ordered = sorted(results, key=lambda item: SOLVER_ORDER.index(item.solver))
    lines = [
        "# Transient Hillslope Surface-Interaction Investigation",
        "",
        "West no-flow, east fixed head, annual recharge ramp followed by one dry year, and top drainage.",
        "",
        f"- hydraulic conductivity scale: `{HYDRAULIC_CONDUCTIVITY_SCALE:.3f}x`",
        f"- drainage conductance: `{DRAINAGE_CONDUCTANCE_M2_S:.3g} m2/s`",
        f"- time step: `{DT_DAYS:.1f} day`",
        f"- recharge series [mm/day]: `{list(RECHARGE_SERIES_MM_DAY)}`",
        "- forcing shape: increase during first half-year, decrease during second half-year, then one additional year with zero recharge.",
        "",
        "| Solver | Onset day [d] | Peak drainage flux [m3/day] | Peak drainage day [d] | Max clearance [m] | Wall time [s] | Results dir |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in ordered:
        wall_time_text = "n/a" if item.wall_time_seconds is None else f"{item.wall_time_seconds:.2f}"
        lines.append(
            f"| {SOLVER_LABELS[item.solver]} | {item.onset_day:.1f} | {item.peak_drainage_flux_m3_day:.4f} | {item.peak_drainage_day:.1f} | {item.max_clearance_m:.4f} | {wall_time_text} | `{item.out_path}` |"
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    output_root = Path(args.output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    os.environ["HYDROMODPY_OUT_PATH"] = str(output_root)

    metadata = load_case_metadata(CASE_DIR)
    reference_cfg = dict(metadata.get("reference", {}))
    hydraulic_conductivity_m_s = (
        float(reference_cfg["hydraulic_conductivity_m_per_s"]) * HYDRAULIC_CONDUCTIVITY_SCALE
    )

    runtime_configs_dir = output_root / "runtime_configs"
    results: list[TransientResult] = []
    for solver_key, launcher_solver in (
        ("modflownwt", "modflownwt"),
        ("modflow6", "modflow6"),
        ("modflow6_irregular_tri", "modflow6"),
    ):
        t0 = time.perf_counter()
        run_result = _run_launcher_solver(
            metadata=metadata,
            solver=launcher_solver,
            solver_key=solver_key,
            hydraulic_conductivity_m_s=hydraulic_conductivity_m_s,
            timeout=int(args.timeout),
            runtime_configs_dir=runtime_configs_dir,
        )
        results.append(_build_result(run_result, wall_time_seconds=time.perf_counter() - t0))
    t0 = time.perf_counter()
    bouss_result = _run_boussinesq(
        hydraulic_conductivity_m_s=hydraulic_conductivity_m_s,
        timeout=int(args.timeout),
    )
    results.append(_build_result(bouss_result, wall_time_seconds=time.perf_counter() - t0))

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
    _write_markdown_summary(results, output_root / "summary.md", figures_dir)
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
