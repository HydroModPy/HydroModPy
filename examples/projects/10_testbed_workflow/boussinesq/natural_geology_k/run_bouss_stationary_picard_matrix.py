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
from collections.abc import Iterable
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

from hydromodpy.solver.boussinesq.runtime_contract import SteadySolveInputs  # noqa: E402
from hydromodpy.solver.boussinesq.runtimes.stationary_picard_lscheme import (  # noqa: E402
    PicardLschemeOptions,
    PicardViCycleOptions,
    bounded_picard_lscheme,
    bounded_picard_vi_cycles,
)

DEFAULT_OUTPUT_DIR = "docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_lscheme"
MATRIX_CSV = "stationary_strict_picard_lscheme_matrix.csv"
MATRIX_JSON = "stationary_strict_picard_lscheme_matrix.json"

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
        case_id="site_01_k_base__bouss_tri_uniform_rivers_drain_00",
        source_config=baseline.MATRIX_OUTPUT_ROOT
        / "site_01_k_base_natural_drainage_k_mesh_matrix"
        / "_generated_configs"
        / "bouss_tri_uniform_rivers_drain_00.toml",
        known_status="site_01 K base, uniform-rivers mesh, drainage zero",
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
        "output_dir": str(output_dir),
        "strict_problem_definition": True,
    }
    (output_dir / "run_command.json").write_text(
        json.dumps(command_payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    rows: list[dict[str, Any]] = []
    for spec in selected_cases:
        loaded = baseline.load_case(spec)
        print(
            f"[case] {spec.case_id}: n={loaded.mesh.n_cells}, "
            f"K={loaded.k_value_m_s:g}, drainage={loaded.drainage_conductance_m2_s:g}",
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
                row = _row(
                    loaded=loaded,
                    method=method,
                    result=result,
                    elapsed_s=time.perf_counter() - started,
                    diagnostics_dir=method_dir,
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
) -> dict[str, Any]:
    diagnostics = dict(result.diagnostics or {})
    return {
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


def _selected_cases(case_ids: list[str] | None) -> tuple[baseline.CaseSpec, ...]:
    if not case_ids:
        requested = set(DEFAULT_CASE_IDS)
    else:
        requested = set(case_ids)
    return tuple(case for case in ALL_CASES if case.case_id in requested)


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
