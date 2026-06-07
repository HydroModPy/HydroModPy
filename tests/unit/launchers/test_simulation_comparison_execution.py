from __future__ import annotations

import json
from pathlib import Path

import pytest

import hydromodpy.analysis.comparison.output_pipeline as output_pipeline_module
from hydromodpy.analysis.comparison.experiment_launcher import (
    SimulationComparisonLauncher,
)
from hydromodpy.analysis.comparison.run_backend import ChildRunResult
from tests.unit.launchers._simulation_comparison_builders import (
    _write_base_simulation_config,
    _write_comparison_config,
)


def test_simulation_comparison_launcher_reuses_existing_run_folders(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import hydromodpy.analysis.comparison.experiment_launcher as launcher_module

    config_path = tmp_path / "compare_existing.toml"
    for run_name in ("mf6", "bouss"):
        (tmp_path / "runs" / run_name).mkdir(parents=True)
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "comparison"',
                "",
                "[comparison]",
                'comparison_id = "existing_runs"',
                'output_root = "comparison_outputs"',
                'reference_simulation = "mf6_ref"',
                "",
                "[comparison.execution]",
                "run_simulations = false",
                "",
                "[[comparison.simulation]]",
                'id = "mf6_ref"',
                'solver = "modflow6"',
                'run_folder = "runs/mf6"',
                "",
                "[[comparison.simulation]]",
                'id = "bouss_candidate"',
                'solver = "boussinesq"',
                'run_folder = "runs/bouss"',
                "",
                "[[comparison.observable]]",
                'name = "head_mid"',
                'variable = "watertable_elevation"',
                'support = "point"',
                "cell_index = 0",
                'time = "last"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_extract_observables(
        self: SimulationComparisonLauncher,
        comparison_cfg,
        simulation_summaries,
    ) -> list[dict[str, object]]:
        assert [summary["config_path"] for summary in simulation_summaries] == [
            None,
            None,
        ]
        assert [Path(str(summary["run_folder"])).name for summary in simulation_summaries] == [
            "mf6",
            "bouss",
        ]
        assert [simulation.id for simulation in comparison_cfg.comparison.simulation] == [
            "mf6_ref",
            "bouss_candidate",
        ]
        return [
            {
                "comparison_id": "existing_runs",
                "simulation_id": "mf6_ref",
                "simulation_label": "mf6_ref",
                "solver": "modflow6",
                "observable": "head_mid",
                "variable": "watertable_elevation",
                "support": "point",
                "time": "last",
                "time_index": 0,
                "comparison_time_key": "time_index:0",
                "value_index": 0,
                "value": 10.0,
                "is_nodata": False,
            },
            {
                "comparison_id": "existing_runs",
                "simulation_id": "bouss_candidate",
                "simulation_label": "bouss_candidate",
                "solver": "boussinesq",
                "observable": "head_mid",
                "variable": "watertable_elevation",
                "support": "point",
                "time": "last",
                "time_index": 0,
                "comparison_time_key": "time_index:0",
                "value_index": 0,
                "value": 11.0,
                "is_nodata": False,
            },
        ]

    monkeypatch.setattr(
        SimulationComparisonLauncher, "_extract_observables", fake_extract_observables
    )
    monkeypatch.setattr(
        launcher_module,
        "build_equivalence_audit",
        lambda **kwargs: {
            "schema_version": "simulation_comparison_audit_v1",
            "status": "pass",
            "reference_simulation": kwargs["reference_simulation"],
            "issues": [],
        },
    )
    monkeypatch.setattr(output_pipeline_module, "generate_comparison_figures", lambda **kwargs: [])

    manifest = SimulationComparisonLauncher(config_path).run()

    assert manifest["base_simulation_config"] is None
    assert manifest["generated_config_paths"] == []
    assert manifest["simulations"][0]["status"] == "reused"
    assert manifest["simulations"][0]["config_path"] is None
    assert manifest["n_observable_rows"] == 2


