from __future__ import annotations

from pathlib import Path

from hydromodpy.analysis.comparison.experiment_config import SimulationComparisonConfig
from hydromodpy.core.toml_io.loader import load_toml_with_base_config


def _write_base_simulation_config(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "simulation"',
                "",
                "[workspace]",
                'project_root = "."',
                "",
                "[simulation]",
                'run_id = "base_run"',
                "",
                "[[simulation.process]]",
                'id = "flow_main"',
                'type = "flow"',
                'solvers = ["modflow6"]',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_comparison_config(
    path: Path,
    *,
    output_root: str = "comparison_outputs",
    keep_generated_configs: bool = True,
) -> None:
    execution_lines = []
    if not keep_generated_configs:
        execution_lines = [
            "",
            "[comparison.execution]",
            "keep_generated_configs = false",
        ]
    path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "comparison"',
                "",
                "[comparison]",
                'comparison_id = "demo_sim_compare"',
                'base_simulation_config = "base.toml"',
                f'output_root = "{output_root}"',
                'reference_simulation = "mf6_ref"',
                *execution_lines,
                "",
                "[[comparison.simulation]]",
                'id = "mf6_ref"',
                'label = "MF6 reference"',
                'solver = "modflow6"',
                "",
                "[[comparison.simulation]]",
                'id = "bouss_candidate"',
                'label = "Boussinesq candidate"',
                'solver = "boussinesq"',
                "",
                "[[comparison.observable]]",
                'name = "head_mid"',
                'variable = "watertable_elevation"',
                'support = "point"',
                "cell_index = 0",
                'time = "last"',
                'unit = "m"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _load_comparison_cfg(config_path: Path) -> SimulationComparisonConfig:
    return SimulationComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )
