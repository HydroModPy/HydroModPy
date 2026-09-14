"""CLI entrypoint for the LAK ex-gwf-lak-p01 validation case.

Runs the upstream feet/days reference and the HMP meters/seconds DISV build, then
prints the structural and numerical metrics with a PASS / FAIL verdict against
``tolerances.toml``.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from .comparison import LakeP01Scenario, load_tolerances, run_lake_p01_scenario


def _verdict(value: float, threshold: float, *, name: str) -> str:
    status = "PASS" if value <= threshold else "FAIL"
    return f"  [{status}] {name}: {value:.6g} (tol {threshold:.6g})"


def _structural_verdict(actual: int, expected: int, *, name: str) -> str:
    status = "PASS" if actual == expected else "FAIL"
    return f"  [{status}] {name}: {actual} (expected {expected})"


def print_report(scenario: LakeP01Scenario, tolerances: dict) -> bool:
    """Print the metric report and return True when every metric passes."""
    stage_tol = dict(tolerances["stage"])
    exchange_tol = dict(tolerances["exchange"])
    budget_tol = dict(tolerances["budget"])
    structural_tol = dict(tolerances["structural"])

    print("LAK ex-gwf-lak-p01 (Merritt & Konikow 2000, test 1)")
    print(f"  reference final stage : {scenario.reference_stage_m:.4f} m")
    print(f"  HMP final stage       : {scenario.hmp_stage_m:.4f} m")
    print("Structural (home-grown DISV CONNECTIONDATA vs upstream):")
    structural_lines = [
        _structural_verdict(
            scenario.structural.n_connections,
            int(structural_tol["n_connections"]),
            name="n_connections",
        ),
        _structural_verdict(
            scenario.structural.n_vertical,
            int(structural_tol["n_vertical"]),
            name="n_vertical",
        ),
        _structural_verdict(
            scenario.structural.n_horizontal,
            int(structural_tol["n_horizontal"]),
            name="n_horizontal",
        ),
    ]
    print("Numerical:")
    numerical_lines = [
        _verdict(
            scenario.final_stage_abs_error_m,
            float(stage_tol["final_stage_abs_error_m"]),
            name="final_stage_abs_error_m",
        ),
        _verdict(
            scenario.rmse_stage_m,
            float(stage_tol["rmse_stage_m"]),
            name="rmse_stage_m",
        ),
        _verdict(
            scenario.lake_gwf_exchange_rel_err,
            float(exchange_tol["lake_gwf_exchange_rel_err"]),
            name="lake_gwf_exchange_rel_err",
        ),
        _verdict(
            scenario.max_budget_percent_discrepancy,
            float(budget_tol["budget_percent_discrepancy"]),
            name="budget_percent_discrepancy",
        ),
    ]
    for line in structural_lines:
        print(line)
    for line in numerical_lines:
        print(line)
    return all("[FAIL]" not in line for line in structural_lines + numerical_lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run the LAK ex-gwf-lak-p01 validation case and print metrics."
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Directory for the two MF6 runs (defaults to a temporary directory).",
    )
    args = parser.parse_args(argv)

    workspace = args.workspace
    if workspace is None:
        workspace = Path(tempfile.mkdtemp(prefix="lak_p01_"))
    workspace.mkdir(parents=True, exist_ok=True)

    scenario = run_lake_p01_scenario(workspace=workspace)
    passed = print_report(scenario, load_tolerances())
    print(f"Workspace: {workspace}")
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
