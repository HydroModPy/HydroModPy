"""Execution-time export tests for comparison reports."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from hydromodpy.analysis.comparison.exports import write_execution_summary_csv


def test_execution_summary_uses_flow_solve_time_only(tmp_path: Path) -> None:
    artifacts, rows = write_execution_summary_csv(
        comparison_root=tmp_path,
        reference_simulation="mf6_ref",
        simulation_summaries=[
            {
                "id": "mf6_ref",
                "status": "completed",
                "solver": "modflow6",
                "wall_time_seconds": 100.0,
                "metrics": {"flow_solve_time_seconds": 10.0},
            },
            {
                "id": "bouss_candidate",
                "status": "completed",
                "solver": "boussinesq",
                "wall_time_seconds": 200.0,
                "flow_solve_time_seconds": 5.0,
            },
        ],
    )

    assert [item["kind"] for item in artifacts] == ["execution_times_csv"]
    assert [row["runtime_seconds"] for row in rows] == [10.0, 5.0]
    assert rows[1]["speedup_vs_reference"] == pytest.approx(2.0)
    assert {row["time_scope"] for row in rows} == {"flow_solve"}

    with (tmp_path / "execution_times.csv").open("r", encoding="utf-8", newline="") as handle:
        exported = list(csv.DictReader(handle))
    assert [row["runtime_seconds"] for row in exported] == ["10.0", "5.0"]


def test_execution_summary_does_not_fallback_to_workflow_wall_time(tmp_path: Path) -> None:
    artifacts, rows = write_execution_summary_csv(
        comparison_root=tmp_path,
        reference_simulation="mf6_ref",
        simulation_summaries=[
            {
                "id": "mf6_ref",
                "status": "completed",
                "solver": "modflow6",
                "wall_time_seconds": 100.0,
            },
            {
                "id": "bouss_candidate",
                "status": "completed",
                "solver": "boussinesq",
                "wall_time_seconds": 200.0,
            },
        ],
    )

    assert artifacts == []
    assert rows == []
    assert not (tmp_path / "execution_times.csv").exists()
