"""Unit checks for the boundary-step simulation-comparison runner."""

from __future__ import annotations

from pathlib import Path

from validation_cases.analytical.transient.linearized_unconfined_boundary_step_1d import (
    run_comparison,
)


def test_boundary_step_comparison_runner_uses_canonical_section(tmp_path: Path) -> None:
    payload = run_comparison._build_payload(output_root=tmp_path, run_simulations=True)

    assert payload["workflow"] == "comparison"
    assert "comparison" in payload

    comparison = payload["comparison"]
    assert comparison["output_root"] == str(tmp_path)
    assert comparison["reference_simulation"] == "modflow6"
    assert comparison["execution"]["run_simulations"] is True
    assert [simulation["id"] for simulation in comparison["simulation"]] == [
        "modflownwt",
        "modflow6",
    ]


def test_boundary_step_comparison_runner_can_disable_child_runs(tmp_path: Path) -> None:
    payload = run_comparison._build_payload(output_root=tmp_path, run_simulations=False)

    assert payload["comparison"]["execution"]["run_simulations"] is False
