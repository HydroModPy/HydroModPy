"""Unit tests for the mesh-catchment runtime helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.workspace.path_registry import PREPROCESSING_DIR
from hydromodpy.spatial.mesh.config import MeshCatchmentConfig
from hydromodpy.spatial.mesh.launcher import runtime as mesh_runtime

from ._mesh_catchment_builders import (
    _DummyDomainGeographic,
    _DummyGeographicFeatures,
    _DummyWorkspace,
)


def test_mesh_runtime_require_mesh_section_returns_typed_model() -> None:
    section = mesh_runtime.require_mesh_section(
        {"mesh_catchment": {"constraints_mode": "rivers_only"}}
    )

    assert isinstance(section, MeshCatchmentConfig)
    assert section.constraints_mode == "rivers_only"
    assert section.domain.kind == "geographic_box_buffer"


def test_prepare_geographic_config_for_meshing_updates_simple_namespace_runtime() -> None:
    geographic_cfg = SimpleNamespace(
        uses_synthetic_geographic=lambda: False,
        river_network=SimpleNamespace(enabled=False),
    )

    updated = mesh_runtime.prepare_geographic_config_for_meshing(
        geographic_cfg,
        constraints_mode="rivers_only",
    )

    assert updated is not geographic_cfg
    assert updated.river_network.enabled is True
    assert geographic_cfg.river_network.enabled is False


def test_mesh_runtime_can_skip_exchange_bundle_export(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace_cfg = SimpleNamespace(project_root=tmp_path / "projects" / "mesh_catchment_case")
    geographic_cfg = SimpleNamespace(
        uses_synthetic_geographic=lambda: False,
        river_network=SimpleNamespace(enabled=True),
    )
    local_workspace = _DummyWorkspace(workspace_cfg)

    def _fake_run_case(config_toml, **kwargs):
        _ = config_toml
        kwargs["output_mesh"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["output_mesh"].write_text("mesh", encoding="utf-8")
        return {"summary_schema_version": "zone_conformal_sidecar_v1"}

    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.run_zone_conformal_meshing_from_toml",
        _fake_run_case,
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.export_catchment_mesh_bundle",
        lambda **_: pytest.fail("exchange bundle export should be skipped"),
    )

    summary = mesh_runtime.run_single_mesh_catchment_workflow(
        config_path=tmp_path / "config.toml",
        section_data=MeshCatchmentConfig.model_validate(
            {
                "constraints_mode": "rivers_only",
                "export_exchange_bundle": False,
            }
        ),
        workspace_cfg=workspace_cfg,
        geographic_cfg=geographic_cfg,
        domain_cfg=SimpleNamespace(depth_model=SimpleNamespace(kind="constant_thickness")),
        constraints_mode="rivers_only",
        workspace=local_workspace,
        geographic_features=_DummyGeographicFeatures(),
        domain_geographic=_DummyDomainGeographic(),
    )

    assert summary["exchange_bundle_export_enabled"] is False
    assert "output_exchange_bundle_dir" not in summary


def test_mesh_runtime_cleanup_mode_skips_external_domain_geographic(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace_cfg = SimpleNamespace(project_root=tmp_path / "projects" / "mesh_catchment_case")
    geographic_cfg = SimpleNamespace(
        uses_synthetic_geographic=lambda: False,
        river_network=SimpleNamespace(enabled=True),
    )
    local_workspace = _DummyWorkspace(workspace_cfg)

    _stable = workspace_cfg.project_root / PREPROCESSING_DIR

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

    summary = mesh_runtime.run_single_mesh_catchment_workflow(
        config_path=tmp_path / "config.toml",
        section_data=MeshCatchmentConfig.model_validate(
            {
                "constraints_mode": "rivers_only",
                "geographic_outputs_mode": "cleanup",
            }
        ),
        workspace_cfg=workspace_cfg,
        geographic_cfg=geographic_cfg,
        domain_cfg=SimpleNamespace(depth_model=SimpleNamespace(kind="constant_thickness")),
        constraints_mode="rivers_only",
        workspace=local_workspace,
        geographic_features=_DummyGeographicFeatures(),
        domain_geographic=_DummyDomainGeographic(),
    )

    assert summary["geographic_outputs_mode"] == "cleanup"
    assert summary["geographic_outputs_cleanup_applied"] is False
    assert (_stable / "geographic").exists()
    assert (_stable / "demcorrecflow").exists()


def test_mesh_runtime_accepts_external_geographic_features(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace_cfg = SimpleNamespace(project_root=tmp_path / "projects" / "mesh_catchment_case")
    geographic_cfg = SimpleNamespace(
        uses_synthetic_geographic=lambda: False,
        river_network=SimpleNamespace(enabled=True),
    )
    local_workspace = _DummyWorkspace(workspace_cfg)
    captured: dict[str, object] = {}

    def _fake_run_case(config_toml, **kwargs):
        _ = config_toml
        captured["kwargs"] = kwargs
        return {"summary_schema_version": "zone_conformal_sidecar_v1"}

    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.run_zone_conformal_meshing_from_toml",
        _fake_run_case,
    )

    summary = mesh_runtime.run_single_mesh_catchment_workflow(
        config_path=tmp_path / "config.toml",
        section_data=MeshCatchmentConfig.model_validate(
            {
                "constraints_mode": "rivers_only",
            }
        ),
        workspace_cfg=workspace_cfg,
        geographic_cfg=geographic_cfg,
        domain_cfg=None,
        constraints_mode="rivers_only",
        workspace=local_workspace,
        geographic_features=_DummyGeographicFeatures(river_mesh_trace="trace-1"),
    )

    assert summary["summary_schema_version"] == "zone_conformal_sidecar_v1"
    assert captured["kwargs"]["river_trace"] == "trace-1"
    assert captured["kwargs"]["geographic_features"].rivers.river_mesh_trace == "trace-1"
    assert not hasattr(captured["kwargs"]["domain_geographic"], "river_mesh_trace")
