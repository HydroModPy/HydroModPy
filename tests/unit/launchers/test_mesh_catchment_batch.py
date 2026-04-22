from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.spatial.mesh.batch_io import load_mesh_catchment_outlet_records
from hydromodpy.spatial.mesh.batch_reporting import (
    write_mesh_catchment_batch_manifest,
)
from hydromodpy.spatial.mesh.batch import (
    MeshCatchmentBatchConfig,
    MeshCatchmentBatchResultRow,
    MeshCatchmentBatchRunner,
    MeshCatchmentBatchSummary,
)
from hydromodpy.spatial.mesh.config import MeshCatchmentConfig


def test_mesh_catchment_batch_config_from_mapping_returns_typed_values(
    tmp_path: Path,
) -> None:
    batch_cfg = MeshCatchmentBatchConfig.from_mapping(
        {
            "enabled": True,
            "outlets_table_path": "outlets.csv",
            "selection_mode": "selected",
            "selected_outlet_ids": [2, "A3"],
            "outputs": {
                "mesh_filename": "mesh_{outlet_id}.msh",
                "summary_filename": "summary_{outlet_id}.json",
            },
        },
        base_dir=tmp_path,
    )

    assert batch_cfg is not None
    assert batch_cfg.outlets_table_path == (tmp_path / "outlets.csv").resolve()
    assert batch_cfg.selection_mode == "selected"
    assert batch_cfg.selected_outlet_ids == ("2", "A3")
    assert batch_cfg.outputs.mesh_filename == "mesh_{outlet_id}.msh"
    assert batch_cfg.outputs.summary_filename == "summary_{outlet_id}.json"


def test_batch_runner_validate_output_configuration_requires_per_outlet_pattern(
    tmp_path: Path,
) -> None:
    mesh_section_data = MeshCatchmentConfig.model_validate(
        {
            "constraints_mode": "rivers_only",
            "output_figure": "outputs/fixed.png",
        }
    )
    batch_cfg = MeshCatchmentBatchConfig.from_mapping(
        {
            "enabled": True,
            "outlets_table_path": "outlets.csv",
        },
        base_dir=tmp_path,
    )
    assert batch_cfg is not None

    runner = MeshCatchmentBatchRunner(
        config_path=tmp_path / "config.toml",
        mesh_section_data=mesh_section_data,
        workspace_cfg=SimpleNamespace(project_root=tmp_path / "mesh_batch"),
        geographic_cfg=SimpleNamespace(dem_init_path=tmp_path / "dem.tif"),
        domain_cfg=None,
        run_single_workflow=lambda **kwargs: {},
    )

    with pytest.raises(ValueError, match="mesh_catchment_batch.outputs.figure_filename"):
        runner.validate_output_configuration(batch_cfg)


def test_mesh_catchment_batch_summary_serializes_typed_rows() -> None:
    summary = MeshCatchmentBatchSummary(
        manifest_csv="batch/manifest.csv",
        results=(
            MeshCatchmentBatchResultRow(
                outlet_id="A1",
                catch_name="catch_A1",
                status="ok",
                x_outlet=10.0,
                y_outlet=20.0,
                output_mesh="mesh_A1.msh",
            ),
            MeshCatchmentBatchResultRow(
                outlet_id="A2",
                catch_name="catch_A2",
                status="error",
                x_outlet=30.0,
                y_outlet=40.0,
                error="boom",
            ),
        ),
    ).to_mapping()

    assert summary["manifest_csv"] == "batch/manifest.csv"
    assert summary["outlets_total"] == 2
    assert summary["outlets_succeeded"] == 1
    assert summary["outlets_failed"] == 1
    assert summary["results"][0]["output_mesh"] == "mesh_A1.msh"
    assert summary["results"][1]["error"] == "boom"


def test_load_mesh_catchment_outlet_records_reads_csv(tmp_path: Path) -> None:
    table_path = tmp_path / "outlets.csv"
    table_path.write_text("outlet_id,x,y\nA1,10.5,20.5\nA2,30.0,40.0\n", encoding="utf-8")

    records = load_mesh_catchment_outlet_records(
        table_path=table_path,
        selection_mode="all",
        selected_outlet_ids=(),
        outlet_id_column="outlet_id",
        x_column="x",
        y_column="y",
    )

    assert [record.outlet_id for record in records] == ["A1", "A2"]
    assert records[0].outlet_id_safe == "A1"
    assert records[1].x_outlet == pytest.approx(30.0)


def test_load_mesh_catchment_outlet_records_accepts_geometry_xy_fallback(
    tmp_path: Path,
) -> None:
    table_path = tmp_path / "outlets_geometry_xy.csv"
    table_path.write_text(
        "outlet_id,geometry_x,geometry_y\nA1,10.5,20.5\n",
        encoding="utf-8",
    )

    records = load_mesh_catchment_outlet_records(
        table_path=table_path,
        selection_mode="all",
        selected_outlet_ids=(),
        outlet_id_column="outlet_id",
        x_column="x",
        y_column="y",
    )

    assert len(records) == 1
    assert records[0].x_outlet == pytest.approx(10.5)
    assert records[0].y_outlet == pytest.approx(20.5)