def test_simulation_comparison_launcher_writes_manifest_with_mocked_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_base_simulation_config(tmp_path / "base.toml")
    config_path = tmp_path / "compare.toml"
    _write_comparison_config(config_path, output_root="comparison_outputs")

    import hydromodpy.analysis.comparison.experiment_launcher as launcher_module

    sim_ids = {
        "mf6_ref": "00000000-0000-0000-0000-000000000001",
        "bouss_candidate": "00000000-0000-0000-0000-000000000002",
    }

    def fake_run_child_with_hmp(
        child_config_path: Path,
        *,
        python_executable: str | None = None,
        timeout_seconds: float | None = None,
    ) -> ChildRunResult:
        del python_executable, timeout_seconds
        simulation_id = child_config_path.stem
        return ChildRunResult(
            config_path=child_config_path,
            returncode=0,
            wall_time_seconds=0.25,
            sim_id=sim_ids[simulation_id],
            stdout="",
            stderr=f"  sim_id: {sim_ids[simulation_id]}\n",
        )

    def fake_extract_observables(
        self: SimulationComparisonLauncher,
        comparison_cfg,
        simulation_summaries: list[dict],
    ) -> list[dict]:
        del self, comparison_cfg, simulation_summaries
        return [
            {
                "comparison_id": "demo_sim_compare",
                "simulation_id": "mf6_ref",
                "simulation_label": "MF6 reference",
                "solver": "modflow6",
                "mesh_mode": "unknown",
                "observable": "head_mid",
                "variable": "watertable_elevation",
                "support": "point",
                "time": "last",
                "time_index": 0,
                "elapsed_seconds": 0.0,
                "comparison_time_key": "time_index:0",
                "match_fallback_key": "time_selector:last",
                "value_index": 0,
                "value": 10.0,
                "is_nodata": False,
                "unit": "m",
                "selection": "declared_cell",
            },
            {
                "comparison_id": "demo_sim_compare",
                "simulation_id": "bouss_candidate",
                "simulation_label": "Boussinesq candidate",
                "solver": "boussinesq",
                "mesh_mode": "unknown",
                "observable": "head_mid",
                "variable": "watertable_elevation",
                "support": "point",
                "time": "last",
                "time_index": 0,
                "elapsed_seconds": 0.0,
                "comparison_time_key": "time_index:0",
                "match_fallback_key": "time_selector:last",
                "value_index": 0,
                "value": 11.0,
                "is_nodata": False,
                "unit": "m",
                "selection": "declared_cell",
            },
        ]

    monkeypatch.setattr(launcher_module, "run_child_with_hmp", fake_run_child_with_hmp)
    monkeypatch.setattr(
        SimulationComparisonLauncher, "_extract_observables", fake_extract_observables
    )
    monkeypatch.setattr(
        launcher_module,
        "build_equivalence_audit",
        lambda **kwargs: {
            "schema_version": "simulation_comparison_audit_v1",
            "status": "pass",
            "reference_simulation": kwargs["reference_simulation"],
            "issues": [],
        },
    )
    monkeypatch.setattr(
        output_pipeline_module,
        "generate_comparison_figures",
        lambda **kwargs: [
            {
                "kind": "mock_figure",
                "observable": "head_mid",
                "path": str(kwargs["comparison_root"] / "comparison_figures" / "mock.png"),
            }
        ],
    )

    manifest = SimulationComparisonLauncher(config_path).run()

    manifest_path = Path(manifest["manifest_path"])
    assert manifest_path.exists()
    persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert persisted["audit_status"] == "pass"
    assert persisted["n_observable_rows"] == 2
    assert persisted["n_metric_rows"] == 1
    assert Path(persisted["observables_csv"]).exists()
    assert Path(persisted["comparison_metrics_csv"]).exists()
    assert persisted["generated_configs_kept"] is True
    assert (tmp_path / "comparison_outputs" / "_generated_configs" / "mf6_ref.toml").exists()


