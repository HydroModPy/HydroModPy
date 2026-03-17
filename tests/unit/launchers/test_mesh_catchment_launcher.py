"""Unit tests for the dedicated mesh-catchment launcher."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.geographic.geographic_config import GeographicConfig
from hydromodpy.simulation.workspace.config import WorkspaceConfig
from launchers.mesh_catchment.launcher import MeshCatchmentLauncher


class _DummyWorkspace:
    def __init__(self, config) -> None:
        self.config = config
        self.project_root = Path(config.project_root)
        self.catch_folder = self.project_root
        self.stable_folder = self.project_root / "results_stable"


class _DummyBatchWorkspace:
    def __init__(self, config) -> None:
        self.config = config
        self.catch_name = str(config.catch_name)
        self.out_dir_path = Path(config.out_dir_path)
        self.catch_folder = self.out_dir_path / self.catch_name
        self.stable_folder = self.catch_folder / "results_stable"


class _DummyDomainGeographic:
    def __init__(self, river_mesh_trace=object()) -> None:
        self.river_mesh_trace = river_mesh_trace


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
    return SimpleNamespace(
        workspace=WorkspaceConfig(
            catch_name="mesh_batch",
            out_dir_path=tmp_path / "out",
            data_path=tmp_path / "data",
        ),
        geographic=GeographicConfig(
            catch_def="from_outlet_coord",
            dem_init_path=tmp_path / "regional_dem.tif",
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
        "launchers.mesh_catchment.launcher._load_standard_section",
        lambda _, model_cls, __: (
            minimal_cfg.workspace
            if model_cls.__name__ == "WorkspaceConfig"
            else minimal_cfg.geographic
        ),
    )
    monkeypatch.setattr(
        "launchers.mesh_catchment.launcher.load_toml_with_base_config",
        lambda _: {"mesh_catchment": {"constraints_mode": "rivers_only"}},
    )
    monkeypatch.setattr(
        "launchers.mesh_catchment.launcher.hmp.Workspace",
        _DummyWorkspace,
    )
    monkeypatch.setattr(
        "launchers.mesh_catchment.launcher.build_domain_geographic_context",
        lambda **_: _DummyDomainGeographic(),
    )

    def _fake_run_case(config_toml, **kwargs):
        captured["config_toml"] = config_toml
        captured["kwargs"] = kwargs
        return {"summary_schema_version": "zone_conformal_sidecar_v1"}

    monkeypatch.setattr(
        "launchers.mesh_catchment.launcher.run_reference_2d_zone_conformal_case_from_toml",
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
    assert kwargs["output_mesh"] == (
        expected_root / "results_stable" / "mesh" / "gmsh" / "mesh_catchment.msh"
    )
    assert kwargs["output_summary_json"] == (
        expected_root / "results_stable" / "mesh" / "gmsh" / "mesh_catchment_summary.json"
    )
    assert kwargs["output_figure"] is None
    assert kwargs["domain_geographic"].river_mesh_trace is not None


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
        "launchers.mesh_catchment.launcher._load_standard_section",
        lambda _, model_cls, __: (
            minimal_cfg.workspace
            if model_cls.__name__ == "WorkspaceConfig"
            else minimal_cfg.geographic
        ),
    )
    monkeypatch.setattr(
        "launchers.mesh_catchment.launcher.load_toml_with_base_config",
        lambda _: {
            "mesh_catchment": {
                "constraints_mode": "rivers_only",
                "output_mesh": "mesh/custom_mesh.msh",
                "output_summary_json": "mesh/custom_summary.json",
                "output_figure": "mesh/custom_plot.png",
                "show_plot": True,
            }
        },
    )
    monkeypatch.setattr(
        "launchers.mesh_catchment.launcher.hmp.Workspace",
        _DummyWorkspace,
    )
    monkeypatch.setattr(
        "launchers.mesh_catchment.launcher.build_domain_geographic_context",
        lambda **_: _DummyDomainGeographic(),
    )

    def _fake_run_case(config_toml, **kwargs):
        captured["config_toml"] = config_toml
        captured["kwargs"] = kwargs
        return {"summary_schema_version": "zone_conformal_sidecar_v1"}

    monkeypatch.setattr(
        "launchers.mesh_catchment.launcher.run_reference_2d_zone_conformal_case_from_toml",
        _fake_run_case,
    )

    launcher = MeshCatchmentLauncher(config_path)
    _ = launcher.run()

    kwargs = captured["kwargs"]
    assert kwargs["output_mesh"] == (config_path.parent / "mesh/custom_mesh.msh").resolve()
    assert kwargs["output_summary_json"] == (
        config_path.parent / "mesh/custom_summary.json"
    ).resolve()
    assert kwargs["output_figure"] == (config_path.parent / "mesh/custom_plot.png").resolve()
    assert kwargs["show_plot"] is True
    assert kwargs["river_trace"] is not None


def test_mesh_catchment_launcher_requires_mesh_section(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("# no section\n", encoding="utf-8")
    minimal_cfg = _minimal_cfg(tmp_path)

    monkeypatch.setattr(
        "launchers.mesh_catchment.launcher._load_standard_section",
        lambda _, model_cls, __: (
            minimal_cfg.workspace
            if model_cls.__name__ == "WorkspaceConfig"
            else minimal_cfg.geographic
        ),
    )
    monkeypatch.setattr(
        "launchers.mesh_catchment.launcher.load_toml_with_base_config",
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
        "[mesh_catchment]\nconstraints_mode='geology_only'\n",
        encoding="utf-8",
    )
    captured: dict[str, object] = {}
    minimal_cfg = _minimal_cfg(tmp_path)

    monkeypatch.setattr(
        "launchers.mesh_catchment.launcher._load_standard_section",
        lambda _, model_cls, __: (
            minimal_cfg.workspace
            if model_cls.__name__ == "WorkspaceConfig"
            else minimal_cfg.geographic
        ),
    )
    monkeypatch.setattr(
        "launchers.mesh_catchment.launcher.load_toml_with_base_config",
        lambda _: {"mesh_catchment": {"constraints_mode": "geology_only"}},
    )
    monkeypatch.setattr(
        "launchers.mesh_catchment.launcher.hmp.Workspace",
        _DummyWorkspace,
    )
    monkeypatch.setattr(
        "launchers.mesh_catchment.launcher.build_domain_geographic_context",
        lambda **_: _DummyDomainGeographic(river_mesh_trace=None),
    )

    def _fake_run_case(config_toml, **kwargs):
        captured["config_toml"] = config_toml
        captured["kwargs"] = kwargs
        return {"summary_schema_version": "zone_conformal_sidecar_v1"}

    monkeypatch.setattr(
        "launchers.mesh_catchment.launcher.run_reference_2d_zone_conformal_case_from_toml",
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
        "launchers.mesh_catchment.launcher._load_standard_section",
        lambda _, model_cls, __: (
            minimal_cfg.workspace
            if model_cls.__name__ == "WorkspaceConfig"
            else minimal_cfg.geographic
        ),
    )
    monkeypatch.setattr(
        "launchers.mesh_catchment.launcher.load_toml_with_base_config",
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
        "launchers.mesh_catchment.launcher._load_standard_section",
        lambda _, model_cls, __: (
            runtime_cfg.workspace
            if model_cls.__name__ == "WorkspaceConfig"
            else runtime_cfg.geographic
        ),
    )
    monkeypatch.setattr(
        "launchers.mesh_catchment.launcher.load_toml_with_base_config",
        lambda _: {
            "mesh_catchment": {"constraints_mode": "geology_only"},
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
        "launchers.mesh_catchment.launcher.hmp.Workspace",
        _DummyBatchWorkspace,
    )
    monkeypatch.setattr(
        "launchers.mesh_catchment.launcher.build_domain_geographic_context",
        lambda **_: _DummyDomainGeographic(river_mesh_trace=None),
    )

    def _fake_run_case(config_toml, **kwargs):
        captured_calls.append({"config_toml": config_toml, "kwargs": kwargs})
        return {
            "summary_schema_version": "zone_conformal_sidecar_v1",
            "output_mesh": str(kwargs["output_mesh"]),
            "output_summary_json": str(kwargs["output_summary_json"]),
            "output_figure": str(kwargs["output_figure"]),
        }

    monkeypatch.setattr(
        "launchers.mesh_catchment.launcher.run_reference_2d_zone_conformal_case_from_toml",
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
        "mesh_batch_outlet_2\\results_stable\\mesh\\gmsh\\mesh_2.msh"
    )
    assert str(kwargs["output_summary_json"]).endswith(
        "mesh_batch_outlet_2\\results_stable\\mesh\\gmsh\\summary_2.json"
    )
    assert str(kwargs["output_figure"]).endswith(
        "mesh_batch_outlet_2\\results_stable\\mesh\\gmsh\\figure_2.png"
    )

    manifest_path = Path(summary["manifest_csv"])
    assert manifest_path.exists()
    manifest_text = manifest_path.read_text(encoding="utf-8")
    assert "outlet_id,catch_name,status" in manifest_text
    assert "2,mesh_batch_outlet_2,ok" in manifest_text


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
        "launchers.mesh_catchment.launcher._load_standard_section",
        lambda _, model_cls, __: (
            runtime_cfg.workspace
            if model_cls.__name__ == "WorkspaceConfig"
            else runtime_cfg.geographic
        ),
    )
    monkeypatch.setattr(
        "launchers.mesh_catchment.launcher.load_toml_with_base_config",
        lambda _: {
            "mesh_catchment": {
                "constraints_mode": "geology_only",
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
