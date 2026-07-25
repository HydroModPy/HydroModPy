"""Unit tests for the mesh-catchment launcher cleanup and validation paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.workspace.path_registry import PREPROCESSING_DIR
from hydromodpy.workflow.pipelines.mesh import MeshCatchmentLauncher

from ._mesh_catchment_builders import (
    _DummyWorkspace,
    _minimal_cfg,
    _minimal_geology_config,
    _patch_dummy_geographic_builders,
)


def test_mesh_catchment_launcher_cleanup_mode_removes_geographic_outputs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[mesh_catchment]\nconstraints_mode='rivers_only'\n",
        encoding="utf-8",
    )
    minimal_cfg = _minimal_cfg(tmp_path)

    monkeypatch.setattr(
        "hydromodpy.workflow.pipelines.mesh.load_standard_section",
        lambda _, model_cls, __: (
            minimal_cfg.workspace
            if model_cls.__name__ == "WorkspaceConfig"
            else minimal_cfg.geographic
        ),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.pipelines.mesh.load_toml_with_base_config",
        lambda _: {
            "mesh_catchment": {
                "constraints_mode": "rivers_only",
                "geographic_outputs_mode": "cleanup",
            }
        },
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.Workspace",
        _DummyWorkspace,
    )
    _patch_dummy_geographic_builders(monkeypatch)

    _stable = minimal_cfg.workspace.project_root / PREPROCESSING_DIR

    def _fake_run_case(config_toml, **kwargs):
        (_stable / "geographic" / "tmp").mkdir(parents=True, exist_ok=True)
        (_stable / "demcorrecflow" / "tmp").mkdir(parents=True, exist_ok=True)
        kwargs["output_mesh"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["output_mesh"].write_text("mesh", encoding="utf-8")
        return {"summary_schema_version": "zone_conformal_sidecar_v1"}

    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.run_zone_conformal_meshing_from_toml",
        _fake_run_case,
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.export_catchment_mesh_bundle",
        lambda **_: {"bundle_dir": str(tmp_path / "bundle")},
    )

    summary = MeshCatchmentLauncher(config_path).run()

    assert summary["geographic_outputs_mode"] == "cleanup"
    assert summary["geographic_outputs_cleanup_applied"] is True
    assert not (_stable / "geographic").exists()
    assert not (_stable / "demcorrecflow").exists()


def test_mesh_catchment_launcher_keep_mode_preserves_geographic_outputs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[mesh_catchment]\nconstraints_mode='rivers_only'\n",
        encoding="utf-8",
    )
    minimal_cfg = _minimal_cfg(tmp_path)

    monkeypatch.setattr(
        "hydromodpy.workflow.pipelines.mesh.load_standard_section",
        lambda _, model_cls, __: (
            minimal_cfg.workspace
            if model_cls.__name__ == "WorkspaceConfig"
            else minimal_cfg.geographic
        ),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.pipelines.mesh.load_toml_with_base_config",
        lambda _: {"mesh_catchment": {"constraints_mode": "rivers_only"}},
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.Workspace",
        _DummyWorkspace,
    )
    _patch_dummy_geographic_builders(monkeypatch)

    _stable = minimal_cfg.workspace.project_root / PREPROCESSING_DIR

    def _fake_run_case(config_toml, **kwargs):
        (_stable / "geographic" / "tmp").mkdir(parents=True, exist_ok=True)
        (_stable / "demcorrecflow" / "tmp").mkdir(parents=True, exist_ok=True)
        kwargs["output_mesh"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["output_mesh"].write_text("mesh", encoding="utf-8")
        return {"summary_schema_version": "zone_conformal_sidecar_v1"}

    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.run_zone_conformal_meshing_from_toml",
        _fake_run_case,
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.export_catchment_mesh_bundle",
        lambda **_: {"bundle_dir": str(tmp_path / "bundle")},
    )

    summary = MeshCatchmentLauncher(config_path).run()

    assert summary["geographic_outputs_mode"] == "keep"
    assert summary["geographic_outputs_cleanup_applied"] is False
    assert (_stable / "geographic").exists()
    assert (_stable / "demcorrecflow").exists()


def test_mesh_catchment_launcher_requires_mesh_section(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("# no section\n", encoding="utf-8")
    minimal_cfg = _minimal_cfg(tmp_path)

    monkeypatch.setattr(
        "hydromodpy.workflow.pipelines.mesh.load_standard_section",
        lambda _, model_cls, __: (
            minimal_cfg.workspace
            if model_cls.__name__ == "WorkspaceConfig"
            else minimal_cfg.geographic
        ),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.pipelines.mesh.load_toml_with_base_config",
        lambda _: {},
    )

    with pytest.raises(ValueError, match=r"Missing \[mesh_catchment\] section"):
        _ = MeshCatchmentLauncher(config_path)


def test_mesh_catchment_launcher_geology_mode_skips_river_trace_requirement(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        (
            "[mesh_catchment]\n"
            "constraints_mode='geology_only'\n"
            "\n"
            "[mesh_catchment.geology.source]\n"
            "path='data/geology.gpkg'\n"
            "kind='vector'\n"
            "code_field='CODE'\n"
            "reference_raster_path='data/reference.tif'\n"
        ),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}
    minimal_cfg = _minimal_cfg(tmp_path)

    monkeypatch.setattr(
        "hydromodpy.workflow.pipelines.mesh.load_standard_section",
        lambda _, model_cls, __: (
            minimal_cfg.workspace
            if model_cls.__name__ == "WorkspaceConfig"
            else minimal_cfg.geographic
        ),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.pipelines.mesh.load_toml_with_base_config",
        lambda _: {
            "mesh_catchment": {
                "constraints_mode": "geology_only",
                "geology": _minimal_geology_config(),
            }
        },
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.Workspace",
        _DummyWorkspace,
    )
    _patch_dummy_geographic_builders(monkeypatch, river_mesh_trace=None)

    def _fake_run_case(config_toml, **kwargs):
        captured["config_toml"] = config_toml
        captured["kwargs"] = kwargs
        return {"summary_schema_version": "zone_conformal_sidecar_v1"}

    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.run_zone_conformal_meshing_from_toml",
        _fake_run_case,
    )

    launcher = MeshCatchmentLauncher(config_path)
    _ = launcher.run()

    kwargs = captured["kwargs"]
    assert kwargs["river_trace"] is None


def test_mesh_catchment_launcher_requires_constraints_mode(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[mesh_catchment]\n", encoding="utf-8")
    minimal_cfg = _minimal_cfg(tmp_path)

    monkeypatch.setattr(
        "hydromodpy.workflow.pipelines.mesh.load_standard_section",
        lambda _, model_cls, __: (
            minimal_cfg.workspace
            if model_cls.__name__ == "WorkspaceConfig"
            else minimal_cfg.geographic
        ),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.pipelines.mesh.load_toml_with_base_config",
        lambda _: {"mesh_catchment": {}},
    )

    with pytest.raises(ValueError, match="constraints_mode is required"):
        _ = MeshCatchmentLauncher(config_path)
