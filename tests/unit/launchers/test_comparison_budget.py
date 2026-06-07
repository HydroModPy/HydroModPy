from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.analysis.comparison.exports import (
    _load_catalog_budget_rows,
    write_boussinesq_obstacle_diagnostics_export,
    write_budget_exports,
)

from ._comparison_builders import (
    OUTLET_CELL_AREA_M2,
    _patch_result_store,
    _write_boussinesq_run_folder,
)


def test_write_budget_exports_derives_boussinesq_budget_timeseries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_folder = tmp_path / "run_bouss_budget"
    bundle_dir = tmp_path / "bundle_bouss_budget"
    store = _write_boussinesq_run_folder(run_folder, bundle_dir)

    comparison_root = tmp_path / "comparison"
    config_path = tmp_path / "run_bouss_budget.toml"
    config_path.write_text('[workspace]\nproject_root = "."\n', encoding="utf-8")
    _patch_result_store(monkeypatch, {config_path.resolve(): store})
    artifacts, rows = write_budget_exports(
        comparison_root=comparison_root,
        simulation_summaries=[
            {
                "id": "bouss_demo",
                "label": "Bouss demo",
                "solver": "boussinesq",
                "mesh_mode": "mesh_input",
                "status": "completed",
                "run_folder": str(run_folder),
                "config_path": str(config_path),
            }
        ],
    )

    assert artifacts
    assert any(row["component"] == "surface_excess_total_m3_s" for row in rows)
    assert any(row["component"] == "comparable_outflow_total_m3_s" for row in rows)
    assert any(row["component"] == "dry_deficit_total_m3_s" for row in rows)
    assert any(row["component"] == "storage_change_total_m3_s" for row in rows)
    recharge_row = next(
        row
        for row in rows
        if row["component"] == "recharge_total_m3_s" and int(row["period_index"]) == 0
    )
    storage_row = next(
        row
        for row in rows
        if row["component"] == "storage_change_total_m3_s" and int(row["period_index"]) == 0
    )
    residual_row = next(
        row
        for row in rows
        if row["component"] == "closure_residual_m3_s" and int(row["period_index"]) == 0
    )
    dry_row = next(
        row
        for row in rows
        if row["component"] == "dry_deficit_total_m3_s" and int(row["period_index"]) == 0
    )
    comparable_row = next(
        row
        for row in rows
        if row["component"] == "comparable_outflow_total_m3_s" and int(row["period_index"]) == 0
    )
    assert int(recharge_row["time_index"]) == 1
    assert recharge_row["time_role"] == "period_value"
    assert recharge_row["period_start_seconds"] == pytest.approx(0.0)
    assert recharge_row["period_end_seconds"] == pytest.approx(3600.0)
    assert not recharge_row["is_initial_state"]
    assert float(recharge_row["value"]) == pytest.approx(3.75e-7)
    assert float(storage_row["value"]) == pytest.approx(0.68 / 3600.0)
    assert float(dry_row["value"]) == pytest.approx(0.005 * OUTLET_CELL_AREA_M2)
    assert float(comparable_row["value"]) == pytest.approx(0.35 + 0.48)
    assert math.isfinite(float(residual_row["value"]))
    assert float(residual_row["value"]) == pytest.approx(
        3.75e-7 - 0.025 + 0.005 * OUTLET_CELL_AREA_M2 - 0.48 - 0.35 - (0.68 / 3600.0)
    )


def test_write_budget_exports_prefers_boussinesq_solver_residual_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_folder = tmp_path / "run_bouss_budget"
    bundle_dir = tmp_path / "bundle_bouss_budget"
    store = _write_boussinesq_run_folder(
        run_folder,
        bundle_dir,
        residual_history_m3_s=np.asarray([[0.0, 0.0, 0.0], [0.2, -0.03, 0.01]]),
    )

    comparison_root = tmp_path / "comparison"
    config_path = tmp_path / "run_bouss_budget.toml"
    config_path.write_text('[workspace]\nproject_root = "."\n', encoding="utf-8")
    _patch_result_store(monkeypatch, {config_path.resolve(): store})
    _, rows = write_budget_exports(
        comparison_root=comparison_root,
        simulation_summaries=[
            {
                "id": "bouss_demo",
                "label": "Bouss demo",
                "solver": "boussinesq",
                "mesh_mode": "mesh_input",
                "status": "completed",
                "run_folder": str(run_folder),
                "config_path": str(config_path),
            }
        ],
    )

    residual_row = next(
        row
        for row in rows
        if row["component"] == "closure_residual_m3_s" and int(row["period_index"]) == 0
    )
    assert float(residual_row["value"]) == pytest.approx(0.18)


