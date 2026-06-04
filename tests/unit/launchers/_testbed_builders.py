from __future__ import annotations

from pathlib import Path


def _write_mesh_base(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "mesh"',
                "",
                "[workspace]",
                'project_root = "mesh_outputs/base"',
                "",
                "[simulation]",
                'name = "mesh_base"',
                "",
                "[[simulation.process]]",
                'id = "mesh_main"',
                'type = "mesh"',
                'backend = "catchment"',
                "",
                "[mesh_catchment]",
                'constraints_mode = "rivers_only"',
                "",
                "[mesh_catchment.zone_meshing]",
                "global_size = 200.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_flow_base(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "simulation"',
                "",
                "[workspace]",
                'project_root = "flow_outputs/base"',
                "",
                "[simulation]",
                'name = "flow_base"',
                "",
                "[[simulation.process]]",
                'id = "flow_main"',
                'type = "flow"',
                'solvers = ["modflow6"]',
                "",
                "[flow]",
                'flow_regime = "steady"',
                'param_list = ["K"]',
                "",
                "[flow.param.K.field]",
                'kind = "homogeneous"',
                'unit = "m/s"',
                'value = "1e-5 m/s"',
                "",
                "[display]",
                "enabled = false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_comparison_base(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "comparison"',
                "",
                "[comparison]",
                'comparison_id = "comparison_base"',
                'output_root = "comparison_outputs/base"',
                "",
                "[[comparison.simulation]]",
                'id = "reference"',
                'run_folder = "runs/reference"',
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


def _write_calibration_base(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "calibration"',
                "",
                "[calibration]",
                'campaign_id = "calibration_base"',
                'output_root = "calibration_outputs/base"',
                'objective = "nse"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
