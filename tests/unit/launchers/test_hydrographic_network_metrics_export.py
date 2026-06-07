from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.analysis.comparison.exports import (
    write_hydrographic_network_metrics_export,
)

from ._hydrographic_network_metrics_export_builders import _register_completed_run


def test_write_hydrographic_network_metrics_export_writes_csv(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    config_path, sim_id = _register_completed_run(
        workspace_root,
        reference_length_m=1000.0,
        generated_length_m=800.0,
    )

    artifacts, rows = write_hydrographic_network_metrics_export(
        comparison_id="demo_compare",
        comparison_root=tmp_path / "comparison_outputs",
        simulation_summaries=[
            {
                "id": "mf6_demo",
                "label": "MF6 demo",
                "solver": "modflow6",
                "mesh_mode": "structured",
                "config_path": str(config_path),
                "run_folder": str(tmp_path / "run_folder"),
                "sim_id": sim_id,
                "run_name": "network_demo",
                "status": "completed",
            }
        ],
        tolerance_m=0.0,
    )

    assert len(artifacts) == 1
    assert artifacts[0]["kind"] == "hydrographic_network_metrics_csv"
    assert Path(artifacts[0]["path"]).exists()
    assert len(rows) == 1
    row = rows[0]
    assert row["comparison_id"] == "demo_compare"
    assert row["simulation_id"] == "mf6_demo"
    assert row["reference_total_length_m"] == pytest.approx(1000.0)
    assert row["candidate_total_length_m"] == pytest.approx(800.0)
    assert row["reference_coverage_ratio"] == pytest.approx(0.8)
    assert row["candidate_match_ratio"] == pytest.approx(1.0)


def test_write_hydrographic_network_metrics_export_skips_missing_networks(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    config_path, sim_id = _register_completed_run(
        workspace_root,
        reference_length_m=1000.0,
        generated_length_m=None,
    )

    artifacts, rows = write_hydrographic_network_metrics_export(
        comparison_id="demo_compare",
        comparison_root=tmp_path / "comparison_outputs",
        simulation_summaries=[
            {
                "id": "mf6_demo",
                "label": "MF6 demo",
                "solver": "modflow6",
                "mesh_mode": "structured",
                "config_path": str(config_path),
                "run_folder": str(tmp_path / "run_folder"),
                "sim_id": sim_id,
                "run_name": "network_demo",
                "status": "completed",
            }
        ],
        tolerance_m=0.0,
    )

    assert len(artifacts) == 1
    assert artifacts[0]["kind"] == "hydrographic_network_metrics_skipped_json"
    assert Path(str(artifacts[0]["path"])).exists()
    assert rows == []

    payload = Path(str(artifacts[0]["path"])).read_text(encoding="utf-8")
    assert "missing_required_roles" in payload
    assert "reference" in payload


def test_write_hydrographic_network_metrics_export_reports_partial_skips(
    tmp_path: Path,
) -> None:
    workspace_ok = tmp_path / "workspace_ok"
    config_path_ok, sim_id_ok = _register_completed_run(
        workspace_ok,
        reference_length_m=1000.0,
        generated_length_m=800.0,
    )
    workspace_missing = tmp_path / "workspace_missing"
    config_path_missing, sim_id_missing = _register_completed_run(
        workspace_missing,
        reference_length_m=1000.0,
        generated_length_m=None,
    )

    artifacts, rows = write_hydrographic_network_metrics_export(
        comparison_id="demo_compare",
        comparison_root=tmp_path / "comparison_outputs",
        simulation_summaries=[
            {
                "id": "mf6_ok",
                "label": "MF6 ok",
                "solver": "modflow6",
                "mesh_mode": "structured",
                "config_path": str(config_path_ok),
                "run_folder": str(tmp_path / "run_ok"),
                "sim_id": sim_id_ok,
                "run_name": "network_demo",
                "status": "completed",
            },
            {
                "id": "mf6_missing",
                "label": "MF6 missing",
                "solver": "modflow6",
                "mesh_mode": "structured",
                "config_path": str(config_path_missing),
                "run_folder": str(tmp_path / "run_missing"),
                "sim_id": sim_id_missing,
                "run_name": "network_demo",
                "status": "completed",
            },
        ],
        tolerance_m=0.0,
    )

    artifact_kinds = {item["kind"] for item in artifacts}
    assert "hydrographic_network_metrics_csv" in artifact_kinds
    assert "hydrographic_network_metrics_skipped_json" in artifact_kinds
    assert len(rows) == 1
