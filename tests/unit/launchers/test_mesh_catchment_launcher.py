"""Unit tests for the dedicated mesh-catchment launcher."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from launchers.mesh_catchment.launcher import MeshCatchmentLauncher


class _DummyWorkspace:
    def __init__(self, config) -> None:
        self.config = config
        self.stable_folder = Path(config.out_dir_path) / "results_stable"


class _DummyDomainGeographic:
    def __init__(self, river_mesh_trace=object()) -> None:
        self.river_mesh_trace = river_mesh_trace


def _minimal_cfg(tmp_path: Path):
    return SimpleNamespace(
        workspace=SimpleNamespace(
            out_dir_path=tmp_path / "out",
            data_path=tmp_path / "data",
            catch_name="mesh_catchment_case",
        ),
        geographic=SimpleNamespace(
            uses_synthetic_geographic=lambda: False,
            river_network=SimpleNamespace(enabled=True),
        ),
    )


def test_mesh_catchment_launcher_run_uses_default_outputs(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[mesh_catchment]\n", encoding="utf-8")
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
        "launchers.mesh_catchment.launcher.resolve_launcher_output_root",
        lambda out_dir: (Path(out_dir), "configured"),
    )
    monkeypatch.setattr(
        "launchers.mesh_catchment.launcher.load_toml_with_base_config",
        lambda _: {"mesh_catchment": {}},
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
        "launchers.mesh_catchment.launcher.run_reference_2d_geology_conformal_case_from_toml",
        _fake_run_case,
    )

    launcher = MeshCatchmentLauncher(config_path)
    summary = launcher.run()

    kwargs = captured["kwargs"]
    assert summary["summary_schema_version"] == "zone_conformal_sidecar_v1"
    assert captured["config_toml"] == config_path.resolve()
    assert kwargs["section"] == "mesh_catchment"
    assert kwargs["mesh_mode_override"] == "rivers"
    assert kwargs["show_plot"] is False
    assert kwargs["river_trace"] is not None
    assert kwargs["output_mesh"] == (
        (minimal_cfg.workspace.out_dir_path / "results_stable" / "mesh" / "gmsh" / "mesh_catchment.msh")
    )
    assert kwargs["output_summary_json"] == (
        (minimal_cfg.workspace.out_dir_path / "results_stable" / "mesh" / "gmsh" / "mesh_catchment_summary.json")
    )
    assert kwargs["output_figure"] is None
    assert kwargs["domain_geographic"].river_mesh_trace is not None


def test_mesh_catchment_launcher_run_uses_section_output_overrides(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[mesh_catchment]\n", encoding="utf-8")
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
        "launchers.mesh_catchment.launcher.resolve_launcher_output_root",
        lambda out_dir: (Path(out_dir), "configured"),
    )
    monkeypatch.setattr(
        "launchers.mesh_catchment.launcher.load_toml_with_base_config",
        lambda _: {
            "mesh_catchment": {
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
        "launchers.mesh_catchment.launcher.run_reference_2d_geology_conformal_case_from_toml",
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
    assert kwargs["mesh_mode_override"] == "rivers"
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
        "launchers.mesh_catchment.launcher.resolve_launcher_output_root",
        lambda out_dir: (Path(out_dir), "configured"),
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
    config_path.write_text("[mesh_catchment]\nmesh_mode='geology'\n", encoding="utf-8")
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
        "launchers.mesh_catchment.launcher.resolve_launcher_output_root",
        lambda out_dir: (Path(out_dir), "configured"),
    )
    monkeypatch.setattr(
        "launchers.mesh_catchment.launcher.load_toml_with_base_config",
        lambda _: {"mesh_catchment": {"mesh_mode": "geology"}},
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
        "launchers.mesh_catchment.launcher.run_reference_2d_geology_conformal_case_from_toml",
        _fake_run_case,
    )

    launcher = MeshCatchmentLauncher(config_path)
    _ = launcher.run()

    kwargs = captured["kwargs"]
    assert kwargs["mesh_mode_override"] == "geology"
    assert kwargs["river_trace"] is None
