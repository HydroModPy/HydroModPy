"""Unit tests for the dedicated mesh-catchment launcher (non-batch runs)."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.workflow.pipelines.mesh import MeshCatchmentLauncher

from ._mesh_catchment_builders import (
    _DummyGeographicFeatures,
    _DummyWorkspace,
    _minimal_cfg,
    _patch_dummy_geographic_builders,
)


def test_mesh_catchment_launcher_run_uses_default_outputs(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[mesh_catchment]\nconstraints_mode='rivers_only'\n",
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
        lambda _: {"mesh_catchment": {"constraints_mode": "rivers_only"}},
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.Workspace",
        _DummyWorkspace,
    )
    _patch_dummy_geographic_builders(monkeypatch)

    def _fake_run_case(config_toml, **kwargs):
        captured["config_toml"] = config_toml
        captured["kwargs"] = kwargs
        return {"summary_schema_version": "zone_conformal_sidecar_v1"}

    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.run_zone_conformal_meshing_from_toml",
        _fake_run_case,
    )

    launcher = MeshCatchmentLauncher(config_path)
    summary = launcher.run()

    kwargs = captured["kwargs"]
    assert summary["summary_schema_version"] == "zone_conformal_sidecar_v1"
    assert captured["config_toml"] == config_path.resolve()
    assert kwargs["section"] == "mesh_catchment"
    assert kwargs["show_plot"] is False
    assert kwargs["river_trace"] is not None
    expected_root = minimal_cfg.workspace.project_root
    assert kwargs["output_mesh"] == (expected_root / "mesh" / "mesh_catchment.msh")
    assert kwargs["output_summary_json"] == (expected_root / "mesh" / "mesh_catchment_summary.json")
    assert kwargs["output_figure"] is None
    assert kwargs["output_figure_regional"] is None
    assert kwargs["section_data_override"]["domain"]["kind"] == "geographic_box_buffer"
    assert kwargs["section_data_override"]["watershed_boundary"]["enabled"] is False
    assert kwargs["geographic_features"].rivers.river_mesh_trace is not None
    assert not hasattr(kwargs["domain_geographic"], "river_mesh_trace")


def test_mesh_catchment_launcher_accepts_watershed_boundary_section(
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
                "watershed_boundary": {
                    "enabled": True,
                    "boundary_refinement_distance": 500.0,
                    "smoothing": {
                        "enabled": True,
                        "distance": 50.0,
                        "river_buffer_distance": 100.0,
                        "outer_bias_distance": 10.0,
                    },
                },
            }
        },
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.Workspace",
        _DummyWorkspace,
    )
    _patch_dummy_geographic_builders(monkeypatch)
    captured: dict[str, object] = {}

    def _fake_run_case(config_toml, **kwargs):
        captured["config_toml"] = config_toml
        captured["kwargs"] = kwargs
        return {"summary_schema_version": "zone_conformal_sidecar_v1"}

    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.run_zone_conformal_meshing_from_toml",
        _fake_run_case,
    )

    summary = MeshCatchmentLauncher(config_path).run()

    assert summary["summary_schema_version"] == "zone_conformal_sidecar_v1"
    assert captured["kwargs"]["section_data_override"]["watershed_boundary"]["enabled"] is True
    assert (
        captured["kwargs"]["section_data_override"]["watershed_boundary"][
            "boundary_refinement_distance"
        ]
        == 500.0
    )


def test_mesh_catchment_launcher_flat_output_layout_writes_directly_to_project_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[mesh_catchment]\nconstraints_mode='rivers_only'\noutput_layout='flat'\n",
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
                "constraints_mode": "rivers_only",
                "output_layout": "flat",
            }
        },
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.Workspace",
        _DummyWorkspace,
    )

    def _fake_build_geographic_derived_features(**kwargs):
        runtime_root = Path(kwargs["workspace"].project_root)
        captured["runtime_workspace_project_root"] = runtime_root
        (runtime_root / ".solver_scratch/_preprocessing" / "geographic").mkdir(
            parents=True, exist_ok=True
        )
        (runtime_root / "results_simulations").mkdir(parents=True, exist_ok=True)
        (runtime_root / "results_calibration").mkdir(parents=True, exist_ok=True)
        return _DummyGeographicFeatures()

    _patch_dummy_geographic_builders(
        monkeypatch,
        builder=_fake_build_geographic_derived_features,
    )

    def _fake_run_case(config_toml, **kwargs):
        captured["kwargs"] = kwargs
        return {"summary_schema_version": "zone_conformal_sidecar_v1"}

    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.run_zone_conformal_meshing_from_toml",
        _fake_run_case,
    )

    summary = MeshCatchmentLauncher(config_path).run()

    kwargs = captured["kwargs"]
    expected_root = minimal_cfg.workspace.project_root
    runtime_workspace_project_root = Path(captured["runtime_workspace_project_root"])
    assert summary["output_layout"] == "flat"
    assert kwargs["output_mesh"] == expected_root / "mesh_catchment.msh"
    assert kwargs["output_summary_json"] == (expected_root / "mesh_catchment_summary.json")
    assert kwargs["output_figure"] is None
    assert kwargs["output_figure_regional"] is None
    assert runtime_workspace_project_root == (
        expected_root.parent / "_mesh_runtime" / expected_root.name
    )
    assert not runtime_workspace_project_root.exists()
    assert not (expected_root / ".solver_scratch/_preprocessing").exists()
    assert not (expected_root / "results_simulations").exists()
    assert not (expected_root / "results_calibration").exists()


def test_mesh_catchment_launcher_passes_domain_depth_model_to_bundle_export(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[mesh_catchment]\nconstraints_mode='rivers_only'\n",
        encoding="utf-8",
    )
    minimal_cfg = _minimal_cfg(tmp_path)
    domain_cfg = DomainConfig.model_validate(
        {
            "depth_model": {
                "kind": "flat_substratum",
                "substratum_elevation": 12.5,
            }
        }
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "hydromodpy.workflow.pipelines.mesh.load_standard_section",
        lambda _, model_cls, __: (
            minimal_cfg.workspace
            if model_cls.__name__ == "WorkspaceConfig"
            else (
                minimal_cfg.geographic if model_cls.__name__ == "GeographicConfig" else domain_cfg
            )
        ),
    )
    monkeypatch.setattr(
        "hydromodpy.workflow.pipelines.mesh.load_toml_with_base_config",
        lambda _: {
            "domain": {
                "depth_model": {
                    "kind": "flat_substratum",
                    "substratum_elevation": 12.5,
                }
            },
            "mesh_catchment": {"constraints_mode": "rivers_only"},
        },
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.Workspace",
        _DummyWorkspace,
    )
    _patch_dummy_geographic_builders(monkeypatch)

    def _fake_run_case(config_toml, **kwargs):
        kwargs["output_mesh"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["output_mesh"].write_text("mesh", encoding="utf-8")
        kwargs["output_summary_json"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["output_summary_json"].write_text("{}", encoding="utf-8")
        return {"summary_schema_version": "zone_conformal_sidecar_v1"}

    def _fake_export_bundle(**kwargs):
        captured.update(kwargs)
        return {"bundle_dir": str(tmp_path / "bundle")}

    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.run_zone_conformal_meshing_from_toml",
        _fake_run_case,
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.export_catchment_mesh_bundle",
        _fake_export_bundle,
    )

    _ = MeshCatchmentLauncher(config_path).run()

    exported_domain_cfg = captured["domain_cfg"]
    assert exported_domain_cfg.depth_model.kind == "flat_substratum"
    assert exported_domain_cfg.depth_model.substratum_elevation == 12.5


def test_mesh_catchment_launcher_run_uses_section_output_overrides(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[mesh_catchment]\nconstraints_mode='rivers_only'\n",
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
                "constraints_mode": "rivers_only",
                "output_mesh": "mesh/custom_mesh.msh",
                "output_summary_json": "mesh/custom_summary.json",
                "output_figure": "mesh/custom_plot.png",
                "output_figure_regional": "mesh/custom_plot_regional.png",
                "show_plot": True,
            }
        },
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.Workspace",
        _DummyWorkspace,
    )
    _patch_dummy_geographic_builders(monkeypatch)

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
    assert kwargs["output_mesh"] == (config_path.parent / "mesh/custom_mesh.msh").resolve()
    assert (
        kwargs["output_summary_json"] == (config_path.parent / "mesh/custom_summary.json").resolve()
    )
    assert kwargs["output_figure"] == (config_path.parent / "mesh/custom_plot.png").resolve()
    assert (
        kwargs["output_figure_regional"]
        == (config_path.parent / "mesh/custom_plot_regional.png").resolve()
    )
    assert kwargs["show_plot"] is True
    assert kwargs["river_trace"] is not None


def test_mesh_catchment_launcher_disables_figure_outputs_when_requested(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[mesh_catchment]\nconstraints_mode='rivers_only'\n",
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
                "constraints_mode": "rivers_only",
                "output_figure": "mesh/custom_plot.png",
                "output_figure_regional": "mesh/custom_plot_regional.png",
                "figures_enabled": False,
                "show_plot": True,
            }
        },
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.launcher.runtime.Workspace",
        _DummyWorkspace,
    )
    _patch_dummy_geographic_builders(monkeypatch)

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
    assert kwargs["output_figure"] is None
    assert kwargs["output_figure_regional"] is None
    assert kwargs["show_plot"] is False