def test_write_budget_exports_uses_child_config_bundle_when_run_folder_has_no_mesh_metadata(
    tmp_path: Path,
) -> None:
    run_folder = tmp_path / "generated_configs"
    bundle_dir = tmp_path / "bundle_from_child_config"
    run_folder.mkdir(parents=True, exist_ok=True)
    _write_boussinesq_run_folder(run_folder, bundle_dir)
    (run_folder / "_boussinesq_summary.json").unlink()

    config_dir = tmp_path / "comparison" / "_generated_configs"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "bouss_candidate.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "simulation"',
                "",
                "[mesh_input]",
                'bundle_dir = "../../bundle_from_child_config"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    artifacts, rows = write_budget_exports(
        comparison_root=tmp_path / "comparison",
        simulation_summaries=[
            {
                "id": "bouss_demo",
                "label": "Bouss demo",
                "solver": "boussinesq",
                "mesh_mode": "mesh_input",
                "status": "completed",
                "run_folder": str(run_folder),
                "config_path": str(config_path),
            }
        ],
    )

    assert artifacts
    assert any(row["component"] == "recharge_total_m3_s" for row in rows)


def test_write_boussinesq_obstacle_diagnostics_exports_bounds_and_dry_deficit(
    tmp_path: Path,
) -> None:
    run_folder = tmp_path / "run_bouss_obstacles"
    bundle_dir = tmp_path / "bundle_bouss_obstacles"
    run_folder.mkdir(parents=True, exist_ok=True)
    _write_boussinesq_run_folder(run_folder, bundle_dir)

    artifacts, rows = write_boussinesq_obstacle_diagnostics_export(
        comparison_root=tmp_path / "comparison",
        simulation_summaries=[
            {
                "id": "bouss_demo",
                "label": "Bouss demo",
                "solver": "boussinesq",
                "mesh_mode": "mesh_input",
                "status": "completed",
                "run_folder": str(run_folder),
            }
        ],
    )

    assert artifacts
    assert rows
    last = next(row for row in rows if int(row["time_index"]) == 1)
    assert float(last["min_head_above_bottom_m"]) == pytest.approx(-0.3)
    assert float(last["max_head_below_bottom_m"]) == pytest.approx(0.3)
    assert int(last["head_below_bottom_cell_count"]) == 1
    assert float(last["negative_storage_volume_m3"]) == pytest.approx(0.24)
    assert int(last["dry_deficit_active_cell_count"]) == 1
    assert float(last["dry_deficit_total_m3_s"]) == pytest.approx(0.005 * OUTLET_CELL_AREA_M2)


def test_catalog_budget_rows_are_normalized_to_elapsed_seconds_and_m3_s(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "mf6_child.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "simulation"',
                "",
                "[simulation]",
                'name = "mf6_budget_demo"',
                "",
                "[simulation.time]",
                'start_datetime = "2020-01-01 00:00:00"',
                'end_datetime = "2020-01-02 00:00:00"',
                'step_value = "1 day"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    class FakeBudgetStore:
        def query_budget(self, sim_id: str) -> pd.DataFrame:
            assert sim_id == "mf6-demo"
            return pd.DataFrame(
                [
                    {
                        "timestep": 0,
                        "component": "rcha",
                        "flux_in": 2.5,
                        "flux_out": 0.0,
                        "unit": "m3/d",
                    },
                    {
                        "timestep": 0,
                        "component": "chd",
                        "flux_in": 0.1,
                        "flux_out": 0.4,
                        "unit": "m3/d",
                    },
                    {
                        "timestep": 0,
                        "component": "sto-sy",
                        "flux_in": 0.2,
                        "flux_out": 1.0,
                        "unit": "m3/d",
                    },
                    {
                        "timestep": 1,
                        "component": "rcha",
                        "flux_in": 0.0,
                        "flux_out": 0.0,
                        "unit": "m3/s",
                    },
                ]
            )

    rows = _load_catalog_budget_rows(
        {
            "id": "mf6_ref",
            "label": "MF6 reference",
            "solver": "modflow6",
            "mesh_mode": "mesh_input",
            "config_path": str(config_path),
        },
        FakeBudgetStore(),
        "mf6-demo",
    )

    by_component = {row["component"]: row for row in rows if int(row["time_index"]) == 0}
    assert by_component["recharge_total_m3_s"]["elapsed_seconds"] == pytest.approx(86400.0)
    assert by_component["recharge_total_m3_s"]["time_role"] == "period_value"
    assert by_component["recharge_total_m3_s"]["period_index"] == 0
    assert by_component["recharge_total_m3_s"]["period_start_seconds"] == pytest.approx(0.0)
    assert by_component["recharge_total_m3_s"]["period_end_seconds"] == pytest.approx(86400.0)
    assert not by_component["recharge_total_m3_s"]["is_initial_state"]
    assert by_component["recharge_total_m3_s"]["unit"] == "m3/s"
    assert by_component["recharge_total_m3_s"]["value"] == pytest.approx(2.5)
    assert by_component["prescribed_head_out_total_m3_s"]["value"] == pytest.approx(0.3)
    assert by_component["storage_change_total_m3_s"]["value"] == pytest.approx(0.8)
    assert by_component["closure_residual_m3_s"]["value"] == pytest.approx(1.4)
