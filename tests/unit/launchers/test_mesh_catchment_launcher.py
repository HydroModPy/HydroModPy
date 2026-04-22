"""Unit tests for the dedicated mesh-catchment launcher."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.mesh import runtime as mesh_runtime
from hydromodpy.spatial.mesh.config import MeshCatchmentConfig
from hydromodpy.workflow.pipelines.mesh import MeshCatchmentLauncher


class _DummyWorkspace:
    def __init__(self, config) -> None:
        self.config = config
        self.project_root = Path(config.project_root)
        self.solver_scratch_folder = self.project_root / ".solver_scratch"


class _DummyBatchWorkspace:
    def __init__(self, config) -> None:
        self.config = config
        self.project_root = Path(config.project_root)
        self.catch_name = str(config.catch_name)
        self.solver_scratch_folder = self.project_root / ".solver_scratch"


class _DummyDomainGeographic:
    def __init__(self, river_mesh_trace=object()) -> None:
        self.river_mesh_trace = river_mesh_trace


class _DummyGeographicFeatures:
    def __init__(self, river_mesh_trace=object()) -> None:
        self.rivers = SimpleNamespace(river_mesh_trace=river_mesh_trace)

    def to_domain_geographic_context(self) -> _DummyDomainGeographic:
        return _DummyDomainGeographic(river_mesh_trace=self.rivers.river_mesh_trace)


def _patch_dummy_geographic_builders(
    monkeypatch: pytest.MonkeyPatch,
    *,
    builder=None,
    river_mesh_trace=object(),
) -> None:
    build_fn = (
        builder
        if builder is not None
        else (lambda **_: _DummyGeographicFeatures(river_mesh_trace=river_mesh_trace))
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.runtime.build_geographic_derived_features",
        build_fn,
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.runtime.build_domain_geographic_context",
        lambda **kwargs: build_fn(**kwargs).to_domain_geographic_context(),
    )


def _write_test_raster(path: Path, *, xmin: float, ymin: float, xmax: float, ymax: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pixel_size = 100.0
    width = max(1, int(round((xmax - xmin) / pixel_size)))
    height = max(1, int(round((ymax - ymin) / pixel_size)))
    transform = from_origin(float(xmin), float(ymax), pixel_size, pixel_size)
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": rasterio.float32,
        "crs": "EPSG:2154",
        "transform": transform,
        "nodata": -9999.0,
    }
    data = np.ones((height, width), dtype=np.float32)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)


def _minimal_geology_config(
    *,
    reference_raster_path: str = "data/reference.tif",
) -> dict[str, object]:
    return {
        "source": {
            "path": "data/geology.gpkg",
            "kind": "vector",
            "code_field": "CODE",
            "reference_raster_path": reference_raster_path,
        }
    }


def _minimal_cfg(tmp_path: Path):
    return SimpleNamespace(
        workspace=SimpleNamespace(
            project_root=tmp_path / "projects" / "mesh_catchment_case",
        ),
        geographic=SimpleNamespace(
            uses_synthetic_geographic=lambda: False,
            river_network=SimpleNamespace(enabled=True),
        ),
    )


def _batch_cfg(tmp_path: Path):
    dem_path = tmp_path / "regional_dem.tif"
    _write_test_raster(
        dem_path,
        xmin=0.0,
        ymin=0.0,
        xmax=1000.0,
        ymax=1000.0,
    )
    return SimpleNamespace(
        workspace=WorkspaceConfig(
            project_root=tmp_path / "out" / "mesh_batch",
            root=tmp_path,
        ),
        geographic=GeographicConfig(
            catch_def="from_outlet_coord",
            dem_init_path=dem_path,
            x_outlet=389285.910,
            y_outlet=6816518.749,
            snap_dist="50 m",
            buff_area="20%",
            crs_project="EPSG:2154",
        ),
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
        "hydromodpy.workflow.pipelines.mesh._load_standard_section",
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
        "hydromodpy.spatial.mesh.runtime.hmp.Workspace",
        _DummyWorkspace,
    )
    _patch_dummy_geographic_builders(monkeypatch)

    def _fake_run_case(config_toml, **kwargs):
        captured["config_toml"] = config_toml
        captured["kwargs"] = kwargs
        return {"summary_schema_version": "zone_conformal_sidecar_v1"}

    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.runtime.run_reference_2d_zone_conformal_case_from_toml",
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
    assert kwargs["domain_geographic"].river_mesh_trace is not None


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
        "hydromodpy.workflow.pipelines.mesh._load_standard_section",
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
        "hydromodpy.spatial.mesh.runtime.hmp.Workspace",
        _DummyWorkspace,
    )
    _patch_dummy_geographic_builders(monkeypatch)
    captured: dict[str, object] = {}

    def _fake_run_case(config_toml, **kwargs):
        captured["config_toml"] = config_toml
        captured["kwargs"] = kwargs
        return {"summary_schema_version": "zone_conformal_sidecar_v1"}

    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.runtime.run_reference_2d_zone_conformal_case_from_toml",
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
        "hydromodpy.workflow.pipelines.mesh._load_standard_section",
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
        "hydromodpy.spatial.mesh.runtime.hmp.Workspace",
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
        "hydromodpy.spatial.mesh.runtime.run_reference_2d_zone_conformal_case_from_toml",
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
                "type": "flat_substratum",
                "substratum_elevation": 12.5,
            }
        }
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "hydromodpy.workflow.pipelines.mesh._load_standard_section",
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
                    "type": "flat_substratum",
                    "substratum_elevation": 12.5,
                }
            },
            "mesh_catchment": {"constraints_mode": "rivers_only"},
        },
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.runtime.hmp.Workspace",
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
        "hydromodpy.spatial.mesh.runtime.run_reference_2d_zone_conformal_case_from_toml",
        _fake_run_case,
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.runtime.export_catchment_mesh_bundle",
        _fake_export_bundle,
    )

    _ = MeshCatchmentLauncher(config_path).run()

    exported_domain_cfg = captured["domain_cfg"]
    assert exported_domain_cfg.depth_model.type == "flat_substratum"
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
        "hydromodpy.workflow.pipelines.mesh._load_standard_section",
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
        "hydromodpy.spatial.mesh.runtime.hmp.Workspace",
        _DummyWorkspace,
    )
    _patch_dummy_geographic_builders(monkeypatch)

    def _fake_run_case(config_toml, **kwargs):
        captured["config_toml"] = config_toml
        captured["kwargs"] = kwargs
        return {"summary_schema_version": "zone_conformal_sidecar_v1"}

    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.runtime.run_reference_2d_zone_conformal_case_from_toml",
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
        "hydromodpy.workflow.pipelines.mesh._load_standard_section",
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
        "hydromodpy.spatial.mesh.runtime.hmp.Workspace",
        _DummyWorkspace,
    )
    _patch_dummy_geographic_builders(monkeypatch)

    def _fake_run_case(config_toml, **kwargs):
        captured["config_toml"] = config_toml
        captured["kwargs"] = kwargs
        return {"summary_schema_version": "zone_conformal_sidecar_v1"}

    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.runtime.run_reference_2d_zone_conformal_case_from_toml",
        _fake_run_case,
    )

    launcher = MeshCatchmentLauncher(config_path)
    _ = launcher.run()

    kwargs = captured["kwargs"]
    assert kwargs["output_figure"] is None
    assert kwargs["output_figure_regional"] is None
    assert kwargs["show_plot"] is False


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
        "hydromodpy.workflow.pipelines.mesh._load_standard_section",
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
        "hydromodpy.spatial.mesh.runtime.hmp.Workspace",
        _DummyWorkspace,
    )
    _patch_dummy_geographic_builders(monkeypatch)

    _stable = minimal_cfg.workspace.project_root / ".solver_scratch/_preprocessing"

    def _fake_run_case(config_toml, **kwargs):
        (_stable / "geographic" / "tmp").mkdir(parents=True, exist_ok=True)
        (_stable / "demcorrecflow" / "tmp").mkdir(parents=True, exist_ok=True)
        kwargs["output_mesh"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["output_mesh"].write_text("mesh", encoding="utf-8")
        return {"summary_schema_version": "zone_conformal_sidecar_v1"}

    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.runtime.run_reference_2d_zone_conformal_case_from_toml",
        _fake_run_case,
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.runtime.export_catchment_mesh_bundle",
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
        "hydromodpy.workflow.pipelines.mesh._load_standard_section",
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
        "hydromodpy.spatial.mesh.runtime.hmp.Workspace",
        _DummyWorkspace,
    )
    _patch_dummy_geographic_builders(monkeypatch)

    _stable = minimal_cfg.workspace.project_root / ".solver_scratch/_preprocessing"

    def _fake_run_case(config_toml, **kwargs):
        (_stable / "geographic" / "tmp").mkdir(parents=True, exist_ok=True)
        (_stable / "demcorrecflow" / "tmp").mkdir(parents=True, exist_ok=True)
        kwargs["output_mesh"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["output_mesh"].write_text("mesh", encoding="utf-8")
        return {"summary_schema_version": "zone_conformal_sidecar_v1"}

    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.runtime.run_reference_2d_zone_conformal_case_from_toml",
        _fake_run_case,
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.runtime.export_catchment_mesh_bundle",
        lambda **_: {"bundle_dir": str(tmp_path / "bundle")},
    )

    summary = MeshCatchmentLauncher(config_path).run()

    assert summary["geographic_outputs_mode"] == "keep"
    assert summary["geographic_outputs_cleanup_applied"] is False
    assert (_stable / "geographic").exists()
    assert (_stable / "demcorrecflow").exists()


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
        "hydromodpy.spatial.mesh.runtime.run_reference_2d_zone_conformal_case_from_toml",
        _fake_run_case,
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.runtime.export_catchment_mesh_bundle",
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
        domain_cfg=SimpleNamespace(depth_model=SimpleNamespace(type="constant_thickness")),
        constraints_mode="rivers_only",
        workspace=local_workspace,
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

    _stable = workspace_cfg.project_root / ".solver_scratch/_preprocessing"

    def _fake_run_case(config_toml, **kwargs):
        (_stable / "geographic" / "tmp").mkdir(parents=True, exist_ok=True)
        (_stable / "demcorrecflow" / "tmp").mkdir(parents=True, exist_ok=True)
        kwargs["output_mesh"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["output_mesh"].write_text("mesh", encoding="utf-8")
        return {"summary_schema_version": "zone_conformal_sidecar_v1"}

    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.runtime.run_reference_2d_zone_conformal_case_from_toml",
        _fake_run_case,
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.runtime.export_catchment_mesh_bundle",
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
        domain_cfg=SimpleNamespace(depth_model=SimpleNamespace(type="constant_thickness")),
        constraints_mode="rivers_only",
        workspace=local_workspace,
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
        "hydromodpy.spatial.mesh.runtime.run_reference_2d_zone_conformal_case_from_toml",
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
    assert captured["kwargs"]["domain_geographic"].river_mesh_trace == "trace-1"


def test_mesh_catchment_launcher_requires_mesh_section(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("# no section\n", encoding="utf-8")
    minimal_cfg = _minimal_cfg(tmp_path)

    monkeypatch.setattr(
        "hydromodpy.workflow.pipelines.mesh._load_standard_section",
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
        "hydromodpy.workflow.pipelines.mesh._load_standard_section",
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
        "hydromodpy.spatial.mesh.runtime.hmp.Workspace",
        _DummyWorkspace,
    )
    _patch_dummy_geographic_builders(monkeypatch, river_mesh_trace=None)

    def _fake_run_case(config_toml, **kwargs):
        captured["config_toml"] = config_toml
        captured["kwargs"] = kwargs
        return {"summary_schema_version": "zone_conformal_sidecar_v1"}

    monkeypatch.setattr(
        "hydromodpy.spatial.mesh.runtime.run_reference_2d_zone_conformal_case_from_toml",
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
        "hydromodpy.workflow.pipelines.mesh._load_standard_section",
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
        "hydromodpy.workflow.pipelines.mesh._load_standard_section",
        lambda _, model_cls, __: (
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
        "hydromodpy.spatial.mesh.runtime.hmp.Workspace",
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
        "hydromodpy.spatial.mesh.runtime.run_reference_2d_zone_conformal_case_from_toml",
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
        str(Path("mesh_batch_outlet_2") / ".solver_scratch/_preprocessing" / "mesh" / "mesh_2.msh")
    )
    assert str(kwargs["output_summary_json"]).endswith(
        str(
            Path("mesh_batch_outlet_2")
            / ".solver_scratch/_preprocessing"
            / "mesh"
            / "summary_2.json"
        )
    )
    assert str(kwargs["output_figure"]).endswith(
        str(
            Path("mesh_batch_outlet_2") / ".solver_scratch/_preprocessing" / "mesh" / "figure_2.png"
        )
    )
    assert str(kwargs["output_figure_regional"]).endswith(
        str(
            Path("mesh_batch_outlet_2")
            / ".solver_scratch/_preprocessing"
            / "mesh"
            / "figure_2_regional.png"
        )
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
        "hydromodpy.workflow.pipelines.mesh._load_standard_section",
        lambda _, model_cls, __: (
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
        "hydromodpy.spatial.mesh.runtime.hmp.Workspace",
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
        "hydromodpy.spatial.mesh.runtime.run_reference_2d_zone_conformal_case_from_toml",
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
        "hydromodpy.workflow.pipelines.mesh._load_standard_section",
        lambda _, model_cls, __: (
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
        "hydromodpy.spatial.mesh.runtime.hmp.Workspace",
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
        "hydromodpy.spatial.mesh.runtime.run_reference_2d_zone_conformal_case_from_toml",
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
        "hydromodpy.workflow.pipelines.mesh._load_standard_section",
        lambda _, model_cls, __: (
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
            catch_def="from_outlet_coord",
            dem_init_path=dem_path,
            x_outlet=100.0,
            y_outlet=100.0,
            snap_dist="50 m",
            buff_area="20%",
            crs_project="EPSG:2154",
        ),
    )

    monkeypatch.setattr(
        "hydromodpy.workflow.pipelines.mesh._load_standard_section",
        lambda _, model_cls, __: (
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