def test_write_mesh_catchment_batch_manifest_persists_csv(tmp_path: Path) -> None:
    manifest_path = tmp_path / "batch" / "manifest.csv"
    rows = [
        MeshCatchmentBatchResultRow(
            outlet_id="A1",
            catch_name="catch_A1",
            status="ok",
            x_outlet=1.0,
            y_outlet=2.0,
            output_mesh="mesh_A1.msh",
        )
    ]

    write_mesh_catchment_batch_manifest(manifest_path, rows)

    content = manifest_path.read_text(encoding="utf-8")
    assert "outlet_id,catch_name,status" in content
    assert "A1,catch_A1,ok,1.0,2.0,mesh_A1.msh" in content


def test_batch_runner_marks_missing_mesh_output_as_error_and_continues(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    outlets_csv = tmp_path / "outlets.csv"
    outlets_csv.write_text(
        "outlet_id,x_outlet_m,y_outlet_m\n1,10.0,20.0\n2,30.0,40.0\n",
        encoding="utf-8",
    )
    batch_cfg = MeshCatchmentBatchConfig.from_mapping(
        {
            "enabled": True,
            "outlets_table_path": str(outlets_csv),
            "continue_on_error": True,
            "outputs": {
                "mesh_filename": "mesh_{outlet_id}.msh",
                "manifest_csv": "batch/manifest.csv",
            },
        },
        base_dir=tmp_path,
    )
    assert batch_cfg is not None

    mesh_section_data = MeshCatchmentConfig.model_validate({"constraints_mode": "rivers_only"})
    workspace_cfg = SimpleNamespace(project_root=tmp_path / "mesh_batch")
    geographic_cfg = SimpleNamespace(dem_init_path=tmp_path / "dem.tif")
    call_count = {"n": 0}

    def _fake_run_single_workflow(**kwargs):
        call_count["n"] += 1
        output_mesh = Path(kwargs["output_overrides"]["output_mesh"])
        if call_count["n"] == 2:
            output_mesh.parent.mkdir(parents=True, exist_ok=True)
            output_mesh.write_text("mesh", encoding="utf-8")
        return {
            "output_mesh": str(output_mesh),
            "output_summary_json": str(output_mesh.with_suffix(".json")),
        }

    runner = MeshCatchmentBatchRunner(
        config_path=tmp_path / "config.toml",
        mesh_section_data=mesh_section_data,
        workspace_cfg=workspace_cfg,
        geographic_cfg=geographic_cfg,
        domain_cfg=None,
        run_single_workflow=_fake_run_single_workflow,
    )

    summary = runner.run(batch_cfg)

    assert call_count["n"] == 2
    assert summary["outlets_total"] == 2
    assert summary["outlets_succeeded"] == 1
    assert summary["outlets_failed"] == 1
    assert summary["results"][0]["status"] == "error"
    assert "did not write the expected mesh file" in summary["results"][0]["error"]
    assert summary["results"][1]["status"] == "ok"
    assert summary["results"][0].get("error", "")


def test_batch_runner_raises_runtime_error_when_missing_mesh_output_and_stop_requested(
    tmp_path: Path,
) -> None:
    outlets_csv = tmp_path / "outlets.csv"
    outlets_csv.write_text(
        "outlet_id,x_outlet_m,y_outlet_m\n1,10.0,20.0\n",
        encoding="utf-8",
    )
    batch_cfg = MeshCatchmentBatchConfig.from_mapping(
        {
            "enabled": True,
            "outlets_table_path": str(outlets_csv),
            "continue_on_error": False,
            "outputs": {
                "mesh_filename": "mesh_{outlet_id}.msh",
                "manifest_csv": "batch/manifest.csv",
            },
        },
        base_dir=tmp_path,
    )
    assert batch_cfg is not None

    runner = MeshCatchmentBatchRunner(
        config_path=tmp_path / "config.toml",
        mesh_section_data=MeshCatchmentConfig.model_validate({"constraints_mode": "rivers_only"}),
        workspace_cfg=SimpleNamespace(project_root=tmp_path / "mesh_batch"),
        geographic_cfg=SimpleNamespace(dem_init_path=tmp_path / "dem.tif"),
        domain_cfg=None,
        run_single_workflow=lambda **kwargs: {
            "output_mesh": str(kwargs["output_overrides"]["output_mesh"]),
        },
    )

    with pytest.raises(RuntimeError, match="did not write the expected mesh file"):
        runner.run(batch_cfg)

    manifest_path = tmp_path / "mesh_batch" / "batch" / "manifest.csv"
    assert manifest_path.exists()
