from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.analysis.comparison.experiment_launcher import (
    SimulationComparisonLauncher,
)

from ._comparison_builders import (
    _FakeCatalog,
    _patch_result_store,
    _write_fake_run_folder,
    _write_native_timeseries_csv,
    _write_simulation_comparison_config,
    _write_solver_grid_template,
    _write_structured_solver_config,
    _write_visual_simulation_comparison_config,
)


def test_simulation_comparison_launcher_reuses_existing_run_folder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_folder = tmp_path / "run"
    bundle_dir = tmp_path / "bundle"
    store = _write_fake_run_folder(run_folder, bundle_dir)
    config_path = tmp_path / "config_comparison.toml"
    _write_simulation_comparison_config(config_path, run_folder)
    _patch_result_store(monkeypatch, {config_path.resolve(): store})

    summary = SimulationComparisonLauncher(config_path).run()

    manifest_path = Path(summary["manifest_path"])
    observables_csv = Path(summary["observables_csv"])
    assert manifest_path.exists()
    assert observables_csv.exists()
    assert summary["n_observable_rows"] == 2
    with observables_csv.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["observable"] for row in rows} == {
        "head_at_point",
        "outlet_flux",
    }
    assert Path(summary["comparison_metrics_csv"]).exists()
    assert Path(summary["comparison_differences_csv"]).exists()
    assert Path(summary["comparison_report_md"]).exists()


def test_simulation_comparison_launcher_generates_visual_figures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference_run = tmp_path / "reference_run"
    candidate_run = tmp_path / "candidate_run"
    reference_bundle = tmp_path / "reference_bundle"
    candidate_bundle = tmp_path / "candidate_bundle"
    reference_store = _write_fake_run_folder(reference_run, reference_bundle)
    candidate_store = _write_fake_run_folder(
        candidate_run,
        candidate_bundle,
        head_offset=1.5,
        accumulation_offset=0.2,
    )

    reference_solver_config = tmp_path / "run_reference_solver.toml"
    candidate_solver_config = tmp_path / "run_candidate_solver.toml"
    _write_structured_solver_config(
        reference_solver_config,
        solver="modflow6",
        nx=3,
        ny=1,
    )
    _write_structured_solver_config(
        candidate_solver_config,
        solver="modflownwt",
        nx=3,
        ny=1,
    )

    config_path = tmp_path / "config_comparison_visuals.toml"
    _write_visual_simulation_comparison_config(
        config_path,
        reference_run_folder=reference_run,
        candidate_run_folder=candidate_run,
        reference_config_path=reference_solver_config,
        candidate_config_path=candidate_solver_config,
    )
    _patch_result_store(
        monkeypatch,
        {
            reference_solver_config.resolve(): reference_store,
            candidate_solver_config.resolve(): candidate_store,
        },
    )

    summary = SimulationComparisonLauncher(config_path).run()

    figures = summary["comparison_figures"]
    assert summary["comparison_figures_dir"]
    assert {item["kind"] for item in figures} == {
        "case_configuration",
        "timeseries",
        "simulated_active_network_figures_skipped_json",
    }
    for item in figures:
        figure_path = Path(item["path"])
        assert figure_path.exists()
        assert figure_path.stat().st_size > 0

    report_text = Path(summary["comparison_report_md"]).read_text(encoding="utf-8")
    assert "## Figures" in report_text
    assert "head_map" in report_text
    assert "outlet_flux_series" in report_text


