"""Cross-solver investigation workflow for simple hillslope surface interaction.

This variant uses:

- west divide / no-flow boundary,
- east fixed head,
- uniform recharge,
- distributed top drainage on a sloping hillslope.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]

from hydromodpy.core.toml_io.loader import merge_toml_payloads
from hydromodpy.physics.flow import Flow
from hydromodpy.solver.boussinesq import Boussinesq
from hydromodpy.spatial.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    load_catchment_mesh_bundle,
)
from validation_cases.analytical.steady.boussinesq_piecewise import mm_day_to_m_s
from validation_cases.analytical.steady.linearized_unconfined_hillslope_drainage_1d.reference import (
    build_linear_topography_values,
)
from validation_cases.shared import (
    ValidationRunResult,
    load_case_config,
    load_case_metadata,
    load_last_npy_array,
    max_std_along_axis,
    mean_along_axis,
)
from validation_cases.shared.boussinesq_uniform_strip import (
    aggregate_triangle_history_to_structured_grids,
    build_flow_config,
    write_uniform_strip_bundle,
)
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
    REPO_ROOT / "examples" / "projects" / "launcher_simulation" / "launcher_simulation.py"
)
SOLVER_ORDER = ("modflownwt", "modflow6", "boussinesq")
SOLVER_LABELS = {
    "modflownwt": "MODFLOW-NWT",
    "modflow6": "MODFLOW 6",
    "boussinesq": "Boussinesq",
}
SOLVER_COLORS = {
    "modflownwt": "#1f77b4",
    "modflow6": "#ff7f0e",
    "boussinesq": "#2ca02c",
}
CONTACT_TOLERANCE_M = 0.02
BOUSS_NX = 40
BOUSS_NY = 3
ACCEPTABLE_BOUSS_RESIDUAL_INF = 5.0e-5
LENGTH_X_M = 400.0
WIDTH_Y_M = 30.0
TOPOGRAPHY_BASE_ELEVATION_M = 5.0
TOPOGRAPHY_RIGHT_TO_LEFT_AMPLITUDE_M = 5.0
AQUIFER_THICKNESS_M = 20.0
EAST_HEAD_M = TOPOGRAPHY_BASE_ELEVATION_M + (
    TOPOGRAPHY_RIGHT_TO_LEFT_AMPLITUDE_M / (2.0 * BOUSS_NX)
)
INITIAL_HEAD_M = 6.0
HYDRAULIC_CONDUCTIVITY_SCALE = 0.2


@dataclass(frozen=True, slots=True)
class ScenarioSpec:
    scenario_id: str
    label: str
    recharge_mm_day: float
    drainage_conductance_m2_per_s: float


@dataclass(frozen=True, slots=True)
class InvestigationResult:
    scenario: ScenarioSpec
    solver: str
    out_path: Path
    postprocess_dir: Path
    x: np.ndarray
    topography_profile: np.ndarray
    analytical_profile: np.ndarray
    numerical_profile: np.ndarray
    residual_profile: np.ndarray
    clearance_profile: np.ndarray
    rms_error: float
    max_error: float
    row_spread: float
    min_clearance_m: float
    mean_clearance_m: float
    max_clearance_m: float
    surface_lock_fraction: float
    below_surface_fraction: float
    locked_length_from_toe_m: float
    boussinesq_summary: dict[str, Any] | None = None
    boussinesq_surface_profile_m3_day: np.ndarray | None = None
    boussinesq_drainage_profile_m3_day: np.ndarray | None = None


DEFAULT_SCENARIOS = (
    ScenarioSpec(
        scenario_id="rch_05",
        label="Recharge 0.5 mm/day",
        recharge_mm_day=0.5,
        drainage_conductance_m2_per_s=1.0e-5,
    ),
    ScenarioSpec(
        scenario_id="rch_10",
        label="Recharge 1.0 mm/day",
        recharge_mm_day=1.0,
        drainage_conductance_m2_per_s=1.0e-5,
    ),
    ScenarioSpec(
        scenario_id="rch_20",
        label="Recharge 2.0 mm/day",
        recharge_mm_day=2.0,
        drainage_conductance_m2_per_s=1.0e-5,
    ),
)
SCENARIO_BY_ID = {item.scenario_id: item for item in DEFAULT_SCENARIOS}


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value.lower()).strip("_")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
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


def _apply_scenario_to_launcher_payload(
    payload: dict[str, Any],
    *,
    scenario: ScenarioSpec,
    solver: str,
    hydraulic_conductivity_m_s: float,
) -> dict[str, Any]:
    run_id = f"hillslope_surface_{scenario.scenario_id}_{solver}"
    geographic = dict(payload.get("geographic", {}))
    geographic_synthetic = dict(geographic.get("synthetic", {}))
    geographic_synthetic["case_id"] = f"val_hillslope_surface_{scenario.scenario_id}"
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
    field = dict(param_k.get("field", {}))
    field["value"] = f"{hydraulic_conductivity_m_s:.12g} m/s"
    param_k["field"] = field
    param["K"] = param_k
    flow["param"] = param
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
        "value": f"{scenario.drainage_conductance_m2_per_s:.12g} m2/s",
    }
    bc["dirichlet"] = dirichlet
    bc["cauchy"] = cauchy
    flow["bc"] = bc
    flow["active_sinks_sources"] = ["recharge"]
    flow["active_bc"] = ["east_side", "drainage"]
    flow["ic"] = {
        "type": "custom",
        "value": f"{INITIAL_HEAD_M:.6f} m",
    }
    flow["sinks_sources"] = {"recharge": {"first_clim": "mean"}}

    data = dict(payload.get("data", {}))
    data["types"] = ["recharge"]
    data["inference_mode"] = "warn"
    data["recharge"] = {
        "sources": [
            {
                "source": "synthetic",
                "values": [float(scenario.recharge_mm_day)],
                "runoff_ratio": 0.0,
            }
        ]
    }

    simulation = dict(payload.get("simulation", {}))
    simulation["run_id"] = run_id
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
    payload[solver] = solver_section
    return payload


def _run_launcher_solver_scenario(
    *,
    metadata: dict[str, Any],
    scenario: ScenarioSpec,
    solver: str,
    hydraulic_conductivity_m_s: float,
    timeout: int,
    runtime_configs_dir: Path,
) -> ValidationRunResult:
    out_path = resolve_validation_results_dir(
        test_file=__file__,
        run_name=f"{scenario.scenario_id}_{solver}",
    )
    if out_path.exists():
        remove_tree_with_retry(out_path)
    out_path.mkdir(parents=True, exist_ok=True)

    payload = _load_case_payload_for_solver(metadata, solver)
    payload = _apply_scenario_to_launcher_payload(
        payload,
        scenario=scenario,
        solver=solver,
        hydraulic_conductivity_m_s=hydraulic_conductivity_m_s,
    )

    runtime_configs_dir.mkdir(parents=True, exist_ok=True)
    config_path = runtime_configs_dir / f"{scenario.scenario_id}__{solver}.toml"
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
            "Launcher run failed for "
            f"{scenario.scenario_id}/{solver}.\n"
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
        solver_name=solver,
        out_path=out_path,
        model_ws=model_ws,
        postprocess_dir=postprocess_dir,
        particles_dir=particles_dir,
        run_returncode=int(completed.returncode),
        run_stdout=str(completed.stdout),
        run_stderr=str(completed.stderr),
    )


def _run_boussinesq_scenario(
    *,
    scenario: ScenarioSpec,
    timeout: int,
    length_x_m: float,
    width_y_m: float,
    nx: int,
    ny: int,
    aquifer_thickness_m: float,
    hydraulic_conductivity_m_s: float,
) -> ValidationRunResult:
    initial_head_m = INITIAL_HEAD_M
    out_path = resolve_validation_results_dir(
        test_file=__file__,
        run_name=f"{scenario.scenario_id}_boussinesq",
    )
    if out_path.exists():
        remove_tree_with_retry(out_path)
    out_path.mkdir(parents=True, exist_ok=True)

    bundle_dir = write_uniform_strip_bundle(
        out_path / "mesh_bundle",
        nx=int(nx),
        ny=int(ny),
        length_x_m=float(length_x_m),
        width_y_m=float(width_y_m),
        z_top_m=lambda x_m: build_linear_topography_values(
            x_m=np.asarray(x_m, dtype=float),
            xmin=0.0,
            xmax=length_x_m,
            topography_base_elevation_m=TOPOGRAPHY_BASE_ELEVATION_M,
            topography_right_to_left_amplitude_m=TOPOGRAPHY_RIGHT_TO_LEFT_AMPLITUDE_M,
        ),
        z_bottom_m=lambda x_m: (
            build_linear_topography_values(
                x_m=np.asarray(x_m, dtype=float),
                xmin=0.0,
                xmax=length_x_m,
                topography_base_elevation_m=TOPOGRAPHY_BASE_ELEVATION_M,
                topography_right_to_left_amplitude_m=TOPOGRAPHY_RIGHT_TO_LEFT_AMPLITUDE_M,
            )
            - aquifer_thickness_m
        ),
        hydraulic_conductivity_m_s=float(hydraulic_conductivity_m_s),
        storage_coefficient=0.10,
    )
    bundle = load_catchment_mesh_bundle(bundle_dir)
    simulations_folder = out_path / "results_simulations"
    simulations_folder.mkdir(parents=True, exist_ok=True)

    flow = Flow(
        build_flow_config(
            {
                "runtime_backend": "local",
                "flow_regime": "steady",
                "ic": {"type": "custom", "value": initial_head_m},
                "active_sinks_sources": ["recharge"],
                "active_bc": ["east_side", "drainage"],
                "sinks_sources": {
                    "recharge": {
                        "values": mm_day_to_m_s(float(scenario.recharge_mm_day)),
                        "first_clim": "mean",
                        "units": "m/s",
                    }
                },
                "bc": {
                    "dirichlet": {
                        "east_side": {
                            "type": "dirichlet",
                            "value": EAST_HEAD_M,
                        },
                    },
                    "cauchy": {
                        "drainage": {
                            "application_domain": "top",
                            "type": "cauchy",
                            "value": scenario.drainage_conductance_m2_per_s,
                        }
                    },
                },
            },
            case_dir=CASE_DIR,
        )
    )

    model = Boussinesq(
        mesh_bundle=bundle,
        flow=flow,
        domain=None,
        time_grid=None,
        model_folder=simulations_folder,
        model_name="flow_validation__boussinesq",
    )
    model.pre_processing()
    success = bool(model.processing(write_model=True, run_model=True))
    residual = float(model.runtime_summary.get("steady_residual_norm_inf", np.inf))
    accepted = success or residual <= ACCEPTABLE_BOUSS_RESIDUAL_INF
    model.runtime_summary["accepted_with_relaxed_residual"] = bool((not success) and accepted)
    model.runtime_summary["acceptable_steady_residual_inf"] = float(ACCEPTABLE_BOUSS_RESIDUAL_INF)
    if not accepted:
        post_error = ""
        try:
            model.post_processing()
        except Exception as exc:
            post_error = f" Post-processing failed: {type(exc).__name__}: {exc}."
        raise RuntimeError(
            "Boussinesq hillslope-surface investigation did not converge to an "
            f"acceptable residual. residual_inf={residual:.6g}, "
            f"threshold={ACCEPTABLE_BOUSS_RESIDUAL_INF:.6g}, "
            f"workspace={model.full_path}.{post_error}"
        )

    model.has_numerical_solution = True
    model.solve_stage = "solved"
    model.post_processing()
    aggregate_triangle_history_to_structured_grids(
        model,
        nx=int(nx),
        ny=int(ny),
    )

    model_ws = Path(model.full_path)
    postprocess_dir = model_ws / "_postprocess"
    particles_dir = postprocess_dir / "_particles"
    return ValidationRunResult(
        case_dir=CASE_DIR,
        solver_name="boussinesq",
        out_path=out_path,
        model_ws=model_ws,
        postprocess_dir=postprocess_dir,
        particles_dir=particles_dir,
        run_returncode=0,
        run_stdout="",
        run_stderr="",
    )


def _load_boussinesq_surface_profiles(
    *,
    result: ValidationRunResult,
    nx: int,
    xmin: float,
    xmax: float,
) -> tuple[np.ndarray, np.ndarray]:
    state_history = np.load(result.model_ws / "_boussinesq_state_history.npz")
    surface_history = np.asarray(
        state_history["saturation_excess_history_m_s"],
        dtype=float,
    )
    drainage_history = np.asarray(
        state_history["drainage_flux_history_m3_s"],
        dtype=float,
    )
    if surface_history.ndim == 1:
        surface_history = surface_history.reshape(1, -1)
    if drainage_history.ndim == 1:
        drainage_history = drainage_history.reshape(1, -1)
    final_surface = np.asarray(surface_history[-1], dtype=float)
    final_drainage = np.asarray(drainage_history[-1], dtype=float)

    cells = np.genfromtxt(
        result.out_path / "mesh_bundle" / "cells.csv",
        delimiter=",",
        names=True,
        dtype=float,
        encoding="utf-8",
    )
    centroid_x = np.asarray(cells["centroid_x"], dtype=float).reshape(-1)
    area_m2 = np.asarray(cells["area_m2"], dtype=float).reshape(-1)
    dx = (float(xmax) - float(xmin)) / float(nx)
    col_index = np.clip(
        np.floor((centroid_x - float(xmin)) / dx).astype(int),
        0,
        int(nx) - 1,
    )

    surface_profile = np.zeros(int(nx), dtype=float)
    drainage_profile = np.zeros(int(nx), dtype=float)
    for cell_idx, col in enumerate(col_index.tolist()):
        surface_profile[col] += float(final_surface[cell_idx]) * float(area_m2[cell_idx]) * 86_400.0
        drainage_profile[col] += float(final_drainage[cell_idx]) * 86_400.0
    return surface_profile, drainage_profile


def _locked_length_from_toe(
    x: np.ndarray,
    clearance_profile: np.ndarray,
    *,
    tol_m: float,
) -> float:
    x_values = np.asarray(x, dtype=float).reshape(-1)
    clearance = np.asarray(clearance_profile, dtype=float).reshape(-1)
    if x_values.size <= 1:
        return 0.0
    locked = np.abs(clearance) <= float(tol_m)
    if not bool(locked[-1]):
        return 0.0
    last_false = np.flatnonzero(~locked)
    if last_false.size == 0:
        return float(x_values[-1] - x_values[0])
    start_idx = int(last_false[-1]) + 1
    dx = float(np.median(np.diff(x_values)))
    return float((x_values.size - start_idx) * dx)


def _build_investigation_result(
    *,
    metadata: dict[str, Any],
    scenario: ScenarioSpec,
    result: ValidationRunResult,
) -> InvestigationResult:
    _timestep, heads = load_last_npy_array(result.postprocess_dir, "watertable_elevation")
    profile_axis = 0
    numerical_profile = mean_along_axis(heads, axis=profile_axis)
    xmin = 0.0
    xmax = LENGTH_X_M
    x = xmin + (
        (np.arange(numerical_profile.size, dtype=float) + 0.5)
        * ((xmax - xmin) / float(numerical_profile.size))
    )
    topography_profile = build_linear_topography_values(
        x_m=x,
        xmin=xmin,
        xmax=xmax,
        topography_base_elevation_m=TOPOGRAPHY_BASE_ELEVATION_M,
        topography_right_to_left_amplitude_m=TOPOGRAPHY_RIGHT_TO_LEFT_AMPLITUDE_M,
    )
    analytical_profile = np.full_like(numerical_profile, np.nan, dtype=float)
    residual_profile = np.full_like(numerical_profile, np.nan, dtype=float)
    clearance_profile = np.asarray(numerical_profile - topography_profile, dtype=float)

    bouss_summary: dict[str, Any] | None = None
    bouss_surface_profile: np.ndarray | None = None
    bouss_drainage_profile: np.ndarray | None = None
    if result.solver_name == "boussinesq":
        summary_path = result.model_ws / "_boussinesq_summary.json"
        if summary_path.exists():
            bouss_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        bouss_surface_profile, bouss_drainage_profile = _load_boussinesq_surface_profiles(
            result=result,
            nx=int(numerical_profile.size),
            xmin=xmin,
            xmax=xmax,
        )

    return InvestigationResult(
        scenario=scenario,
        solver=result.solver_name,
        out_path=result.out_path,
        postprocess_dir=result.postprocess_dir,
        x=np.asarray(x, dtype=float),
        topography_profile=np.asarray(topography_profile, dtype=float),
        analytical_profile=np.asarray(analytical_profile, dtype=float),
        numerical_profile=np.asarray(numerical_profile, dtype=float),
        residual_profile=residual_profile,
        clearance_profile=clearance_profile,
        rms_error=float("nan"),
        max_error=float("nan"),
        row_spread=max_std_along_axis(heads, axis=profile_axis),
        min_clearance_m=float(np.min(clearance_profile)),
        mean_clearance_m=float(np.mean(clearance_profile)),
        max_clearance_m=float(np.max(clearance_profile)),
        surface_lock_fraction=float(np.mean(np.abs(clearance_profile) <= CONTACT_TOLERANCE_M)),
        below_surface_fraction=float(np.mean(clearance_profile < -CONTACT_TOLERANCE_M)),
        locked_length_from_toe_m=_locked_length_from_toe(
            x,
            clearance_profile,
            tol_m=CONTACT_TOLERANCE_M,
        ),
        boussinesq_summary=bouss_summary,
        boussinesq_surface_profile_m3_day=bouss_surface_profile,
        boussinesq_drainage_profile_m3_day=bouss_drainage_profile,
    )


def _pairwise_rows(results: list[InvestigationResult]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    by_scenario: dict[str, list[InvestigationResult]] = {}
    for item in results:
        by_scenario.setdefault(item.scenario.scenario_id, []).append(item)
    for scenario_id, scenario_results in by_scenario.items():
        ordered = sorted(
            scenario_results,
            key=lambda item: SOLVER_ORDER.index(item.solver),
        )
        for idx, left in enumerate(ordered):
            for right in ordered[idx + 1 :]:
                x_common = np.linspace(
                    max(float(np.min(left.x)), float(np.min(right.x))),
                    min(float(np.max(left.x)), float(np.max(right.x))),
                    num=max(int(left.x.size), int(right.x.size)),
                    dtype=float,
                )
                left_values = np.interp(
                    x_common,
                    np.asarray(left.x, dtype=float),
                    np.asarray(left.numerical_profile, dtype=float),
                )
                right_values = np.interp(
                    x_common,
                    np.asarray(right.x, dtype=float),
                    np.asarray(right.numerical_profile, dtype=float),
                )
                diff = np.asarray(left_values - right_values, dtype=float)
                rows.append(
                    {
                        "scenario_id": scenario_id,
                        "scenario_label": left.scenario.label,
                        "solver_left": left.solver,
                        "solver_right": right.solver,
                        "pairwise_profile_rmse_m": float(np.sqrt(np.mean(diff**2))),
                        "pairwise_max_abs_error_m": float(np.max(np.abs(diff))),
                        "pairwise_mean_abs_error_m": float(np.mean(np.abs(diff))),
                    }
                )
    return rows


def _write_scenario_figure(
    *,
    scenario: ScenarioSpec,
    scenario_results: list[InvestigationResult],
    output_png: Path,
) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)
    ordered = sorted(
        scenario_results,
        key=lambda item: SOLVER_ORDER.index(item.solver),
    )
    ref = ordered[0]

    fig, axes = plt.subplots(
        3,
        1,
        figsize=(10.5, 10.0),
        sharex=True,
        constrained_layout=True,
    )

    axes[0].plot(
        ref.x,
        ref.topography_profile,
        color="#222222",
        linewidth=1.6,
        linestyle="--",
        label="Topography",
    )
    for item in ordered:
        axes[0].plot(
            item.x,
            item.numerical_profile,
            color=SOLVER_COLORS[item.solver],
            linewidth=1.8,
            label=SOLVER_LABELS[item.solver],
        )
    axes[0].set_ylabel("Head [m]")
    axes[0].grid(alpha=0.25, linewidth=0.6)
    axes[0].legend(loc="upper right", fontsize=8.8, frameon=False, ncols=2)

    for item in ordered:
        axes[1].plot(
            item.x,
            item.clearance_profile,
            color=SOLVER_COLORS[item.solver],
            linewidth=1.8,
        )
    axes[1].axhline(0.0, color="#444444", linewidth=0.9)
    axes[1].axhspan(
        -CONTACT_TOLERANCE_M,
        CONTACT_TOLERANCE_M,
        color="#d9d9d9",
        alpha=0.35,
    )
    axes[1].set_ylabel("h - z_top [m]")
    axes[1].grid(alpha=0.25, linewidth=0.6)

    labels_seen: set[str] = set()
    for idx, left in enumerate(ordered):
        for right in ordered[idx + 1 :]:
            label = f"{SOLVER_LABELS[left.solver]} - {SOLVER_LABELS[right.solver]}"
            x_common = np.linspace(
                max(float(np.min(left.x)), float(np.min(right.x))),
                min(float(np.max(left.x)), float(np.max(right.x))),
                num=max(int(left.x.size), int(right.x.size)),
                dtype=float,
            )
            diff = np.interp(
                x_common,
                np.asarray(left.x, dtype=float),
                np.asarray(left.numerical_profile, dtype=float),
            ) - np.interp(
                x_common,
                np.asarray(right.x, dtype=float),
                np.asarray(right.numerical_profile, dtype=float),
            )
            axes[2].plot(
                x_common,
                diff,
                linewidth=1.6,
                label=label if label not in labels_seen else None,
            )
            labels_seen.add(label)
    axes[2].axhline(0.0, color="#444444", linewidth=0.9)
    axes[2].set_ylabel("Solver - solver [m]")
    axes[2].set_xlabel("x [m]")
    axes[2].grid(alpha=0.25, linewidth=0.6)
    axes[2].legend(loc="upper right", fontsize=8.6, frameon=False)

    fig.suptitle(
        f"Simple hillslope surface interaction - {scenario.label}",
        fontsize=11.0,
    )
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _write_boussinesq_diagnostics_figure(
    *,
    scenario: ScenarioSpec,
    result: InvestigationResult,
    output_png: Path,
) -> None:
    if (
        result.boussinesq_surface_profile_m3_day is None
        or result.boussinesq_drainage_profile_m3_day is None
    ):
        return
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)

    summary = result.boussinesq_summary or {}
    fig, axes = plt.subplots(2, 1, figsize=(10.0, 7.5), constrained_layout=True)

    axes[0].plot(
        result.x,
        result.boussinesq_surface_profile_m3_day,
        color="#d62728",
        linewidth=1.8,
        label="Surface threshold",
    )
    axes[0].plot(
        result.x,
        result.boussinesq_drainage_profile_m3_day,
        color="#2ca02c",
        linewidth=1.8,
        label="Drainage",
    )
    axes[0].set_ylabel("Final flux by x-bin [m3/day]")
    axes[0].grid(alpha=0.25, linewidth=0.6)
    axes[0].legend(loc="upper right", fontsize=9.0, frameon=False)

    labels = [
        "Peak surface total",
        "Final surface total",
        "Peak active fraction",
        "Peak head above top",
    ]
    values = [
        float(summary.get("surface_threshold_peak_total_m3_day", 0.0)),
        float(summary.get("surface_threshold_final_total_m3_day", 0.0)),
        float(summary.get("surface_threshold_peak_active_fraction", 0.0)),
        float(summary.get("surface_threshold_peak_head_above_top_m", 0.0)),
    ]
    colors = ["#d62728", "#ff9896", "#9467bd", "#8c564b"]
    bars = axes[1].bar(
        np.arange(len(labels), dtype=float),
        values,
        color=colors,
        width=0.6,
    )
    axes[1].set_xticks(np.arange(len(labels), dtype=float))
    axes[1].set_xticklabels(labels, rotation=10, ha="right")
    axes[1].grid(axis="y", alpha=0.25, linewidth=0.6)
    for bar, value in zip(bars, values, strict=False):
        axes[1].text(
            bar.get_x() + bar.get_width() / 2.0,
            value,
            f"{value:.3g}",
            ha="center",
            va="bottom",
            fontsize=8,
        )

    fig.suptitle(
        f"Boussinesq surface diagnostics - {scenario.label}",
        fontsize=11.0,
    )
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _write_overview_figure(results: list[InvestigationResult], output_png: Path) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_png.unlink(missing_ok=True)

    scenario_ids = [
        item.scenario_id
        for item in DEFAULT_SCENARIOS
        if any(row.scenario.scenario_id == item.scenario_id for row in results)
    ]
    scenarios = [SCENARIO_BY_ID[item] for item in scenario_ids]
    solvers = [solver for solver in SOLVER_ORDER if any(row.solver == solver for row in results)]

    min_clearance = np.full((len(solvers), len(scenarios)), np.nan, dtype=float)
    locked_length = np.full((len(solvers), len(scenarios)), np.nan, dtype=float)
    bouss_surface_peak = np.full(len(scenarios), np.nan, dtype=float)
    index_scenario = {item.scenario_id: idx for idx, item in enumerate(scenarios)}
    index_solver = {solver: idx for idx, solver in enumerate(solvers)}

    for item in results:
        i = index_solver[item.solver]
        j = index_scenario[item.scenario.scenario_id]
        min_clearance[i, j] = item.min_clearance_m
        locked_length[i, j] = item.locked_length_from_toe_m
        if item.solver == "boussinesq" and item.boussinesq_summary is not None:
            bouss_surface_peak[j] = float(
                item.boussinesq_summary.get(
                    "surface_threshold_peak_total_m3_day",
                    np.nan,
                )
            )

    x = np.arange(len(scenarios), dtype=float)
    width = 0.22
    fig, axes = plt.subplots(3, 1, figsize=(10.5, 9.2), constrained_layout=True)
    for idx, solver in enumerate(solvers):
        offset = (idx - (len(solvers) - 1) / 2.0) * width
        axes[0].bar(
            x + offset,
            min_clearance[idx],
            width=width,
            color=SOLVER_COLORS[solver],
            label=SOLVER_LABELS[solver],
        )
        axes[1].bar(
            x + offset,
            locked_length[idx],
            width=width,
            color=SOLVER_COLORS[solver],
            label=SOLVER_LABELS[solver],
        )
    axes[0].set_ylabel("Min clearance [m]")
    axes[0].grid(axis="y", alpha=0.25, linewidth=0.6)
    axes[0].legend(fontsize=8.8, frameon=False, ncols=len(solvers))

    axes[1].set_ylabel("Locked length from toe [m]")
    axes[1].grid(axis="y", alpha=0.25, linewidth=0.6)

    bars = axes[2].bar(x, bouss_surface_peak, width=0.48, color="#d62728")
    axes[2].set_ylabel("Bouss peak surface total [m3/day]")
    axes[2].grid(axis="y", alpha=0.25, linewidth=0.6)
    for bar, value in zip(bars, bouss_surface_peak, strict=False):
        if np.isfinite(value):
            axes[2].text(
                bar.get_x() + bar.get_width() / 2.0,
                value,
                f"{value:.3g}",
                ha="center",
                va="bottom",
                fontsize=8,
            )
    axes[2].set_xticks(x)
    axes[2].set_xticklabels([item.label for item in scenarios], rotation=10, ha="right")

    fig.suptitle("Surface-interaction onset overview", fontsize=11.0)
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _write_markdown_summary(
    *,
    results: list[InvestigationResult],
    pairwise_rows: list[dict[str, Any]],
    output_md: Path,
    figures_dir: Path,
) -> None:
    by_scenario: dict[str, list[InvestigationResult]] = {}
    for item in results:
        by_scenario.setdefault(item.scenario.scenario_id, []).append(item)

    lines: list[str] = [
        "# Simple Hillslope Surface-Interaction Investigation",
        "",
        "This report keeps the same sloping 1D strip for MODFLOW-NWT, MODFLOW 6, and Boussinesq.",
        "The setup uses west no-flow, east fixed head, uniform recharge, and distributed top drainage.",
        "",
        f"Surface-lock tolerance: `{CONTACT_TOLERANCE_M:.3f} m`.",
        "",
    ]
    for scenario in DEFAULT_SCENARIOS:
        if scenario.scenario_id not in by_scenario:
            continue
        scenario_results = sorted(
            by_scenario[scenario.scenario_id],
            key=lambda item: SOLVER_ORDER.index(item.solver),
        )
        lines.append(f"## {scenario.label}")
        lines.append("")
        lines.append(f"- recharge: `{scenario.recharge_mm_day:.3f} mm/day`")
        lines.append(f"- drainage conductance: `{scenario.drainage_conductance_m2_per_s:.3g} m2/s`")
        lines.append(f"- hydraulic conductivity scale: `{HYDRAULIC_CONDUCTIVITY_SCALE:.3f}x`")
        lines.append("")
        lines.append(
            "| Solver | Row spread [m] | Min clearance [m] | Mean clearance [m] | Surface-lock fraction | Locked length from toe [m] | Results dir |"
        )
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | --- |")
        for item in scenario_results:
            lines.append(
                f"| {SOLVER_LABELS[item.solver]} | {item.row_spread:.4f} | {item.min_clearance_m:.4f} | {item.mean_clearance_m:.4f} | {item.surface_lock_fraction:.3f} | {item.locked_length_from_toe_m:.2f} | `{item.out_path}` |"
            )
        case_pairwise = [row for row in pairwise_rows if row["scenario_id"] == scenario.scenario_id]
        if case_pairwise:
            lines.append("")
            lines.append(
                "| Pair | Pairwise RMSE [m] | Pairwise max abs error [m] | Pairwise mean abs error [m] |"
            )
            lines.append("| --- | ---: | ---: | ---: |")
            for row in case_pairwise:
                lines.append(
                    f"| {SOLVER_LABELS[row['solver_left']]} vs {SOLVER_LABELS[row['solver_right']]} | {row['pairwise_profile_rmse_m']:.4f} | {row['pairwise_max_abs_error_m']:.4f} | {row['pairwise_mean_abs_error_m']:.4f} |"
                )
        bouss = next(
            (item for item in scenario_results if item.solver == "boussinesq"),
            None,
        )
        if bouss is not None and bouss.boussinesq_summary is not None:
            summary = bouss.boussinesq_summary
            lines.append("")
            lines.append("| Boussinesq surface diagnostic | Value |")
            lines.append("| --- | ---: |")
            lines.append(
                f"| Peak surface threshold total [m3/day] | {float(summary.get('surface_threshold_peak_total_m3_day', 0.0)):.4f} |"
            )
            lines.append(
                f"| Final surface threshold total [m3/day] | {float(summary.get('surface_threshold_final_total_m3_day', 0.0)):.4f} |"
            )
            lines.append(
                f"| Peak active fraction | {float(summary.get('surface_threshold_peak_active_fraction', 0.0)):.4f} |"
            )
            lines.append(
                f"| Peak head above top [m] | {float(summary.get('surface_threshold_peak_head_above_top_m', 0.0)):.4f} |"
            )
        lines.append("")
        lines.append(f"Figure: `{figures_dir / f'{_slug(scenario.scenario_id)}__profiles.png'}`")
        lines.append(
            f"Boussinesq diagnostics: `{figures_dir / f'{_slug(scenario.scenario_id)}__boussinesq_surface.png'}`"
        )
        lines.append("")

    lines.append(f"Overview: `{figures_dir / 'surface_onset_overview.png'}`")
    lines.append("")
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Investigate simple hillslope surface interaction across "
            "MODFLOW-NWT, MODFLOW 6, and Boussinesq."
        )
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / "out" / "sih_divide_20260413",
        help="Directory where the report and run artifacts are written.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=1800,
        help="Per-solver timeout in seconds.",
    )
    parser.add_argument(
        "--scenarios",
        nargs="+",
        default=[item.scenario_id for item in DEFAULT_SCENARIOS],
        choices=sorted(SCENARIO_BY_ID),
        help="Scenario ids to execute.",
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
    selected_scenarios = [SCENARIO_BY_ID[item] for item in args.scenarios]
    results: list[InvestigationResult] = []
    for scenario in selected_scenarios:
        for solver in ("modflownwt", "modflow6"):
            run_result = _run_launcher_solver_scenario(
                metadata=metadata,
                scenario=scenario,
                solver=solver,
                hydraulic_conductivity_m_s=hydraulic_conductivity_m_s,
                timeout=int(args.timeout),
                runtime_configs_dir=runtime_configs_dir,
            )
            results.append(
                _build_investigation_result(
                    metadata=metadata,
                    scenario=scenario,
                    result=run_result,
                )
            )
        bouss_result = _run_boussinesq_scenario(
            scenario=scenario,
            timeout=int(args.timeout),
            length_x_m=LENGTH_X_M,
            width_y_m=WIDTH_Y_M,
            nx=BOUSS_NX,
            ny=BOUSS_NY,
            aquifer_thickness_m=AQUIFER_THICKNESS_M,
            hydraulic_conductivity_m_s=hydraulic_conductivity_m_s,
        )
        results.append(
            _build_investigation_result(
                metadata=metadata,
                scenario=scenario,
                result=bouss_result,
            )
        )

    metrics_rows = [
        {
            "scenario_id": item.scenario.scenario_id,
            "scenario_label": item.scenario.label,
            "solver": item.solver,
            "solver_label": SOLVER_LABELS[item.solver],
            "row_spread_m": item.row_spread,
            "min_clearance_m": item.min_clearance_m,
            "mean_clearance_m": item.mean_clearance_m,
            "max_clearance_m": item.max_clearance_m,
            "surface_lock_fraction": item.surface_lock_fraction,
            "below_surface_fraction": item.below_surface_fraction,
            "locked_length_from_toe_m": item.locked_length_from_toe_m,
            "results_dir": str(item.out_path),
            "postprocess_dir": str(item.postprocess_dir),
        }
        for item in results
    ]
    pairwise_rows = _pairwise_rows(results)
    bouss_rows = [
        {
            "scenario_id": item.scenario.scenario_id,
            "scenario_label": item.scenario.label,
            "surface_threshold_peak_total_m3_day": float(
                (item.boussinesq_summary or {}).get(
                    "surface_threshold_peak_total_m3_day",
                    0.0,
                )
            ),
            "surface_threshold_final_total_m3_day": float(
                (item.boussinesq_summary or {}).get(
                    "surface_threshold_final_total_m3_day",
                    0.0,
                )
            ),
            "surface_threshold_peak_active_fraction": float(
                (item.boussinesq_summary or {}).get(
                    "surface_threshold_peak_active_fraction",
                    0.0,
                )
            ),
            "surface_threshold_peak_head_above_top_m": float(
                (item.boussinesq_summary or {}).get(
                    "surface_threshold_peak_head_above_top_m",
                    0.0,
                )
            ),
            "results_dir": str(item.out_path),
        }
        for item in results
        if item.solver == "boussinesq"
    ]
    _write_csv(output_root / "metrics.csv", metrics_rows)
    _write_csv(output_root / "pairwise_metrics.csv", pairwise_rows)
    _write_csv(output_root / "boussinesq_surface_metrics.csv", bouss_rows)

    figures_dir = output_root / "figures"
    for scenario in selected_scenarios:
        scenario_results = [
            item for item in results if item.scenario.scenario_id == scenario.scenario_id
        ]
        _write_scenario_figure(
            scenario=scenario,
            scenario_results=scenario_results,
            output_png=figures_dir / f"{_slug(scenario.scenario_id)}__profiles.png",
        )
        bouss = next(
            (item for item in scenario_results if item.solver == "boussinesq"),
            None,
        )
        if bouss is not None:
            _write_boussinesq_diagnostics_figure(
                scenario=scenario,
                result=bouss,
                output_png=figures_dir / f"{_slug(scenario.scenario_id)}__boussinesq_surface.png",
            )
    _write_overview_figure(results, figures_dir / "surface_onset_overview.png")

    _write_markdown_summary(
        results=results,
        pairwise_rows=pairwise_rows,
        output_md=output_root / "summary.md",
        figures_dir=figures_dir,
    )
    (output_root / "summary.json").write_text(
        json.dumps(
            {
                "scenarios": [item.scenario_id for item in selected_scenarios],
                "solvers": list(SOLVER_ORDER),
                "metrics_csv": str(output_root / "metrics.csv"),
                "pairwise_metrics_csv": str(output_root / "pairwise_metrics.csv"),
                "boussinesq_surface_metrics_csv": str(
                    output_root / "boussinesq_surface_metrics.csv"
                ),
                "summary_md": str(output_root / "summary.md"),
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
