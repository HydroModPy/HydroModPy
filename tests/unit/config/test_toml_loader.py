from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.config.hydromodpy_config import ROOT_CONFIG, HydroModPyConfig
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.core.toml_io.loader import config_base_dir, load_toml_with_base_config

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


# Relative paths of every file of a project are read from the project root.


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