def test_simulation_comparison_launcher_writes_chronicles_native_flux_and_runtime_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference_run = tmp_path / "reference_run"
    candidate_run = tmp_path / "candidate_run"
    reference_bundle = tmp_path / "reference_bundle"
    candidate_bundle = tmp_path / "candidate_bundle"
    reference_store = _write_fake_run_folder(reference_run, reference_bundle)
    candidate_store = _write_fake_run_folder(
        candidate_run,
        candidate_bundle,
        head_offset=1.5,
        accumulation_offset=0.2,
    )
    _write_native_timeseries_csv(
        reference_run,
        accumulation_values=[0.1, 0.2, 0.3],
        drain_values=[0.05, 0.08, 0.09],
    )
    _write_native_timeseries_csv(
        candidate_run,
        accumulation_values=[0.12, 0.18, 0.31],
        drain_values=[0.04, 0.09, 0.11],
    )
    (reference_run / "_metrics.json").write_text(
        json.dumps(
            {
                "mesh_output_exchange_bundle_dir": str(reference_bundle),
                "wall_time_seconds": 12.5,
                "flow_solve_time_seconds": 3.5,
                "solvers": ["modflow6"],
                "success": True,
            }
        ),
        encoding="utf-8",
    )
    (candidate_run / "_metrics.json").write_text(
        json.dumps(
            {
                "mesh_output_exchange_bundle_dir": str(candidate_bundle),
                "wall_time_seconds": 25.0,
                "flow_solve_time_seconds": 4.5,
                "solvers": ["modflow_nwt"],
                "success": True,
            }
        ),
        encoding="utf-8",
    )

    reference_solver_config = tmp_path / "run_reference_solver.toml"
    candidate_solver_config = tmp_path / "run_candidate_solver.toml"
    _write_structured_solver_config(reference_solver_config, solver="modflow6", nx=3, ny=1)
    _write_structured_solver_config(candidate_solver_config, solver="modflownwt", nx=3, ny=1)

    config_path = tmp_path / "config_comparison_outputs.toml"
    _write_visual_simulation_comparison_config(
        config_path,
        reference_run_folder=reference_run,
        candidate_run_folder=candidate_run,
        reference_config_path=reference_solver_config,
        candidate_config_path=candidate_solver_config,
    )
    _patch_result_store(
        monkeypatch,
        {
            reference_solver_config.resolve(): reference_store,
            candidate_solver_config.resolve(): candidate_store,
        },
    )

    summary = SimulationComparisonLauncher(config_path).run()

    artifact_kinds = {item["kind"] for item in summary["comparison_data_artifacts"]}
    assert "timeseries_long_csv" in artifact_kinds
    assert "native_timeseries_long_csv" in artifact_kinds
    assert "execution_times_csv" in artifact_kinds

    figure_kinds = {item["kind"] for item in summary["comparison_figures"]}
    assert "native_flux_panel" not in figure_kinds
    assert "execution_time_bars" not in figure_kinds
    assert "point_dashboard" not in figure_kinds


def test_simulation_comparison_launcher_generates_structured_figures_from_run_folder_template(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference_run = tmp_path / "reference_structured_run"
    candidate_run = tmp_path / "candidate_structured_run"
    reference_store = _FakeCatalog(
        reference_run / "simulation.zarr",
        {
            "watertable_elevation": np.asarray(
                [[10.0, 20.0, 30.0, 40.0], [11.0, 21.0, 31.0, 41.0]],
                dtype=float,
            )
        },
    )
    candidate_store = _FakeCatalog(
        candidate_run / "simulation.zarr",
        {
            "watertable_elevation": np.asarray(
                [[10.5, 20.5, 30.5, 40.5], [11.5, 21.5, 31.5, 41.5]],
                dtype=float,
            )
        },
    )
    reference_run.mkdir(parents=True, exist_ok=True)
    candidate_run.mkdir(parents=True, exist_ok=True)
    _write_solver_grid_template(reference_run, nx=2, ny=2)
    _write_solver_grid_template(candidate_run, nx=2, ny=2)
    reference_solver_config = tmp_path / "structured_reference.toml"
    candidate_solver_config = tmp_path / "structured_candidate.toml"
    _write_structured_solver_config(reference_solver_config, solver="modflow6", nx=2, ny=2)
    _write_structured_solver_config(candidate_solver_config, solver="modflownwt", nx=2, ny=2)

    config_path = tmp_path / "config_comparison_structured_reuse.toml"
    config_path.write_text(
        "\n".join(
            [
                "[comparison]",
                'comparison_id = "demo_structured_reuse_visuals"',
                'output_root = "comparison_outputs"',
                'reference_simulation = "mf6_demo"',
                "[comparison.execution]",
                "run_simulations = false",
                "",
                "[comparison.audit]",
                'on_mismatch = "warn"',
                "",
                "[[comparison.simulation]]",
                'id = "mf6_demo"',
                'label = "MF6 reference"',
                'solver = "modflow6"',
                'mesh_mode = "structured"',
                f'run_folder = "{reference_run.as_posix()}"',
                f'simulation_config = "{reference_solver_config.as_posix()}"',
                "",
                "[[comparison.simulation]]",
                'id = "nwt_demo"',
                'label = "NWT candidate"',
                'solver = "modflownwt"',
                'mesh_mode = "structured"',
                f'run_folder = "{candidate_run.as_posix()}"',
                f'simulation_config = "{candidate_solver_config.as_posix()}"',
                "",
                "[[comparison.observable]]",
                'name = "head_map_last"',
                'variable = "watertable_elevation"',
                'support = "map"',
                'time = "last"',
                'unit = "m"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    _patch_result_store(
        monkeypatch,
        {
            reference_solver_config.resolve(): reference_store,
            candidate_solver_config.resolve(): candidate_store,
        },
    )

    summary = SimulationComparisonLauncher(config_path).run()

    figures = summary["comparison_figures"]
    assert {item["kind"] for item in figures} == {
        "case_configuration",
        "simulated_active_network_figures_skipped_json",
    }
    for item in figures:
        figure_path = Path(item["path"])
        assert figure_path.exists()
        assert figure_path.stat().st_size > 0
