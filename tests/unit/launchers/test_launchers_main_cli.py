"""Unit tests for the generic ``python -m launchers`` CLI wrapper."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


def _load_module():
    module_path = Path(__file__).resolve().parents[3] / "launchers" / "__main__.py"
    spec = importlib.util.spec_from_file_location(
        "launchers_main_test_module",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module spec for {module_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _DummyCliWorkspace:
    def __init__(self, config) -> None:
        self.config = config
        self.project_root = Path(config.project_root)
        self.catch_name = str(
            getattr(config, "catch_name", self.project_root.name)
        )
        self.catch_folder = self.project_root
        self.stable_folder = self.project_root / "results_stable"


class _DummyCliDomainGeographic:
    def __init__(self, river_mesh_trace=None) -> None:
        self.river_mesh_trace = river_mesh_trace


def _install_mesh_catchment_runtime_stubs(monkeypatch, tmp_path: Path):
    import launchers.mesh_catchment.launcher as launcher_module

    workspace_cfg = SimpleNamespace(
        project_root=tmp_path / "project" / "mesh_cli_case",
        catch_name="mesh_cli_case",
    )
    geographic_cfg = SimpleNamespace(
        uses_synthetic_geographic=lambda: False,
        river_network=SimpleNamespace(enabled=True),
    )

    def _fake_load_standard_section(_, model_cls, __):
        if model_cls.__name__ == "WorkspaceConfig":
            return workspace_cfg
        return geographic_cfg

    def _fake_run_case(config_toml, **kwargs):
        output_mesh = Path(kwargs["output_mesh"])
        output_mesh.parent.mkdir(parents=True, exist_ok=True)
        output_mesh.write_text("$MeshFormat\n2.2 0 8\n$EndMeshFormat\n", encoding="utf-8")

        summary = {
            "summary_schema_version": "zone_conformal_sidecar_v1",
            "output_mesh": str(output_mesh),
            "output_summary_json": str(Path(kwargs["output_summary_json"])),
            "output_figure": (
                ""
                if kwargs.get("output_figure") is None
                else str(Path(kwargs["output_figure"]))
            ),
            "constraints_mode": "geology_only",
        }
        output_summary_json = Path(kwargs["output_summary_json"])
        output_summary_json.parent.mkdir(parents=True, exist_ok=True)
        output_summary_json.write_text(
            json.dumps(summary, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        output_figure = kwargs.get("output_figure")
        if output_figure is not None:
            figure_path = Path(output_figure)
            figure_path.parent.mkdir(parents=True, exist_ok=True)
            figure_path.write_bytes(b"fake-png")
        return summary

    def _fake_export_bundle(**kwargs):
        mesh_path = Path(kwargs["mesh_path"])
        bundle_dir = mesh_path.parent / f"{mesh_path.stem}_bundle"
        bundle_dir.mkdir(parents=True, exist_ok=True)
        (bundle_dir / "metadata.json").write_text(
            json.dumps({"bundle_schema_version": "mesh_catchment_bundle_v1"}),
            encoding="utf-8",
        )
        return {
            "bundle_schema_version": "mesh_catchment_bundle_v1",
            "bundle_dir": str(bundle_dir),
            "mesh_filename": "mesh_2d.msh",
            "n_nodes": 3,
            "n_cells": 1,
            "n_edges": 3,
            "geology_available": False,
        }

    monkeypatch.setattr(launcher_module, "_load_standard_section", _fake_load_standard_section)
    monkeypatch.setattr(launcher_module.hmp, "Workspace", _DummyCliWorkspace)
    monkeypatch.setattr(
        launcher_module,
        "build_domain_geographic_context",
        lambda **_: _DummyCliDomainGeographic(river_mesh_trace=None),
    )
    monkeypatch.setattr(
        launcher_module,
        "run_reference_2d_zone_conformal_case_from_toml",
        _fake_run_case,
    )
    monkeypatch.setattr(
        launcher_module,
        "export_catchment_mesh_bundle",
        _fake_export_bundle,
    )
    return workspace_cfg


def test_launchers_cli_simulation_dispatches_to_launcher(monkeypatch) -> None:
    module = _load_module()
    captured: dict[str, Path] = {}

    config_path = Path("sample_simulation.toml")

    def _fake_runner(path: Path) -> None:
        captured["config"] = path

    monkeypatch.setattr(module, "_run_simulation_launcher", _fake_runner)

    code = module.main(["simulation", str(config_path)])

    assert code == 0
    assert captured["config"] == config_path.resolve()


def test_launchers_cli_mesh_catchment_run_dispatches_to_launcher(monkeypatch) -> None:
    module = _load_module()
    captured: dict[str, Path] = {}

    config_path = Path("sample_mesh_catchment.toml")

    def _fake_runner(path: Path) -> None:
        captured["config"] = path

    monkeypatch.setattr(module, "_run_mesh_catchment_launcher", _fake_runner)

    code = module.main(["mesh-catchment", "run", str(config_path)])

    assert code == 0
    assert captured["config"] == config_path.resolve()


def test_launchers_cli_rejects_unknown_command() -> None:
    module = _load_module()

    code = module.main(["unknown_command", "sample_config.toml"])

    assert code != 0


def test_launchers_cli_returns_error_when_missing_config() -> None:
    module = _load_module()

    code = module.main(["simulation"])

    assert code != 0


def test_launchers_cli_mesh_catchment_returns_error_when_missing_config() -> None:
    module = _load_module()

    code = module.main(["mesh-catchment", "run"])

    assert code != 0


def test_collect_mesh_catchment_figures_supports_single_run_summary() -> None:
    module = _load_module()

    figures = module._collect_mesh_catchment_figures(
        {"output_figure": r"C:\results\HydromodPy\mesh\figure.png"}
    )

    assert figures == [r"C:\results\HydromodPy\mesh\figure.png"]


def test_print_mesh_catchment_figures_supports_batch_summary(capsys) -> None:
    module = _load_module()

    module._print_mesh_catchment_figures(
        {
            "mode": "batch",
            "results": [
                {"output_figure": r"C:\results\HydromodPy\mesh\figure_a.png"},
                {"output_figure": r"C:\results\HydromodPy\mesh\figure_b.png"},
                {"output_figure": ""},
                {},
            ],
        }
    )

    captured = capsys.readouterr()

    assert "Created figures:" in captured.out
    assert r"C:\results\HydromodPy\mesh\figure_a.png" in captured.out
    assert r"C:\results\HydromodPy\mesh\figure_b.png" in captured.out


def test_launchers_cli_mesh_catchment_single_creates_outputs_and_bundle(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_module()
    _ = _install_mesh_catchment_runtime_stubs(monkeypatch, tmp_path)

    config_path = tmp_path / "mesh_catchment_single.toml"
    config_path.write_text(
        "\n".join(
            [
                "[workspace]",
                'project_root = "project/mesh_cli_case"',
                "",
                "[geographic]",
                'catch_def = "from_outlet_coord"',
                "",
                "[mesh_catchment]",
                'constraints_mode = "geology_only"',
                'output_mesh = "outputs/single_mesh.msh"',
                'output_summary_json = "outputs/single_summary.json"',
                'output_figure = "outputs/single_figure.png"',
            ]
        ),
        encoding="utf-8",
    )

    code = module.main(["mesh-catchment", "run", str(config_path)])

    captured = capsys.readouterr()
    output_mesh = (config_path.parent / "outputs" / "single_mesh.msh").resolve()
    output_summary_json = (config_path.parent / "outputs" / "single_summary.json").resolve()
    output_figure = (config_path.parent / "outputs" / "single_figure.png").resolve()
    bundle_dir = (config_path.parent / "outputs" / "single_mesh_bundle").resolve()

    assert code == 0
    assert output_mesh.exists()
    assert output_summary_json.exists()
    assert output_figure.exists()
    assert bundle_dir.exists()
    assert (bundle_dir / "metadata.json").exists()
    assert "Created figures:" in captured.out
    assert str(output_figure) in captured.out


def test_launchers_cli_mesh_catchment_batch_creates_manifest_and_figures(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_module()
    _ = _install_mesh_catchment_runtime_stubs(monkeypatch, tmp_path)

    outlets_csv = tmp_path / "outlets.csv"
    outlets_csv.write_text(
        "outlet_id,x_outlet_m,y_outlet_m\nA,10.0,20.0\nB,30.0,40.0\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "mesh_catchment_batch.toml"
    config_path.write_text(
        "\n".join(
            [
                "[workspace]",
                'project_root = "project/mesh_cli_case"',
                "",
                "[geographic]",
                'catch_def = "from_outlet_coord"',
                "",
                "[mesh_catchment]",
                'constraints_mode = "geology_only"',
                "",
                "[mesh_catchment_batch]",
                "enabled = true",
                'outlets_table_path = "outlets.csv"',
                'selection_mode = "all"',
                'catch_name_pattern = "{catch_name}_outlet_{outlet_id}"',
                "continue_on_error = false",
                "",
                "[mesh_catchment_batch.outputs]",
                'mesh_filename = "mesh_{outlet_id}.msh"',
                'summary_filename = "summary_{outlet_id}.json"',
                'figure_filename = "figure_{outlet_id}.png"',
                'manifest_csv = "batch/manifest.csv"',
            ]
        ),
        encoding="utf-8",
    )

    code = module.main(["mesh-catchment", "run", str(config_path)])

    captured = capsys.readouterr()
    manifest_path = (tmp_path / "project" / "mesh_cli_case" / "batch" / "manifest.csv").resolve()
    figure_a = (
        tmp_path
        / "project"
        / "mesh_cli_case_outlet_A"
        / "results_stable"
        / "mesh"
        / "gmsh"
        / "figure_A.png"
    ).resolve()
    figure_b = (
        tmp_path
        / "project"
        / "mesh_cli_case_outlet_B"
        / "results_stable"
        / "mesh"
        / "gmsh"
        / "figure_B.png"
    ).resolve()
    bundle_a = figure_a.parent / "mesh_A_bundle"
    bundle_b = figure_b.parent / "mesh_B_bundle"

    assert code == 0
    assert manifest_path.exists()
    assert figure_a.exists()
    assert figure_b.exists()
    assert bundle_a.exists()
    assert bundle_b.exists()
    assert "Created figures:" in captured.out
    assert str(figure_a) in captured.out
    assert str(figure_b) in captured.out