def test_simulation_comparison_child_failure_includes_output_tail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_base_simulation_config(tmp_path / "base.toml")
    config_path = tmp_path / "compare.toml"
    _write_comparison_config(config_path, output_root="comparison_outputs")

    import hydromodpy.analysis.comparison.experiment_launcher as launcher_module

    def fake_run_child_with_hmp(
        child_config_path: Path,
        *,
        python_executable: str | None = None,
        timeout_seconds: float | None = None,
    ) -> ChildRunResult:
        del python_executable, timeout_seconds
        return ChildRunResult(
            config_path=child_config_path,
            returncode=1,
            wall_time_seconds=0.25,
            sim_id=None,
            stdout="",
            stderr="duckdb.IOException: database is locked by another process",
        )

    monkeypatch.setattr(launcher_module, "run_child_with_hmp", fake_run_child_with_hmp)

    with pytest.raises(RuntimeError) as excinfo:
        SimulationComparisonLauncher(config_path).run()

    message = str(excinfo.value)
    assert "Comparison child 'mf6_ref' failed" in message
    assert "hmp run exited with code 1" in message
    assert "stderr tail:" in message
    assert "database is locked by another process" in message


def test_simulation_comparison_launcher_can_remove_generated_child_tomls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_base_simulation_config(tmp_path / "base.toml")
    config_path = tmp_path / "compare.toml"
    _write_comparison_config(
        config_path,
        output_root="comparison_outputs",
        keep_generated_configs=False,
    )

    import hydromodpy.analysis.comparison.experiment_launcher as launcher_module

    sim_ids = {
        "mf6_ref": "00000000-0000-0000-0000-000000000001",
        "bouss_candidate": "00000000-0000-0000-0000-000000000002",
    }

    def fake_run_child_with_hmp(
        child_config_path: Path,
        *,
        python_executable: str | None = None,
        timeout_seconds: float | None = None,
    ) -> ChildRunResult:
        del python_executable, timeout_seconds
        simulation_id = child_config_path.stem
        return ChildRunResult(
            config_path=child_config_path,
            returncode=0,
            wall_time_seconds=0.25,
            sim_id=sim_ids[simulation_id],
            stdout="",
            stderr=f"  sim_id: {sim_ids[simulation_id]}\n",
        )

    monkeypatch.setattr(launcher_module, "run_child_with_hmp", fake_run_child_with_hmp)
    monkeypatch.setattr(
        SimulationComparisonLauncher,
        "_extract_observables",
        lambda self, comparison_cfg, simulation_summaries: [
            {
                "comparison_id": "demo_sim_compare",
                "simulation_id": "mf6_ref",
                "simulation_label": "MF6 reference",
                "solver": "modflow6",
                "mesh_mode": "unknown",
                "observable": "head_mid",
                "variable": "watertable_elevation",
                "support": "point",
                "time": "last",
                "time_index": 0,
                "elapsed_seconds": 0.0,
                "comparison_time_key": "time_index:0",
                "match_fallback_key": "time_selector:last",
                "value_index": 0,
                "value": 10.0,
                "is_nodata": False,
                "unit": "m",
                "selection": "declared_cell",
            },
            {
                "comparison_id": "demo_sim_compare",
                "simulation_id": "bouss_candidate",
                "simulation_label": "Boussinesq candidate",
                "solver": "boussinesq",
                "mesh_mode": "unknown",
                "observable": "head_mid",
                "variable": "watertable_elevation",
                "support": "point",
                "time": "last",
                "time_index": 0,
                "elapsed_seconds": 0.0,
                "comparison_time_key": "time_index:0",
                "match_fallback_key": "time_selector:last",
                "value_index": 0,
                "value": 11.0,
                "is_nodata": False,
                "unit": "m",
                "selection": "declared_cell",
            },
        ],
    )
    monkeypatch.setattr(
        launcher_module,
        "build_equivalence_audit",
        lambda **kwargs: {
            "schema_version": "simulation_comparison_audit_v1",
            "status": "pass",
            "reference_simulation": kwargs["reference_simulation"],
            "issues": [],
        },
    )
    monkeypatch.setattr(output_pipeline_module, "generate_comparison_figures", lambda **kwargs: [])

    manifest = SimulationComparisonLauncher(config_path).run()

    generated_dir = tmp_path / "comparison_outputs" / "_generated_configs"
    assert manifest["generated_configs_kept"] is False
    assert manifest["generated_config_cleanup_errors"] == []
    assert not (generated_dir / "mf6_ref.toml").exists()
    assert not (generated_dir / "bouss_candidate.toml").exists()
