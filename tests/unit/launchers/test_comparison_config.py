from __future__ import annotations

from pathlib import Path

from hydromodpy.analysis.comparison.child_materialization import (
    materialize_child_configs,
)
from hydromodpy.analysis.comparison.config import RuntimeComparisonConfig
from hydromodpy.analysis.comparison.experiment_config import SimulationComparisonConfig
from hydromodpy.core.toml_io.loader import load_toml_with_base_config

from ._comparison_builders import (
    _write_base_simulation_config,
    _write_comparison_anchors,
    _write_simulation_comparison_config,
)


def test_comparison_config_resolves_paths(tmp_path: Path) -> None:
    run_folder = tmp_path / "runs" / "mf6_demo"
    config_path = tmp_path / "config_comparison.toml"
    _write_simulation_comparison_config(config_path, run_folder)

    cfg = RuntimeComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    assert cfg.comparison_root == (tmp_path / "comparison_outputs").resolve()
    assert cfg.comparison.comparison_id == "demo_compare"
    assert cfg.resolve_simulation_run_folder(cfg.comparison.simulation[0]) == run_folder.resolve()
    assert cfg.comparison.observable[1].reducer == "sum"


def test_comparison_config_normalizes_legacy_human_mesh_label(tmp_path: Path) -> None:
    config_path = tmp_path / "config_comparison.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "comparison"',
                "",
                "[comparison]",
                'comparison_id = "demo_compare"',
                'output_root = "comparison_outputs"',
                "",
                "[[comparison.simulation]]",
                'id = "mf6_demo"',
                'run_folder = "run"',
                'mesh_label = "Generated geology-river catchment mesh"',
                "",
                "[[comparison.observable]]",
                'name = "head"',
                'variable = "head"',
                'support = "point"',
                "cell_index = 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cfg = SimulationComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    assert cfg.comparison.simulation[0].mesh_label == "generated_geology_river_catchment_mesh"


def test_comparison_config_applies_anchor_file(tmp_path: Path) -> None:
    anchors_path = tmp_path / "comparison_points.toml"
    _write_comparison_anchors(anchors_path)
    config_path = tmp_path / "config_comparison.toml"
    config_path.write_text(
        "\n".join(
            [
                "[comparison]",
                'comparison_id = "demo_anchor_compare"',
                'anchors_file = "comparison_points.toml"',
                "[comparison.execution]",
                "run_simulations = false",
                "",
                "[[comparison.simulation]]",
                'id = "mf6_demo"',
                'run_folder = "run"',
                "",
                "[[comparison.observable]]",
                'name = "head_at_anchor"',
                'variable = "watertable_elevation"',
                'support = "point"',
                'anchor_id = "demo.reference"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cfg = RuntimeComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    observable = cfg.comparison.observable[0]
    assert observable.anchor_id == "demo.reference"
    assert observable.x == 10.0
    assert observable.y == 0.0


def test_comparison_config_accepts_canonical_anchor_file(tmp_path: Path) -> None:
    anchors_path = tmp_path / "comparison_points.toml"
    anchors_path.write_text(
        "\n".join(
            [
                "[comparison_anchors.demo.reference]",
                "x = 11.0",
                "y = 1.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "config_comparison.toml"
    config_path.write_text(
        "\n".join(
            [
                "[comparison]",
                'comparison_id = "demo_anchor_compare"',
                'anchors_file = "comparison_points.toml"',
                "[comparison.execution]",
                "run_simulations = false",
                "",
                "[[comparison.simulation]]",
                'id = "mf6_demo"',
                'run_folder = "run"',
                "",
                "[[comparison.observable]]",
                'name = "head_at_anchor"',
                'variable = "watertable_elevation"',
                'support = "point"',
                'anchor_id = "demo.reference"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cfg = RuntimeComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    assert cfg.comparison is cfg.comparison
    assert cfg.comparison.observable[0].x == 11.0
    assert cfg.comparison.observable[0].y == 1.0


def test_materialize_simulation_config_writes_base_overlay(tmp_path: Path) -> None:
    base_config = tmp_path / "run_flow_common.toml"
    _write_base_simulation_config(base_config)
    config_path = tmp_path / "config_comparison.toml"
    config_path.write_text(
        "\n".join(
            [
                "[comparison]",
                'comparison_id = "demo_compare"',
                'base_simulation_config = "run_flow_common.toml"',
                "[comparison.execution]",
                "run_simulations = false",
                "",
                "[[comparison.simulation]]",
                'id = "bouss_demo"',
                'solver = "boussinesq"',
                "",
                "[comparison.simulation.overlay.mesh_input]",
                'bundle_dir = "mesh/bundle"',
                "",
                "[[comparison.observable]]",
                'name = "head_cell"',
                'variable = "watertable_elevation"',
                'support = "point"',
                "cell_index = 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    cfg = SimulationComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    generated = materialize_child_configs(cfg)[0].config_path

    assert generated is not None
    raw = load_toml_with_base_config(generated)
    assert raw["simulation"]["name"] == "demo_compare__bouss_demo"
    assert raw["simulation"]["process"][0]["solvers"] == ["boussinesq"]
    assert raw["mesh_input"]["bundle_dir"] == (tmp_path / "mesh" / "bundle").resolve().as_posix()


def test_materialize_simulation_config_applies_shared_base_overlay_and_default_workspace(
    tmp_path: Path,
) -> None:
    base_config = tmp_path / "run_flow_common.toml"
    _write_base_simulation_config(base_config)
    config_path = tmp_path / "config_comparison.toml"
    config_path.write_text(
        "\n".join(
            [
                "[comparison]",
                'comparison_id = "site_01_compare"',
                'base_simulation_config = "run_flow_common.toml"',
                'output_root = "comparison_outputs/site_01"',
                "[comparison.base_simulation_overlay.geographic.catchment]",
                "x_outlet = 131189.1",
                "y_outlet = 6833784.4",
                "",
                "[comparison.base_simulation_overlay.geographic]",
                "target_area_km2 = 10.0",
                "",
                "[comparison.base_simulation_overlay.flow.param.K.field_homogeneous]",
                'value = "2e-5 m/s"',
                "",
                "[comparison.execution]",
                "run_simulations = false",
                "",
                "[[comparison.simulation]]",
                'id = "mf6_demo"',
                'solver = "modflow6"',
                "",
                "[[comparison.observable]]",
                'name = "head_cell"',
                'variable = "watertable_elevation"',
                'support = "point"',
                "cell_index = 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    cfg = SimulationComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    generated = materialize_child_configs(cfg)[0].config_path

    assert generated is not None
    generated_text = generated.read_text(encoding="utf-8")
    assert "# Human-readable simulation name and the run's identity." in generated_text
    assert "# X coordinate of the watershed outlet" in generated_text
    raw = load_toml_with_base_config(generated)
    assert raw["simulation"]["name"] == "site_01_compare__mf6_demo"
    assert raw["geographic"]["catchment"]["x_outlet"] == 131189.1
    assert raw["geographic"]["target_area_km2"] == 10.0
    assert raw["flow"]["param"]["K"]["field_homogeneous"]["value"] == "2e-5 m/s"
    assert raw["workspace"]["root"].endswith("comparison_outputs/site_01/workspaces/mf6_demo")
    assert raw["workspace"]["project_root"] == raw["workspace"]["root"]
