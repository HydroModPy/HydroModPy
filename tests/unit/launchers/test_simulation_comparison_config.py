from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.analysis.comparison.child_materialization import (
    materialize_child_configs,
)
from hydromodpy.analysis.comparison.experiment_config import SimulationComparisonConfig
from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from tests.unit.launchers._simulation_comparison_builders import (
    _load_comparison_cfg,
    _write_base_simulation_config,
    _write_comparison_config,
)


def test_simulation_comparison_materializes_child_tomls(tmp_path: Path) -> None:
    _write_base_simulation_config(tmp_path / "base.toml")
    config_path = tmp_path / "compare.toml"
    _write_comparison_config(config_path)

    cfg = _load_comparison_cfg(config_path)
    children = materialize_child_configs(cfg)

    assert [child.simulation_id for child in children] == ["mf6_ref", "bouss_candidate"]
    mf6_raw = load_toml_with_base_config(children[0].config_path)
    bouss_raw = load_toml_with_base_config(children[1].config_path)
    assert mf6_raw["workflow"] == {"mode": "simulation"}
    assert mf6_raw["simulation"]["name"] == "demo_sim_compare__mf6_ref"
    assert mf6_raw["simulation"]["process"][0]["solvers"] == ["modflow6"]
    assert bouss_raw["simulation"]["run_id"] == "demo_sim_compare__bouss_candidate"
    assert bouss_raw["simulation"]["process"][0]["solvers"] == ["boussinesq"]


def test_simulation_comparison_generated_child_run_folder_uses_workspace_root(
    tmp_path: Path,
) -> None:
    _write_base_simulation_config(tmp_path / "base.toml")
    config_path = tmp_path / "compare_workspace.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "comparison"',
                "",
                "[comparison]",
                'comparison_id = "demo_workspace_root"',
                'base_simulation_config = "base.toml"',
                "",
                "[[comparison.simulation]]",
                'id = "mf6_ref"',
                'solver = "modflow6"',
                "",
                "[comparison.simulation.overlay.workspace]",
                'root = "runs/mf6"',
                "",
                "[[comparison.observable]]",
                'name = "head_mid"',
                'variable = "watertable_elevation"',
                'support = "point"',
                "cell_index = 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cfg = _load_comparison_cfg(config_path)
    children = materialize_child_configs(cfg)

    assert children[0].run_folder == (tmp_path / "runs" / "mf6").resolve()


