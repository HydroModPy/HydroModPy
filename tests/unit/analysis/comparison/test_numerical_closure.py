from __future__ import annotations

import math
from pathlib import Path

import pytest

from hydromodpy.analysis.comparison.numerical_closure import (
    build_numerical_closure_tables,
    write_numerical_closure_exports,
)


def test_build_numerical_closure_tables_summarizes_budget_residuals() -> None:
    detail_rows, summary_rows = build_numerical_closure_tables(
        simulation_summaries=[
            {
                "id": "mf6_ref",
                "label": "MF6 reference",
                "solver": "modflow6",
            }
        ],
        budget_rows=[
            _budget_row("mf6_ref", "recharge_total_m3_s", 10.0, 0, 10.0),
            _budget_row("mf6_ref", "drainage_total_m3_s", 6.0, 0, 10.0),
            _budget_row("mf6_ref", "storage_change_total_m3_s", 4.0, 0, 10.0),
            _budget_row("mf6_ref", "recharge_total_m3_s", 10.0, 1, 20.0),
            _budget_row("mf6_ref", "drainage_total_m3_s", 5.0, 1, 20.0),
            _budget_row("mf6_ref", "storage_change_total_m3_s", 4.99, 1, 20.0),
        ],
    )

    assert [row["period_index"] for row in detail_rows] == [0, 1]
    assert [row["closure_residual_m3_s"] for row in detail_rows] == pytest.approx([0.0, 0.01])
    assert len(summary_rows) == 1
    summary = summary_rows[0]
    assert summary["simulation_id"] == "mf6_ref"
    assert summary["simulation_label"] == "MF6 reference"
    assert summary["solver"] == "modflow6"
    assert summary["n_periods"] == 2
    assert math.isnan(summary["area_m2"])
    assert summary["max_abs_closure_m3_s"] == pytest.approx(0.01)
    assert summary["mean_abs_closure_m3_s"] == pytest.approx(0.005)
    assert summary["rmse_closure_m3_s"] == pytest.approx(math.sqrt(0.0001 / 2.0))
    assert math.isnan(summary["max_abs_closure_mm_d"])
    assert summary["relative_closure_error_p95"] == pytest.approx(
        0.95 * (0.01 / (10.0 + 5.0 + 4.99))
    )
    assert summary["diagnostic"] == "OK"


def test_build_numerical_closure_tables_prefers_direct_closure_residual() -> None:
    detail_rows, summary_rows = build_numerical_closure_tables(
        simulation_summaries=[{"id": "bouss", "solver": "boussinesq"}],
        budget_rows=[
            _budget_row("bouss", "recharge_total_m3_s", 2.0, 0, 1.0),
            _budget_row("bouss", "drainage_total_m3_s", 1.0, 0, 1.0),
            _budget_row("bouss", "storage_change_total_m3_s", 1.0, 0, 1.0),
            _budget_row("bouss", "closure_residual_m3_s", 0.2, 0, 1.0),
        ],
    )

    assert detail_rows[0]["closure_residual_m3_s"] == pytest.approx(0.2)
    assert detail_rows[0]["source"] == "closure_residual_m3_s"
    assert summary_rows[0]["diagnostic"] == "CHECK"


def test_write_numerical_closure_exports_writes_the_comparison_folder_only(
    tmp_path: Path,
) -> None:
    """The closure is written beside the comparison; the compared run is never touched."""
    comparison_root = tmp_path / "comparison"
    run_dir = tmp_path / "runs" / "bouss"
    run_dir.mkdir(parents=True)

    artifacts, detail_rows, summary_rows = write_numerical_closure_exports(
        comparison_root=comparison_root,
        simulation_summaries=[{"id": "bouss", "solver": "boussinesq", "run_dir": str(run_dir)}],
        budget_rows=[
            _budget_row("bouss", "recharge_total_m3_s", 2.0, 0, 1.0),
            _budget_row("bouss", "drainage_total_m3_s", 1.0, 0, 1.0),
            _budget_row("bouss", "storage_change_total_m3_s", 0.999, 0, 1.0),
        ],
    )

    assert detail_rows
    assert summary_rows
    assert {item["kind"] for item in artifacts} == {
        "numerical_closure_by_period_csv",
        "numerical_closure_summary_csv",
        "numerical_closure_summary_json",
    }
    assert all(Path(item["path"]).parent == comparison_root for item in artifacts)
    assert list(run_dir.iterdir()) == []


def _budget_row(
    simulation_id: str,
    component: str,
    value: float,
    period_index: int,
    elapsed_seconds: float,
) -> dict[str, object]:
    return {
        "simulation_id": simulation_id,
        "simulation_label": simulation_id,
        "solver": "",
        "component": component,
        "period_index": period_index,
        "time_index": period_index,
        "elapsed_seconds": elapsed_seconds,
        "value": value,
    }
