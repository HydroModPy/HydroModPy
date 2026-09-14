from __future__ import annotations

import math
from pathlib import Path

import pytest

from hydromodpy.analysis.comparison.numerical_closure import (
    CLOSURE_STATION_ID,
    CLOSURE_VARIABLE,
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


def test_write_numerical_closure_exports_persists_catalog_metrics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _FakeMetricStore()

    monkeypatch.setattr(
        "hydromodpy.analysis.comparison.numerical_closure.open_result_store_for_write",
        lambda *args, **kwargs: (store, "catalog-sim"),
    )

    artifacts, detail_rows, summary_rows = write_numerical_closure_exports(
        comparison_root=tmp_path,
        simulation_summaries=[
            {
                "id": "bouss",
                "solver": "boussinesq",
                "config_path": str(tmp_path / "bouss.toml"),
                "sim_id": "catalog-sim",
            }
        ],
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
    assert store.closed
    metric_names = {item["metric_name"] for item in store.metrics}
    assert {
        "closure_n_periods",
        "closure_max_abs_m3_s",
        "closure_mean_abs_m3_s",
        "closure_rmse_m3_s",
        "closure_relative_error_p95",
        "closure_status_code",
    }.issubset(metric_names)
    assert {item["station_id"] for item in store.metrics} == {"__global__"}
    assert {item["variable"] for item in store.metrics} == {"water_budget"}


def test_open_result_store_for_write_returns_a_writable_catalog(tmp_path: Path) -> None:
    """Producing closure metrics is writing: discovery must not hand back a reader."""
    from hydromodpy.analysis.comparison.runtime.metadata import open_result_store_for_write
    from hydromodpy.results.catalog import Catalog

    sim_id = "11111111-2222-3333-4444-555555555555"
    project_root = tmp_path / "child_project"
    with Catalog(project_root) as catalog:
        catalog.register_simulation(sim_id, "child_project", "modflow6", name="child_run")
        catalog.finalize(sim_id, status="completed")

    config_path = tmp_path / "child.toml"
    config_path.write_text(
        f'[workspace]\nproject_root = "{project_root.as_posix()}"\n',
        encoding="utf-8",
    )

    store, resolved = open_result_store_for_write(config_path, preferred_name="child_run")
    assert store is not None
    assert resolved == str(sim_id)
    try:
        store.write_metric(
            resolved,
            CLOSURE_STATION_ID,
            "closure_n_periods",
            2.0,
            variable=CLOSURE_VARIABLE,
            n_samples=2,
        )
    finally:
        store.close()

    with Catalog(project_root, read_only=True) as reader:
        rows = reader.backend.query(
            "SELECT metric_name, value FROM metrics WHERE variable = ?",
            [CLOSURE_VARIABLE],
        )
    assert rows["metric_name"].tolist() == ["closure_n_periods"]


def test_open_result_store_for_write_never_creates_an_index(tmp_path: Path) -> None:
    """A child that persisted nothing must not gain a phantom index."""
    from hydromodpy.analysis.comparison.runtime.metadata import open_result_store_for_write
    from hydromodpy.core.state.paths import catalog_path_for

    project_root = tmp_path / "never_ran"
    config_path = tmp_path / "child.toml"
    config_path.write_text(
        f'[workspace]\nproject_root = "{project_root.as_posix()}"\n',
        encoding="utf-8",
    )

    assert open_result_store_for_write(config_path) == (None, None)
    assert not catalog_path_for(project_root).exists()


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


class _FakeMetricStore:
    def __init__(self) -> None:
        self.metrics: list[dict[str, object]] = []
        self.closed = False

    def write_metric(
        self,
        sim_id: str,
        station_id: str,
        metric_name: str,
        value: float,
        *,
        variable: str,
        n_samples: int | None,
    ) -> None:
        self.metrics.append(
            {
                "sim_id": sim_id,
                "station_id": station_id,
                "metric_name": metric_name,
                "value": value,
                "variable": variable,
                "n_samples": n_samples,
            }
        )

    def close(self) -> None:
        self.closed = True
