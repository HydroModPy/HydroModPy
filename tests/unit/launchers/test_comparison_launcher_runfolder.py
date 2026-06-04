from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.analysis.comparison.child_materialization import (
    materialize_child_configs,
)
from hydromodpy.analysis.comparison.experiment_launcher import (
    SimulationComparisonLauncher,
)
from hydromodpy.analysis.comparison.run_backend import ChildRunResult

from ._comparison_builders import SIM_ID


def test_simulation_comparison_launcher_infers_completed_run_folder_from_declared_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scratch = tmp_path / "solver_scratch"
    simulation_config = tmp_path / "run_solver.toml"
    simulation_config.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "simulation"',
                "[workspace]",
                'project_root = "project/demo"',
                f'solver_scratch_folder = "{scratch.as_posix()}"',
                "",
                "[simulation]",
                'run_id = "demo_run"',
                "",
                "[[simulation.process]]",
                'id = "flow_main"',
                'type = "flow"',
                'solvers = ["boussinesq"]',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    actual_run_folder = scratch / "demo_run" / "flow_main__boussinesq"
    actual_run_folder.mkdir(parents=True, exist_ok=True)
    (actual_run_folder / "_metrics.json").write_text("{}", encoding="utf-8")
    comparison_config = tmp_path / "config_comparison.toml"
    comparison_config.write_text(
        "\n".join(
            [
                "[comparison]",
                'comparison_id = "demo_compare"',
                "[comparison.execution]",
                "run_simulations = true",
                "",
                "[[comparison.simulation]]",
                'id = "bouss_demo"',
                'solver = "boussinesq"',
                f'simulation_config = "{simulation_config.as_posix()}"',
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

    import hydromodpy.analysis.comparison.experiment_launcher as launcher_module

    class _RootConfigProvider:
        def from_toml(self, _config_path: Path):
            return SimpleNamespace(
                workspace=SimpleNamespace(solver_scratch_folder=scratch),
                simulation=SimpleNamespace(run_id="demo_run"),
            )

    monkeypatch.setattr(
        launcher_module,
        "get_root_config_provider",
        lambda: _RootConfigProvider(),
    )

    launcher = SimulationComparisonLauncher(comparison_config)
    child = materialize_child_configs(launcher.cfg)[0]
    summary = launcher._summary_from_run_result(
        child,
        ChildRunResult(
            config_path=simulation_config,
            returncode=0,
            wall_time_seconds=0.25,
            sim_id=SIM_ID,
            stdout="",
            stderr="",
        ),
    )

    assert summary["status"] == "completed"
    assert Path(summary["run_folder"]) == actual_run_folder.resolve()


def test_simulation_comparison_launcher_reuse_infers_process_output_folder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scratch = tmp_path / "solver_scratch"
    scratch.mkdir(parents=True, exist_ok=True)

    import hydromodpy.analysis.comparison.experiment_launcher as launcher_module

    class _RootConfigProvider:
        def from_toml(self, _config_path: Path):
            return SimpleNamespace(
                workspace=SimpleNamespace(solver_scratch_folder=scratch),
                simulation=SimpleNamespace(run_id="ex12_demo_mod_bouss_tri"),
            )

    monkeypatch.setattr(
        launcher_module,
        "get_root_config_provider",
        lambda: _RootConfigProvider(),
    )

    resolved = SimulationComparisonLauncher._infer_run_folder_from_config(
        tmp_path / "config.toml",
        solver_name="boussinesq",
    )

    assert resolved.name == "ex12_demo_mod_bouss_tri"