def test_simulation_comparison_accepts_existing_run_folders_without_base_config(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "compare_existing.toml"
    run_a = tmp_path / "runs" / "mf6"
    run_b = tmp_path / "runs" / "bouss"
    run_a.mkdir(parents=True)
    run_b.mkdir(parents=True)
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "comparison"',
                "",
                "[comparison]",
                'comparison_id = "existing_runs"',
                'reference_simulation = "mf6_ref"',
                "",
                "[comparison.execution]",
                "run_simulations = false",
                "",
                "[[comparison.simulation]]",
                'id = "mf6_ref"',
                'label = "MF6 existing"',
                'solver = "modflow6"',
                'run_folder = "runs/mf6"',
                "",
                "[[comparison.simulation]]",
                'id = "bouss_candidate"',
                'label = "Boussinesq existing"',
                'solver = "boussinesq"',
                'run_folder = "runs/bouss"',
                "",
                "[[comparison.observable]]",
                'name = "head_mid"',
                'variable = "watertable_elevation"',
                'support = "point"',
                "cell_index = 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cfg = _load_comparison_cfg(config_path)
    children = materialize_child_configs(cfg)

    assert cfg.base_simulation_config_path is None
    assert [child.config_path for child in children] == [None, None]
    assert [child.run_folder for child in children] == [
        run_a.resolve(),
        run_b.resolve(),
    ]
    assert not (tmp_path / "comparison" / "existing_runs" / "_generated_configs").exists()


def test_simulation_comparison_rejects_physical_overlay_changes(tmp_path: Path) -> None:
    _write_base_simulation_config(tmp_path / "base.toml")
    config_path = tmp_path / "compare.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "comparison"',
                "",
                "[comparison]",
                'base_simulation_config = "base.toml"',
                "",
                "[[comparison.simulation]]",
                'id = "mf6_ref"',
                'solver = "modflow6"',
                "",
                "[comparison.simulation.overlay.domain]",
                "anything = 1",
                "",
                "[[comparison.observable]]",
                'name = "head_mid"',
                'variable = "watertable_elevation"',
                'support = "point"',
                "cell_index = 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cfg = _load_comparison_cfg(config_path)
    with pytest.raises(ValueError, match="forbidden sections: domain"):
        materialize_child_configs(cfg)


@pytest.mark.parametrize(
    ("sim_id", "overlay_lines", "raw_path", "expected_value"),
    [
        pytest.param(
            "k_mid",
            [
                "[comparison.simulation.overlay.flow.param.K.field]",
                'value = "2e-4 m/s"',
            ],
            ("flow", "param", "K", "field", "value"),
            "2e-4 m/s",
            id="test_simulation_comparison_allows_flow_parameter_sweep_overlay",
        ),
        pytest.param(
            "drainage_high",
            [
                "[comparison.simulation.overlay.flow.bc.cauchy.drainage]",
                'value = "3e-3 m2/s"',
            ],
            ("flow", "bc", "cauchy", "drainage", "value"),
            "3e-3 m2/s",
            id="test_simulation_comparison_allows_flow_boundary_sweep_overlay",
        ),
        pytest.param(
            "steady_ic",
            [
                "[comparison.simulation.overlay.flow.ic]",
                'type = "steady_state"',
            ],
            ("flow", "ic", "type"),
            "steady_state",
            id="test_simulation_comparison_allows_flow_initial_condition_overlay",
        ),
    ],
)
def test_simulation_comparison_allows_flow_overlay(
    tmp_path: Path,
    sim_id: str,
    overlay_lines: list[str],
    raw_path: tuple[str, ...],
    expected_value: str,
) -> None:
    _write_base_simulation_config(tmp_path / "base.toml")
    config_path = tmp_path / "compare.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "comparison"',
                "",
                "[comparison]",
                'base_simulation_config = "base.toml"',
                "",
                "[[comparison.simulation]]",
                f'id = "{sim_id}"',
                'solver = "modflow6"',
                "",
                *overlay_lines,
                "",
                "[[comparison.observable]]",
                'name = "head_mid"',
                'variable = "watertable_elevation"',
                'support = "point"',
                "cell_index = 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cfg = _load_comparison_cfg(config_path)
    children = materialize_child_configs(cfg)
    raw = load_toml_with_base_config(children[0].config_path)

    value: object = raw
    for key in raw_path:
        value = value[key]  # type: ignore[index]
    assert value == expected_value


def test_simulation_comparison_requires_existing_base_config(tmp_path: Path) -> None:
    config_path = tmp_path / "compare.toml"
    _write_comparison_config(config_path)

    with pytest.raises(FileNotFoundError, match="comparison.base_simulation_config not found"):
        _load_comparison_cfg(config_path)


def test_simulation_comparison_requires_enabled_reference(tmp_path: Path) -> None:
    _write_base_simulation_config(tmp_path / "base.toml")
    config_path = tmp_path / "compare.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "comparison"',
                "",
                "[comparison]",
                'base_simulation_config = "base.toml"',
                'reference_simulation = "mf6_ref"',
                "",
                "[[comparison.simulation]]",
                'id = "mf6_ref"',
                'solver = "modflow6"',
                "enabled = false",
                "",
                "[[comparison.simulation]]",
                'id = "bouss_candidate"',
                'solver = "boussinesq"',
                "",
                "[[comparison.observable]]",
                'name = "head_mid"',
                'variable = "watertable_elevation"',
                'support = "point"',
                "cell_index = 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="reference_simulation must match an enabled"):
        _load_comparison_cfg(config_path)


def test_simulation_comparison_rejects_unknown_observable_simulation(
    tmp_path: Path,
) -> None:
    _write_base_simulation_config(tmp_path / "base.toml")
    config_path = tmp_path / "compare.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "comparison"',
                "",
                "[comparison]",
                'base_simulation_config = "base.toml"',
                "",
                "[[comparison.simulation]]",
                'id = "mf6_ref"',
                'solver = "modflow6"',
                "",
                "[[comparison.observable]]",
                'name = "head_mid"',
                'variable = "watertable_elevation"',
                'simulations = ["missing_candidate"]',
                'support = "point"',
                "cell_index = 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown or disabled ids: missing_candidate"):
        _load_comparison_cfg(config_path)


def test_simulation_comparison_rejects_path_like_comparison_id(tmp_path: Path) -> None:
    _write_base_simulation_config(tmp_path / "base.toml")
    config_path = tmp_path / "compare.toml"
    _write_comparison_config(config_path)
    raw = load_toml_with_base_config(config_path)
    raw["comparison"]["comparison_id"] = "bad/name"

    with pytest.raises(ValueError, match="String should match pattern"):
        SimulationComparisonConfig.from_toml(raw, config_path=config_path)
