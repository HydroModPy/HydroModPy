"""Unit tests for the mesh-catchment launcher batch mode."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.core.workspace.path_registry import PREPROCESSING_DIR
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.workflow.pipelines.mesh import MeshCatchmentLauncher

from ._mesh_catchment_builders import (
    _batch_cfg,
    _DummyBatchWorkspace,
    _minimal_geology_config,
    _patch_dummy_geographic_builders,
    _write_test_raster,
)


def test_mesh_catchment_launcher_batch_runs_selected_outlet_and_writes_manifest(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config_batch.toml"
    outlets_csv = tmp_path / "outlets.csv"
    outlets_csv.write_text(
        "outlet_id,x_outlet_m,y_outlet_m\n1,10.0,20.0\n2,30.0,40.0\n",
        encoding="utf-8",
    )
    runtime_cfg = _batch_cfg(tmp_path)
    captured_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        "hydromodpy.workflow.pipelines.mesh.load_standard_section",
        lambda _, model_cls, __, **__kw: (
            runtime_cfg.workspace
            if model_cls.__name__ == "WorkspaceConfig"
            else runtime_cfg.geographic
        ),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.pipelines.mesh.load_toml_with_base_config",
        lambda _: {
            "mesh_catchment": {
                "constraints_mode": "geology_only",
                "geology": _minimal_geology_config(
                    reference_raster_path=str(runtime_cfg.geographic.dem_init_path)
                ),
            },
            "mesh_catchment_batch": {
                "enabled": True,
                "outlets_table_path": str(outlets_csv),
                "selection_mode": "selected",
                "selected_outlet_ids": [2],
                "catch_name_pattern": "{catch_name}_outlet_{outlet_id}",
                "continue_on_error": True,
                "outputs": {
                    "mesh_filename": "mesh_{outlet_id}.msh",
                    "summary_filename": "summary_{outlet_id}.json",
                    "figure_filename": "figure_{outlet_id}.png",
                    "manifest_csv": "manifests/mesh_batch.csv",
                },
            },
        },
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.Workspace",
        _DummyBatchWorkspace,
    )
    _patch_dummy_geographic_builders(monkeypatch, river_mesh_trace=None)

    def _fake_run_case(config_toml, **kwargs):
        captured_calls.append({"config_toml": config_toml, "kwargs": kwargs})
        kwargs["output_mesh"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["output_mesh"].write_text("mesh", encoding="utf-8")
        return {
            "summary_schema_version": "zone_conformal_sidecar_v1",
            "output_mesh": str(kwargs["output_mesh"]),
            "output_summary_json": str(kwargs["output_summary_json"]),
            "output_figure": str(kwargs["output_figure"]),
            "output_figure_regional": str(kwargs["output_figure_regional"]),
        }

    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.run_zone_conformal_meshing_from_toml",
        _fake_run_case,
    )

    summary = MeshCatchmentLauncher(config_path).run()

    assert summary["mode"] == "batch"
    assert summary["summary_schema_version"] == "mesh_catchment_batch_v1"
    assert summary["outlets_total"] == 1
    assert summary["outlets_succeeded"] == 1
    assert summary["outlets_failed"] == 0
    assert len(captured_calls) == 1
    kwargs = captured_calls[0]["kwargs"]
    assert kwargs["section"] == "mesh_catchment"
    assert kwargs["river_trace"] is None
    assert str(kwargs["output_mesh"]).endswith(
        str(Path("mesh_batch_outlet_2") / PREPROCESSING_DIR / "mesh" / "mesh_2.msh")
    )
    assert str(kwargs["output_summary_json"]).endswith(
        str(Path("mesh_batch_outlet_2") / PREPROCESSING_DIR / "mesh" / "summary_2.json")
    )
    assert str(kwargs["output_figure"]).endswith(
        str(Path("mesh_batch_outlet_2") / PREPROCESSING_DIR / "mesh" / "figure_2.png")
    )
    assert str(kwargs["output_figure_regional"]).endswith(
        str(Path("mesh_batch_outlet_2") / PREPROCESSING_DIR / "mesh" / "figure_2_regional.png")
    )

    manifest_path = Path(summary["manifest_csv"])
    assert manifest_path.exists()
    manifest_text = manifest_path.read_text(encoding="utf-8")
    assert "outlet_id,catch_name,status" in manifest_text
    assert "output_figure_regional" in manifest_text
    assert "2,mesh_batch_outlet_2,ok" in manifest_text


def test_mesh_catchment_launcher_batch_flat_layout_writes_directly_to_catchment_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config_batch.toml"
    outlets_csv = tmp_path / "outlets.csv"
    outlets_csv.write_text(
        "outlet_id,x_outlet_m,y_outlet_m\n2,30.0,40.0\n",
        encoding="utf-8",
    )
    runtime_cfg = _batch_cfg(tmp_path)
    captured_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        "hydromodpy.workflow.pipelines.mesh.load_standard_section",
        lambda _, model_cls, __, **__kw: (
            runtime_cfg.workspace
            if model_cls.__name__ == "WorkspaceConfig"
            else runtime_cfg.geographic
        ),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.pipelines.mesh.load_toml_with_base_config",
        lambda _: {
            "mesh_catchment": {
                "constraints_mode": "geology_only",
                "output_layout": "flat",
                "geology": _minimal_geology_config(
                    reference_raster_path=str(runtime_cfg.geographic.dem_init_path)
                ),
            },
            "mesh_catchment_batch": {
                "enabled": True,
                "outlets_table_path": str(outlets_csv),
                "selection_mode": "all",
                "outputs": {
                    "mesh_filename": "mesh_{outlet_id}.msh",
                    "summary_filename": "summary_{outlet_id}.json",
                    "figure_filename": "figure_{outlet_id}.png",
                },
            },
        },
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.Workspace",
        _DummyBatchWorkspace,
    )
    _patch_dummy_geographic_builders(monkeypatch, river_mesh_trace=None)

    def _fake_run_case(config_toml, **kwargs):
        captured_calls.append({"config_toml": config_toml, "kwargs": kwargs})
        kwargs["output_mesh"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["output_mesh"].write_text("mesh", encoding="utf-8")
        return {
            "summary_schema_version": "zone_conformal_sidecar_v1",
            "output_mesh": str(kwargs["output_mesh"]),
            "output_summary_json": str(kwargs["output_summary_json"]),
            "output_figure": str(kwargs["output_figure"]),
            "output_figure_regional": str(kwargs["output_figure_regional"]),
        }

    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.run_zone_conformal_meshing_from_toml",
        _fake_run_case,
    )

    summary = MeshCatchmentLauncher(config_path).run()

    assert summary["outlets_succeeded"] == 1
    kwargs = captured_calls[0]["kwargs"]
    assert str(kwargs["output_mesh"]).endswith(str(Path("mesh_batch_outlet_2") / "mesh_2.msh"))
    assert str(kwargs["output_summary_json"]).endswith(
        str(Path("mesh_batch_outlet_2") / "summary_2.json")
    )
    assert str(kwargs["output_figure"]).endswith(str(Path("mesh_batch_outlet_2") / "figure_2.png"))
    assert str(kwargs["output_figure_regional"]).endswith(
        str(Path("mesh_batch_outlet_2") / "figure_2_regional.png")
    )


def test_mesh_catchment_launcher_batch_can_disable_figures(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config_batch.toml"
    outlets_csv = tmp_path / "outlets.csv"
    outlets_csv.write_text(
        "outlet_id,x_outlet_m,y_outlet_m\n2,30.0,40.0\n",
        encoding="utf-8",
    )
    runtime_cfg = _batch_cfg(tmp_path)
    captured_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        "hydromodpy.workflow.pipelines.mesh.load_standard_section",
        lambda _, model_cls, __, **__kw: (
            runtime_cfg.workspace
            if model_cls.__name__ == "WorkspaceConfig"
            else runtime_cfg.geographic
        ),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.pipelines.mesh.load_toml_with_base_config",
        lambda _: {
            "mesh_catchment": {
                "constraints_mode": "geology_only",
                "figures_enabled": False,
                "show_plot": True,
                "geology": _minimal_geology_config(
                    reference_raster_path=str(runtime_cfg.geographic.dem_init_path)
                ),
            },
            "mesh_catchment_batch": {
                "enabled": True,
                "outlets_table_path": str(outlets_csv),
                "selection_mode": "all",
                "outputs": {
                    "mesh_filename": "mesh_{outlet_id}.msh",
                    "summary_filename": "summary_{outlet_id}.json",
                    "figure_filename": "figure_{outlet_id}.png",
                    "figure_regional_filename": "figure_{outlet_id}_regional.png",
                },
            },
        },
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.Workspace",
        _DummyBatchWorkspace,
    )
    _patch_dummy_geographic_builders(monkeypatch, river_mesh_trace=None)

    def _fake_run_case(config_toml, **kwargs):
        captured_calls.append({"config_toml": config_toml, "kwargs": kwargs})
        kwargs["output_mesh"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["output_mesh"].write_text("mesh", encoding="utf-8")
        return {
            "summary_schema_version": "zone_conformal_sidecar_v1",
            "output_mesh": str(kwargs["output_mesh"]),
            "output_summary_json": str(kwargs["output_summary_json"]),
            "output_figure": None,
            "output_figure_regional": None,
        }

    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.run_zone_conformal_meshing_from_toml",
        _fake_run_case,
    )

    summary = MeshCatchmentLauncher(config_path).run()

    kwargs = captured_calls[0]["kwargs"]
    assert kwargs["output_figure"] is None
    assert kwargs["output_figure_regional"] is None
    assert kwargs["show_plot"] is False
    result_row = summary["results"][0]
    assert result_row["output_figure"] == ""
    assert result_row["output_figure_regional"] == ""


def test_mesh_catchment_launcher_batch_rejects_fixed_single_output_without_batch_pattern(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config_batch_invalid.toml"
    outlets_csv = tmp_path / "outlets.csv"
    outlets_csv.write_text(
        "outlet_id,x_outlet_m,y_outlet_m\n1,10.0,20.0\n",
        encoding="utf-8",
    )
    runtime_cfg = _batch_cfg(tmp_path)

    monkeypatch.setattr(
        "hydromodpy.workflow.pipelines.mesh.load_standard_section",
        lambda _, model_cls, __, **__kw: (
            runtime_cfg.workspace
            if model_cls.__name__ == "WorkspaceConfig"
            else runtime_cfg.geographic
        ),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.pipelines.mesh.load_toml_with_base_config",
        lambda _: {
            "mesh_catchment": {
                "constraints_mode": "geology_only",
                "geology": _minimal_geology_config(
                    reference_raster_path=str(runtime_cfg.geographic.dem_init_path)
                ),
                "output_figure": "outputs/fixed.png",
            },
            "mesh_catchment_batch": {
                "enabled": True,
                "outlets_table_path": str(outlets_csv),
            },
        },
    )

    with pytest.raises(ValueError, match="mesh_catchment_batch.outputs.figure_filename"):
        _ = MeshCatchmentLauncher(config_path)


def test_mesh_catchment_launcher_batch_rejects_outlets_outside_dem_extent(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config_batch_invalid_extent.toml"
    outlets_csv = tmp_path / "outlets.csv"
    dem_path = tmp_path / "regional_dem.tif"
    outlets_csv.write_text(
        "outlet_id,x_outlet_m,y_outlet_m\nOUT1,5000.0,5000.0\n",
        encoding="utf-8",
    )
    _write_test_raster(
        dem_path,
        xmin=0.0,
        ymin=0.0,
        xmax=1000.0,
        ymax=1000.0,
    )
    runtime_cfg = SimpleNamespace(
        workspace=WorkspaceConfig(
            project_root=tmp_path / "out" / "mesh_batch",
            root=tmp_path,
        ),
        geographic=GeographicConfig(
            catchment={
                "catch_def": "from_outlet_coord",
                "dem_init_path": dem_path,
                "x_outlet": 100.0,
                "y_outlet": 100.0,
                "snap_dist": "50 m",
                "buff_area": "20%",
            },
            crs_project="EPSG:2154",
        ),
    )

    monkeypatch.setattr(
        "hydromodpy.workflow.pipelines.mesh.load_standard_section",
        lambda _, model_cls, __, **__kw: (
            runtime_cfg.workspace
            if model_cls.__name__ == "WorkspaceConfig"
            else runtime_cfg.geographic
        ),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.pipelines.mesh.load_toml_with_base_config",
        lambda _: {
            "mesh_catchment": {
                "constraints_mode": "geology_only",
                "geology": _minimal_geology_config(
                    reference_raster_path=str(runtime_cfg.geographic.dem_init_path)
                ),
            },
            "mesh_catchment_batch": {
                "enabled": True,
                "outlets_table_path": str(outlets_csv),
            },
        },
    )

    with pytest.raises(ValueError, match="geographic.dem_init_path does not cover"):
        _ = MeshCatchmentLauncher(config_path)
