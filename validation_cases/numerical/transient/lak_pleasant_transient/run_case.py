"""CLI entrypoint for the transient multi-layer LAK regression case.

Runs the HMP meters/seconds multi-layer DISV build and prints the structural and
transient metrics with a PASS / FAIL verdict against ``tolerances.toml``.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from .comparison import (
    PleasantTransientScenario,
    load_tolerances,
    run_pleasant_transient_scenario,
)


def _verdict(value: float, threshold: float, *, name: str) -> str:
    status = "PASS" if value <= threshold else "FAIL"
    return f"  [{status}] {name}: {value:.6g} (tol {threshold:.6g})"


def _floor_verdict(value: float, threshold: float, *, name: str) -> str:
    status = "PASS" if value >= threshold else "FAIL"
    return f"  [{status}] {name}: {value:.6g} (min {threshold:.6g})"


def _structural_verdict(actual: int, expected: int, *, name: str) -> str:
    status = "PASS" if actual == expected else "FAIL"
    return f"  [{status}] {name}: {actual} (expected {expected})"


def print_report(scenario: PleasantTransientScenario, tolerances: dict) -> bool:
    """Print the metric report and return True when every metric passes."""
    stage_tol = dict(tolerances["stage"])
    budget_tol = dict(tolerances["budget"])
    structural_tol = dict(tolerances["structural"])

    print("LAK transient multi-layer regression (Plainfield Lakes abacus)")
    stages = ", ".join(f"{s:.4f}" for s in scenario.period_stages_m)
    print(f"  per-period lake stage (m) : [{stages}]")
    print("Structural (multi-layer DISV CONNECTIONDATA):")
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
        _structural_verdict(
            scenario.structural.horizontal_by_layer.get(0, 0),
            int(structural_tol["horizontal_layer_0"]),
            name="horizontal_layer_0",
        ),
        _structural_verdict(
            scenario.structural.horizontal_by_layer.get(1, 0),
            int(structural_tol["horizontal_layer_1"]),
            name="horizontal_layer_1",
        ),
    ]
    print("Transient:")
    numerical_lines = [
        _floor_verdict(
            scenario.stage_swing_m,
            float(stage_tol["min_stage_swing_m"]),
            name="stage_swing_m",
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
        description="Run the transient multi-layer LAK regression case and print metrics."
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Directory for the MF6 run (defaults to a temporary directory).",
    )
    args = parser.parse_args(argv)

    workspace = args.workspace
    if workspace is None:
        workspace = Path(tempfile.mkdtemp(prefix="lak_pleasant_transient_"))
    workspace.mkdir(parents=True, exist_ok=True)

    scenario = run_pleasant_transient_scenario(workspace=workspace)
    passed = print_report(scenario, load_tolerances())
    print(f"Workspace: {workspace}")
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
