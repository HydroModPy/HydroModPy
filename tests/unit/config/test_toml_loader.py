from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.config.hydromodpy_config import ROOT_CONFIG
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.core.toml_io.loader import (
    config_base_dir,
    load_toml_with_base_config,
    read_toml_chain,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def simulation_regression_fixture(name: str) -> Path:
    """Path to a TOML fixture under tests/regression/.../simulation_regression."""
    return (
        REPO_ROOT
        / "tests"
        / "regression"
        / "fixtures"
        / "projects"
        / "simulation_regression"
        / name
    )


def example_project_config(*parts: str) -> Path:
    """Path to a project.toml under examples/projects."""
    return REPO_ROOT.joinpath("examples", "projects", *parts)


def test_simulation_regression_example_config_inheritance_keeps_only_relevant_data_types() -> None:
    example_config = simulation_regression_fixture("run_fast_mf6.toml")

    payload = load_toml_with_base_config(example_config, root=ROOT_CONFIG)

    assert list(payload["flow"]["bc"]) == ["ocean", "drainage"]
    assert payload["data"]["types"] == ["recharge"]
    assert "hydrography" not in payload["data"]
    assert payload["data"]["oceanic"]["sources"][0]["source"] == "file"
    assert payload["data"]["recharge"]["sources"][0]["source"] == "synthetic"


def test_simulation_regression_mf6_precomputed_mesh_config_reads_the_triangulation_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    example_config = simulation_regression_fixture("run_fast_mf6_precomputed_mesh_input.toml")

    payload = load_toml_with_base_config(example_config, root=ROOT_CONFIG)

    assert payload["mesh"]["engine"] == "voronoi"
    assert payload["mesh"]["triangle"]["path"] == "mesh/mesh_catchment.msh"
    assert payload["mesh"]["voronoi"]["seeds"] == "triangulation"
    assert "mesh_input" not in payload
    assert "sgrid" not in payload.get("modflow6", {})
    assert payload["domain"]["layers"]["nlay"] == 2
    assert "postprocess" not in payload
    monkeypatch.setenv("HMP_WORKSPACE", str(tmp_path))
    cfg = HydroModPyConfig.from_toml(example_config)
    assert list(cfg.simulation.process[0].solvers) == ["modflow6"]
    assert cfg.mesh.triangle.path == example_config.parent / "mesh" / "mesh_catchment.msh"


def test_simulation_regression_mf6_generated_mesh_config_asks_for_voronoi_cells(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    example_config = simulation_regression_fixture("run_fast_mf6_mesh_catchment.toml")

    payload = load_toml_with_base_config(example_config, root=ROOT_CONFIG)

    assert payload["mesh"]["engine"] == "voronoi"
    assert "mesh_catchment" not in payload
    assert payload["simulation"]["name"] == "example12_fast_mf6_mesh_catchment"
    assert payload["simulation"]["process"][0]["solvers"] == ["modflow6"]
    assert payload["simulation"]["process"][1]["solvers"] == ["modflow6"]
    assert payload["simulation"]["time"]["step_value"] == "10 day"
    assert payload["flow"]["first_period_steady"] is False
    assert payload["flow"]["ic"]["kind"] == "top"
    assert payload["flow"]["param"]["K"]["field"]["value"] == "1e-5 m/s"
    assert payload["flow"]["param"]["Sy"]["field"]["value"] == "0.12 -"
    assert payload["data"]["recharge"]["sources"][0]["freq"] == "10D"
    assert "postprocess" not in payload
    assert "analysis" not in payload

    monkeypatch.setenv("HMP_WORKSPACE", str(tmp_path))
    cfg = HydroModPyConfig.from_toml(example_config)
    assert cfg.mesh.engine == "voronoi"
    assert cfg.mesh.families.rivers == "cell"
    assert cfg.mesh.families.geology == "face"
    assert cfg.flow.first_period_steady is False


def test_data_overview_example_declares_overview_workflow_and_report_section() -> None:
    example_config = example_project_config("04_data_overview", "project.toml")

    cfg = HydroModPyConfig.from_toml(example_config)

    assert cfg.workflow.mode == "overview"
    assert cfg.overview is not None
    assert cfg.overview.date_start == "2019-01-01"
    assert cfg.overview.date_end == "2025-12-31"
    assert all(cfg.overview.panels.model_dump().values())


# Relative paths of every file of a project are read from the project root.


def test_the_base_is_the_folder_of_project_toml_above_the_file(tmp_path: Path) -> None:
    (tmp_path / "project.toml").write_text("[workspace]\n", encoding="utf-8")
    case = tmp_path / "plan" / "abc123" / "nancon-base.toml"
    case.parent.mkdir(parents=True)
    case.write_text("[workspace]\n", encoding="utf-8")

    assert config_base_dir(case) == tmp_path
    assert config_base_dir(tmp_path / "project.toml") == tmp_path


def test_outside_a_project_the_base_is_the_folder_of_the_root_of_the_chain(tmp_path: Path) -> None:
    (tmp_path / "base.toml").write_text("[workspace]\n", encoding="utf-8")
    child = tmp_path / "sub" / "child.toml"
    child.parent.mkdir()
    child.write_text('base_config = "../base.toml"\n', encoding="utf-8")
    alone = tmp_path / "sub" / "alone.toml"
    alone.write_text("[workspace]\n", encoding="utf-8")

    assert config_base_dir(child) == tmp_path
    assert config_base_dir(alone) == tmp_path / "sub"


def test_the_chain_is_read_root_first_with_the_own_keys_of_each_file(tmp_path: Path) -> None:
    (tmp_path / "base.toml").write_text('[flow]\nflow_regime = "steady"\n', encoding="utf-8")
    (tmp_path / "mid.toml").write_text(
        'base_config = "base.toml"\n[flow]\nparam_list = ["K"]\n', encoding="utf-8"
    )
    leaf = tmp_path / "leaf.toml"
    leaf.write_text(
        'base_config = "mid.toml"\n[flow]\nflow_regime = "transient"\n', encoding="utf-8"
    )

    chain = read_toml_chain(leaf, root=None)

    assert [item.path.name for item in chain] == ["base.toml", "mid.toml", "leaf.toml"]
    assert chain[1].own == {"flow": {"param_list": ["K"]}}
    assert "base_config" not in chain[2].own
    assert load_toml_with_base_config(leaf, root=None) == {
        "flow": {"flow_regime": "transient", "param_list": ["K"]}
    }


def test_a_cycle_is_refused(tmp_path: Path) -> None:
    (tmp_path / "a.toml").write_text('base_config = "b.toml"\n', encoding="utf-8")
    (tmp_path / "b.toml").write_text('base_config = "a.toml"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="circular base_config chain"):
        read_toml_chain(tmp_path / "a.toml", root=None)


def test_a_file_in_a_sub_folder_of_a_project_reads_its_paths_from_the_root(tmp_path: Path) -> None:
    from hydromodpy.config import HydroModPyConfig

    (tmp_path / "project.toml").write_text("[workspace]\n", encoding="utf-8")
    (tmp_path / "data").mkdir()
    sub = tmp_path / "configs_of_runs" / "run.toml"
    sub.parent.mkdir()
    sub.write_text(
        '[workspace]\ndata_dir = "data"\n\n[geographic]\nsource_mode = "synthetic"\n\n'
        '[simulation]\nname = "x"\n\n[[simulation.process]]\nid = "flow_main"\n'
        'kind = "flow"\nsolvers = ["modflow6"]\n\n[flow]\nflow_regime = "steady"\n',
        encoding="utf-8",
    )

    cfg = HydroModPyConfig.from_toml(sub)

    assert Path(cfg.workspace.data_dir) == tmp_path / "data"
    assert Path(cfg.workspace.project_root) == tmp_path


def test_a_sealed_file_reads_its_paths_from_the_project(tmp_path: Path) -> None:
    """A sealed file writes them from the project root, wherever the run sits."""
    flat = tmp_path / "flat" / "runs" / "first"
    copy = tmp_path / "elsewhere" / "base"
    for folder in (flat, copy):
        folder.mkdir(parents=True)
        (folder / "config.toml").write_text("", encoding="utf-8")
        (folder / "manifest.json").write_text("{}", encoding="utf-8")

    assert config_base_dir(flat / "config.toml") == (tmp_path / "flat").resolve()
    # A copy outside its project reads from its own folder; a caller names the
    # project by argument (-w, --base, base=).
    assert config_base_dir(copy / "config.toml") == copy.resolve()


def test_load_toml_with_base_config_rejects_cycles(tmp_path: Path) -> None:
    first_path = tmp_path / "first.toml"
    second_path = tmp_path / "second.toml"

    first_path.write_text('base_config = "second.toml"\n', encoding="utf-8")
    second_path.write_text('base_config = "first.toml"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="circular base_config chain"):
        load_toml_with_base_config(first_path, root=None)


def test_from_toml_refuses_workspace_project_root(tmp_path: Path) -> None:
    path = tmp_path / "project.toml"
    path.write_text(
        '[workflow]\nmode = "simulation"\n[workspace]\nproject_root = "."\n',
        encoding="utf-8",
    )

    with pytest.raises(
        ConfigValidationError, match=r"\[workspace\] project_root is not a key of a file"
    ):
        HydroModPyConfig.from_toml(path)


def test_from_toml_rejects_scalar_workflow(tmp_path: Path) -> None:
    path = tmp_path / "scalar_workflow.toml"
    path.write_text(
        "\n".join(
            [
                'workflow = "simulation"',
                "",
                "[workspace]",
                "",
                "[geographic]",
                'source_mode = "synthetic"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigValidationError, match=r"\[workflow\]"):
        HydroModPyConfig.from_toml(path)


def test_workspace_rejects_filename_safe_windows_path_tokens(tmp_path: Path) -> None:
    drive_token = chr(0xF03A)
    separator_token = chr(0xF05C)
    encoded_path = (
        f"C{drive_token}{separator_token}codes{separator_token}HydroModPy{separator_token}outputs"
    )

    with pytest.raises(ConfigValidationError, match="encoded as a safe filename"):
        HydroModPyConfig.from_dict(
            {
                "workflow": {"mode": "simulation"},
                "workspace": {"root": encoded_path},
                "geographic": {"source_mode": "synthetic"},
            },
            base_dir=tmp_path,
        )


def test_hydromodpy_config_rejects_unknown_flow_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "unknown_flow.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "simulation"',
                "[workspace]",
                f'root = "{tmp_path}"',
                "",
                "[geographic]",
                'source_mode = "synthetic"',
                "",
                "[flow]",
                "typo_runtime = true",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigValidationError, match=r"Unknown TOML key\(s\) in \[flow\]"):
        HydroModPyConfig.from_toml(config_path)


def test_hydromodpy_config_rejects_unknown_workflow(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError, match="unknown-workflow"):
        HydroModPyConfig.from_dict(
            {
                "workflow": {"mode": "unknown-workflow"},
                "workspace": {"root": str(tmp_path)},
                "geographic": {"source_mode": "synthetic"},
            },
            base_dir=tmp_path,
        )
