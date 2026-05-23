"""Run a focused strict stationary Boussinesq Picard/L-scheme matrix.

This is an investigation script only.  It calls the isolated experimental
``stationary_picard_lscheme`` runtime directly and does not change HydroModPy's
default Boussinesq solve path.  The Picard runtime keeps the original strict
problem definition: no minimum saturated-thickness floor and no added surface
conductance.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import tomllib
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import run_bouss_stationary_method_matrix as baseline  # noqa: E402

from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh  # noqa: E402
from hydromodpy.solver.boussinesq.runtime_contract import (  # noqa: E402
    NonlinearRuntimeOptions,
    SteadySolveInputs,
    TransientStepInputs,
)
from hydromodpy.solver.boussinesq.runtimes import petsc_vi_obstacle  # noqa: E402
from hydromodpy.solver.boussinesq.runtimes.stationary_picard_lscheme import (  # noqa: E402
    PicardLschemeOptions,
    PicardViCycleOptions,
    bounded_picard_lscheme,
    bounded_picard_vi_cycles,
)
from hydromodpy.spatial.mesh.gmsh_grid.catchment_mesh_bundle_reader import (  # noqa: E402
    load_catchment_mesh_bundle,
)

DEFAULT_OUTPUT_DIR = "docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_lscheme"
MATRIX_CSV = "stationary_strict_picard_lscheme_matrix.csv"
MATRIX_JSON = "stationary_strict_picard_lscheme_matrix.json"
SECONDS_PER_DAY = 86_400.0

METHODS = (
    "bounded_picard_lscheme",
    "bounded_picard_lscheme_then_vi",
    "bounded_picard_vi_cycles",
)

EXTRA_CASES: tuple[baseline.CaseSpec, ...] = (
    baseline.CaseSpec(
        case_id="site_02_k_high__bouss_tri_irregular_drain_00",
        source_config=baseline.MATRIX_OUTPUT_ROOT
        / "site_02_k_high_natural_drainage_k_mesh_matrix"
        / "_generated_configs"
        / "bouss_tri_irregular_drain_00.toml",
        known_status="drainage-zero stress case, larger site_02, K high",
        include_by_default=False,
    ),
    baseline.CaseSpec(
        case_id="site_02_k_low__bouss_tri_irregular_drain_01",
        source_config=baseline.MATRIX_OUTPUT_ROOT
        / "site_02_k_low_natural_drainage_k_mesh_matrix"
        / "_generated_configs"
        / "bouss_tri_irregular_drain_01.toml",
        known_status="site_02 K low, irregular mesh, drainage 0.1 m2/s",
        include_by_default=False,
    ),
    baseline.CaseSpec(
        case_id="site_02_k_base__bouss_tri_irregular_drain_01",
        source_config=baseline.MATRIX_OUTPUT_ROOT
        / "site_02_k_base_natural_drainage_k_mesh_matrix"
        / "_generated_configs"
        / "bouss_tri_irregular_drain_01.toml",
        known_status="site_02 K base, irregular mesh, drainage 0.1 m2/s",
        include_by_default=False,
    ),
    baseline.CaseSpec(
        case_id="site_02_k_high__bouss_tri_irregular_drain_01",
        source_config=baseline.MATRIX_OUTPUT_ROOT
        / "site_02_k_high_natural_drainage_k_mesh_matrix"
        / "_generated_configs"
        / "bouss_tri_irregular_drain_01.toml",
        known_status="site_02 K high, irregular mesh, drainage 0.1 m2/s",
        include_by_default=False,
    ),
    baseline.CaseSpec(
        case_id="site_01_k_base__bouss_tri_uniform_rivers_drain_00",
        source_config=baseline.MATRIX_OUTPUT_ROOT
        / "site_01_k_base_natural_drainage_k_mesh_matrix"
        / "_generated_configs"
        / "bouss_tri_uniform_rivers_drain_00.toml",
        known_status="site_01 K base, uniform-rivers mesh, drainage zero",
        include_by_default=False,
    ),
    baseline.CaseSpec(
        case_id="site_01_k_high__bouss_tri_uniform_rivers_drain_01",
        source_config=baseline.MATRIX_OUTPUT_ROOT
        / "site_01_k_high_natural_drainage_k_mesh_matrix"
        / "_generated_configs"
        / "bouss_tri_uniform_rivers_drain_01.toml",
        known_status="site_01 K high, uniform-rivers mesh, drainage 0.1 m2/s",
        include_by_default=False,
    ),
    baseline.CaseSpec(
        case_id="site_02_k_low__bouss_tri_uniform_rivers_drain_01",
        source_config=baseline.MATRIX_OUTPUT_ROOT
        / "site_02_k_low_natural_drainage_k_mesh_matrix"
        / "_generated_configs"
        / "bouss_tri_uniform_rivers_drain_01.toml",
        known_status="site_02 K low, uniform-rivers mesh, drainage 0.1 m2/s",
        include_by_default=False,
    ),
    baseline.CaseSpec(
        case_id="site_02_k_base__bouss_tri_uniform_rivers_drain_01",
        source_config=baseline.MATRIX_OUTPUT_ROOT
        / "site_02_k_base_natural_drainage_k_mesh_matrix"
        / "_generated_configs"
        / "bouss_tri_uniform_rivers_drain_01.toml",
        known_status="site_02 K base, uniform-rivers mesh, drainage 0.1 m2/s",
        include_by_default=False,
    ),
    baseline.CaseSpec(
        case_id="site_02_k_high__bouss_tri_uniform_rivers_drain_01",
        source_config=baseline.MATRIX_OUTPUT_ROOT
        / "site_02_k_high_natural_drainage_k_mesh_matrix"
        / "_generated_configs"
        / "bouss_tri_uniform_rivers_drain_01.toml",
        known_status="site_02 K high, uniform-rivers mesh, drainage 0.1 m2/s",
        include_by_default=False,
    ),
    baseline.CaseSpec(
        case_id="site_03_hetero__n1_drain_00",
        source_config=REPO_ROOT
        / "examples/projects/10_testbed_workflow/outputs"
        / "boussinesq_natural_n1_10km2_testbed"
        / "comparisons/site_03_natural_n1_10km2_mf6_bouss"
        / "_generated_configs/bouss_candidate.toml",
        known_status="site_03 natural N1, geology-derived heterogeneous K, drainage zero",
        include_by_default=False,
    ),
    baseline.CaseSpec(
        case_id="site_08_hetero__n1_drain_00",
        source_config=REPO_ROOT
        / "examples/projects/10_testbed_workflow/outputs"
        / "boussinesq_natural_n1_10km2_testbed"
        / "comparisons/site_08_natural_n1_10km2_mf6_bouss"
        / "_generated_configs/bouss_candidate.toml",
        known_status="site_08 natural N1, geology-derived heterogeneous K, drainage zero",
        include_by_default=False,
    ),
    baseline.CaseSpec(
        case_id="site_03_hetero__petsc_regression_drain_01",
        source_config=REPO_ROOT
        / "examples/projects/10_testbed_workflow/outputs"
        / "boussinesq_petsc_vi_regression_testbed"
        / "comparisons/site_03_natural_10km2_mf6_bouss_petsc_vi"
        / "_generated_configs/bouss_candidate.toml",
        known_status="site_03 PETSc VI regression, geology-derived heterogeneous K, drainage 0.1 m2/s",
        include_by_default=False,
    ),
    baseline.CaseSpec(
        case_id="site_08_hetero__petsc_regression_drain_01",
        source_config=REPO_ROOT
        / "examples/projects/10_testbed_workflow/outputs"
        / "boussinesq_petsc_vi_regression_testbed"
        / "comparisons/site_08_natural_10km2_mf6_bouss_petsc_vi"
        / "_generated_configs/bouss_candidate.toml",
        known_status="site_08 PETSc VI regression, geology-derived heterogeneous K, drainage 0.1 m2/s",
        include_by_default=False,
    ),
    baseline.CaseSpec(
        case_id="headwater_100km2_outlet_2_hetero__petsc_regression_drain_01",
        source_config=REPO_ROOT
        / "examples/projects/10_testbed_workflow/outputs"
        / "boussinesq_petsc_vi_regression_testbed"
        / "comparisons/headwater_100km2_outlet_2_natural_100km2_mf6_bouss_petsc_vi"
        / "_generated_configs/bouss_candidate.toml",
        known_status="headwater 100 km2 outlet 2, external mesh bundle, heterogeneous K, drainage 0.1 m2/s",
        include_by_default=False,
    ),
)

ALL_CASES: tuple[baseline.CaseSpec, ...] = baseline.CASES + EXTRA_CASES
DEFAULT_CASE_IDS = (
    "site_01_k_high__bouss_tri_irregular_drain_00",
    "site_01_k_high__bouss_tri_irregular_drain_01",
    "site_01_k_high__bouss_tri_irregular_drain_001",
)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    selected_cases = _selected_cases(args.case)
    selected_methods = tuple(args.method or ("bounded_picard_lscheme",))

    command_payload = {
        "argv": list(argv) if argv is not None else sys.argv[1:],
        "cases": [case.case_id for case in selected_cases],
        "methods": list(selected_methods),
        "omega": float(args.omega),
        "Lstab": args.Lstab,
        "max_iterations": int(args.max_iterations),
        "cycle_max": int(args.cycle_max),
        "picard_steps_per_cycle": int(args.picard_steps_per_cycle),
        "vi_max_iterations_per_cycle": int(args.vi_max_iterations_per_cycle),
        "accept_failed_vi_residual_factor": float(args.accept_failed_vi_residual_factor),
        "probe_transient": bool(args.probe_transient),
        "probe_dt_days": float(args.probe_dt_days),
        "output_dir": str(output_dir),
        "strict_problem_definition": True,
    }
    (output_dir / "run_command.json").write_text(
        json.dumps(command_payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    rows: list[dict[str, Any]] = []
    for spec in selected_cases:
        loaded = _load_case(spec)
        k_stats = _k_stats(loaded.mesh)
        print(
            f"[case] {spec.case_id}: n={loaded.mesh.n_cells}, "
            f"K=[{k_stats['k_min']:.3g}, {k_stats['k_median']:.3g}, "
            f"{k_stats['k_max']:.3g}], drainage={loaded.drainage_conductance_m2_s:g}",
            flush=True,
        )
        for method in selected_methods:
            print(f"  [method] {method}", flush=True)
            method_dir = output_dir / "diagnostics" / spec.case_id / method
            method_dir.mkdir(parents=True, exist_ok=True)
            started = time.perf_counter()
            try:
                result = _run_picard_method(
                    method,
                    loaded,
                    method_dir=method_dir,
                    args=args,
                )
                probe = (
                    _probe_transient(loaded, result, args=args)
                    if bool(args.probe_transient)
                    else {}
                )
                row = _row(
                    loaded=loaded,
                    method=method,
                    result=result,
                    elapsed_s=time.perf_counter() - started,
                    diagnostics_dir=method_dir,
                    probe=probe,
                )
                rows.append(row)
                print(
                    "    -> "
                    f"{'OK' if result.converged else 'FAIL'} "
                    f"res={result.residual_norm_inf:.3e} "
                    f"it={result.iterations} "
                    f"{result.termination_reason}",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001 - investigation script
                row = baseline._exception_row(loaded, method, exc)
                row["diagnostics_dir"] = str(method_dir)
                row["elapsed_s"] = time.perf_counter() - started
                rows.append(row)
                (method_dir / "exception.json").write_text(
                    json.dumps(
                        {"method": method, "exception": repr(exc)},
                        indent=2,
                        ensure_ascii=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                print(f"    -> exception: {exc}", flush=True)

    _write_outputs(output_dir, rows)
    return 0


def _parse_args(argv: Iterable[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--case",
        action="append",
        choices=tuple(case.case_id for case in ALL_CASES),
        help="Case id to run. Can be repeated.",
    )
    parser.add_argument(
        "--method",
        action="append",
        choices=METHODS,
        help="Picard method variant to run. Can be repeated.",
    )
    parser.add_argument("--omega", type=float, default=0.5)
    parser.add_argument("--Lstab", default="auto")
    parser.add_argument("--max-iterations", type=int, default=500)
    parser.add_argument("--cycle-max", type=int, default=10)
    parser.add_argument("--picard-steps-per-cycle", type=int, default=200)
    parser.add_argument("--vi-max-iterations-per-cycle", type=int, default=20)
    parser.add_argument("--accept-failed-vi-residual-factor", type=float, default=0.5)
    parser.add_argument("--probe-transient", action="store_true")
    parser.add_argument("--probe-dt-days", type=float, default=30.0)
    return parser.parse_args(tuple(argv) if argv is not None else None)


def _run_picard_method(
    method: str,
    loaded: baseline.LoadedCase,
    *,
    method_dir: Path,
    args: argparse.Namespace,
):
    if method == "bounded_picard_vi_cycles":
        picard_options = PicardLschemeOptions(
            picard_max_iterations=int(args.picard_steps_per_cycle),
            picard_tolerance_residual_inf=float(loaded.options.tol_residual_inf),
            picard_tolerance_update_inf=float(loaded.options.tol_state_update_inf),
            picard_relaxation_omega=float(args.omega),
            picard_lscheme_L=_parse_lstab(args.Lstab),
            picard_final_vi_check=False,
            picard_fail_if_final_vi_fails=False,
            picard_output_diagnostics=False,
        )
        cycle_options = PicardViCycleOptions(
            cycle_max=int(args.cycle_max),
            picard_steps_per_cycle=int(args.picard_steps_per_cycle),
            vi_max_iterations_per_cycle=int(args.vi_max_iterations_per_cycle),
            accept_failed_vi_residual_factor=float(args.accept_failed_vi_residual_factor),
            picard_options=picard_options,
            output_diagnostics=True,
        )
        return bounded_picard_vi_cycles(
            SteadySolveInputs(
                mesh=loaded.mesh,
                head_initial_guess_m=np.asarray(loaded.mesh.z_top_m, dtype=float),
                recharge_rate_m_s=loaded.recharge_rate_m_s,
                well_flux_m3_s=None,
                prescribed_head_m_by_cell=None,
                drainage_conductance_m2_s=loaded.drainage_conductance_m2_s,
                options=loaded.options,
            ),
            cycle_options=cycle_options,
            diagnostics_dir=method_dir,
            case_id=loaded.spec.case_id,
        )

    final_vi = method.endswith("_then_vi")
    picard_options = PicardLschemeOptions(
        picard_max_iterations=int(args.max_iterations),
        picard_tolerance_residual_inf=float(loaded.options.tol_residual_inf),
        picard_tolerance_update_inf=float(loaded.options.tol_state_update_inf),
        picard_relaxation_omega=float(args.omega),
        picard_lscheme_L=_parse_lstab(args.Lstab),
        picard_final_vi_check=bool(final_vi),
        picard_fail_if_final_vi_fails=False,
        picard_output_diagnostics=True,
    )
    return bounded_picard_lscheme(
        SteadySolveInputs(
            mesh=loaded.mesh,
            head_initial_guess_m=np.asarray(loaded.mesh.z_top_m, dtype=float),
            recharge_rate_m_s=loaded.recharge_rate_m_s,
            well_flux_m3_s=None,
            prescribed_head_m_by_cell=None,
            drainage_conductance_m2_s=loaded.drainage_conductance_m2_s,
            options=loaded.options,
        ),
        picard_options=picard_options,
        diagnostics_dir=method_dir,
        case_id=loaded.spec.case_id,
    )


def _row(
    *,
    loaded: baseline.LoadedCase,
    method: str,
    result,
    elapsed_s: float,
    diagnostics_dir: Path,
    probe: dict[str, Any],
) -> dict[str, Any]:
    diagnostics = dict(result.diagnostics or {})
    row = {
        "case": loaded.spec.case_id,
        "method": method,
        "converged": bool(result.converged),
        "residual_norm_inf": float(result.residual_norm_inf),
        "iterations": int(result.iterations),
        "elapsed_s": float(elapsed_s),
        "termination_reason": str(result.termination_reason),
        "strict_problem_definition": bool(diagnostics.get("strict_problem_definition", False)),
        "usable_as_initial_guess": bool(diagnostics.get("usable_as_initial_guess", False)),
        "picard_stop_reason": diagnostics.get("picard_stop_reason"),
        "final_vi_check_enabled": diagnostics.get("final_vi_check_enabled"),
        "final_vi_converged": diagnostics.get("final_vi_converged"),
        "final_vi_residual": diagnostics.get("final_vi_residual"),
        "cycle_count": diagnostics.get("cycle_count"),
        "total_picard_iterations": diagnostics.get("total_picard_iterations"),
        "vi_attempt_count": diagnostics.get("vi_attempt_count"),
        "accepted_failed_vi_count": diagnostics.get("accepted_failed_vi_count"),
        "Lstab": diagnostics.get("Lstab"),
        "omega_final": diagnostics.get("omega_final"),
        "active_bottom_count": diagnostics.get(
            "active_bottom_count", diagnostics.get("bottom_active_cells")
        ),
        "active_top_count": diagnostics.get(
            "active_top_count", diagnostics.get("surface_active_cells")
        ),
        "free_count": diagnostics.get("free_count"),
        "cells_physically_dry_count": diagnostics.get("cells_physically_dry_count"),
        "h_min": diagnostics.get("h_min"),
        "h_max": diagnostics.get("h_max"),
        "diagnostics_dir": str(diagnostics_dir),
    }
    row.update(_k_stats(loaded.mesh))
    row.update(probe)
    return row


def _probe_transient(
    loaded: baseline.LoadedCase,
    result,
    *,
    args: argparse.Namespace,
) -> dict[str, Any]:
    if not bool(result.converged):
        return {
            "probe_transient_attempted": False,
            "probe_transient_skipped_reason": "stationary_not_converged",
        }
    try:
        transient = petsc_vi_obstacle.solve_transient_step(
            TransientStepInputs(
                mesh=loaded.mesh,
                head_prev_m=np.asarray(result.head_m, dtype=float),
                head_initial_guess_m=np.asarray(result.head_m, dtype=float),
                dt_seconds=float(args.probe_dt_days) * SECONDS_PER_DAY,
                recharge_rate_m_s=loaded.recharge_rate_m_s,
                well_flux_m3_s=None,
                prescribed_head_m_by_cell=None,
                drainage_conductance_m2_s=loaded.drainage_conductance_m2_s,
                options=loaded.options,
            )
        )
    except Exception as exc:  # noqa: BLE001 - investigation probe
        return {
            "probe_transient_attempted": True,
            "probe_transient_converged": False,
            "probe_transient_error": repr(exc),
        }
    return {
        "probe_transient_attempted": True,
        "probe_transient_converged": bool(transient.converged),
        "probe_transient_residual": float(transient.residual_norm_inf),
        "probe_transient_iterations": int(transient.iterations),
        "probe_transient_termination_reason": str(transient.termination_reason),
    }


def _selected_cases(case_ids: list[str] | None) -> tuple[baseline.CaseSpec, ...]:
    if not case_ids:
        requested = set(DEFAULT_CASE_IDS)
    else:
        requested = set(case_ids)
    return tuple(case for case in ALL_CASES if case.case_id in requested)


def _load_case(spec: baseline.CaseSpec) -> baseline.LoadedCase:
    config_path = _resolve_path(spec.source_config)
    with config_path.open("rb") as handle:
        config = tomllib.load(handle)

    workspace_root = Path(config["workspace"]["project_root"])
    bundle_dir = workspace_root / "mesh" / "mesh_catchment_bundle"
    if not bundle_dir.exists():
        mesh_input_dir = config.get("mesh_input", {}).get("bundle_dir")
        if mesh_input_dir is None:
            raise FileNotFoundError(f"Mesh bundle not found: {bundle_dir}")
        bundle_dir = _resolve_path(mesh_input_dir)
    if not bundle_dir.exists():
        raise FileNotFoundError(f"Mesh bundle not found: {bundle_dir}")

    sy_value = _field_value(config, "Sy")
    bundle = load_catchment_mesh_bundle(bundle_dir)
    if any(cell.storage_coefficient is None for cell in bundle.cells):
        bundle = replace(
            bundle,
            cells=tuple(
                replace(cell, storage_coefficient=float(sy_value)) for cell in bundle.cells
            ),
        )
    mesh0 = BoussinesqMesh.from_bundle(bundle)
    k_field = config["flow"]["param"]["K"]["field"]
    k_kind = str(k_field.get("kind", "")).strip().lower()
    if k_kind == "homogeneous" or "value" in k_field:
        k_values = np.full(mesh0.n_cells, _first_float(k_field["value"]), dtype=float)
    else:
        k_values = np.asarray(mesh0.hydraulic_conductivity_m_s, dtype=float)
        if k_values.size != mesh0.n_cells or not np.all(np.isfinite(k_values)):
            raise ValueError(
                f"Heterogeneous K case requires finite per-cell bundle K values: {spec.case_id}"
            )
        if np.any(k_values <= 0.0):
            raise ValueError(f"Heterogeneous K case has non-positive K values: {spec.case_id}")

    mesh = replace(
        mesh0,
        hydraulic_conductivity_m_s=k_values,
        storage_coefficient=np.full(mesh0.n_cells, sy_value, dtype=float),
    )
    flow = config["flow"]
    options = NonlinearRuntimeOptions(
        regularization_radius=0.05,
        max_iterations=int(flow.get("runtime_max_iterations", 240)),
        tol_residual_inf=float(flow.get("runtime_tol_residual_inf", 1.0e-6)),
        tol_state_update_inf=float(flow.get("runtime_tol_state_update_inf", 1.0e-6)),
        vi_substeps_per_period=int(flow.get("vi_substeps_per_period", 1) or 1),
        vi_substep_on_failure=bool(flow.get("vi_substep_on_failure", False)),
        vi_max_adaptive_substeps=int(flow.get("vi_max_adaptive_substeps", 1) or 1),
    )
    return baseline.LoadedCase(
        spec=spec,
        mesh=mesh,
        recharge_rate_m_s=_mean_recharge_m_s(config),
        drainage_conductance_m2_s=_drainage_conductance_m2_s(config),
        k_value_m_s=float(np.median(k_values)),
        sy_value=sy_value,
        options=options,
    )


def _k_stats(mesh: BoussinesqMesh) -> dict[str, Any]:
    k_values = np.asarray(mesh.hydraulic_conductivity_m_s, dtype=float)
    return {
        "k_min": float(np.min(k_values)),
        "k_p10": float(np.quantile(k_values, 0.10)),
        "k_median": float(np.median(k_values)),
        "k_p90": float(np.quantile(k_values, 0.90)),
        "k_max": float(np.max(k_values)),
        "k_unique_count": int(np.unique(k_values).size),
    }


def _field_value(config: dict[str, Any], name: str) -> float:
    return _first_float(config["flow"]["param"][name]["field"]["value"])


def _mean_recharge_m_s(config: dict[str, Any]) -> float:
    source = config.get("data", {}).get("recharge", {}).get("sources", [{}])[0]
    values = source.get("values", 0.0)
    values_array = np.asarray(values if isinstance(values, list) else [values], dtype=float)
    return float(np.mean(values_array)) / 1_000.0 / SECONDS_PER_DAY


def _drainage_conductance_m2_s(config: dict[str, Any]) -> float:
    drainage = config["flow"]["bc"]["cauchy"]["drainage"]
    return _first_float(drainage["value"])


def _first_float(value: Any) -> float:
    return float(str(value).split()[0])


def _resolve_path(path: str | Path) -> Path:
    value = Path(path)
    if value.is_absolute():
        return value
    return REPO_ROOT / value


def _parse_lstab(value: str) -> float | str:
    text = str(value).strip().lower()
    if text == "auto":
        return "auto"
    return float(text)


def _write_outputs(output_dir: Path, rows: list[dict[str, Any]]) -> None:
    csv_path = output_dir / MATRIX_CSV
    json_path = output_dir / MATRIX_JSON
    md_path = output_dir / "stationary_strict_picard_lscheme_matrix_summary.md"
    _write_csv(csv_path, rows)
    json_path.write_text(
        json.dumps(_jsonable(rows), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    _write_markdown(md_path, rows)
    print(f"[written] {csv_path}")
    print(f"[written] {json_path}")
    print(f"[written] {md_path}")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Strict stationary Picard/L-scheme matrix summary",
        "",
        "| case | method | converged | final VI | residual | active bottom | active top | runtime s | usable IC |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("case", "")),
                    str(row.get("method", "")),
                    str(row.get("converged", "")),
                    str(row.get("final_vi_converged", "")),
                    _fmt(row.get("residual_norm_inf")),
                    str(row.get("active_bottom_count", "")),
                    str(row.get("active_top_count", "")),
                    _fmt(row.get("elapsed_s")),
                    str(row.get("usable_as_initial_guess", "")),
                ]
            )
            + " |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fmt(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if not np.isfinite(number):
        return ""
    return f"{number:.3g}"


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value


if __name__ == "__main__":
    raise SystemExit(main())
