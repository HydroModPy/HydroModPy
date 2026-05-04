from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import hydromodpy.analysis.comparison.audit as audit_module
import hydromodpy.analysis.comparison.output_pipeline as output_pipeline_module
from hydromodpy.analysis.comparison.audit import build_equivalence_audit
from hydromodpy.analysis.comparison.child_materialization import materialize_child_configs
from hydromodpy.analysis.comparison.experiment_config import SimulationComparisonConfig
from hydromodpy.analysis.comparison.experiment_launcher import SimulationComparisonLauncher
from hydromodpy.analysis.comparison.run_backend import ChildRunResult
from hydromodpy.analysis.comparison.runtime import resolve_bundle_cells
from hydromodpy.cli.commands.run import _infer_workflow_from_sections
from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.workflow.dispatch import resolve_workflow


def _write_base_simulation_config(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                'workflow = "simulation"',
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
                'workflow = "comparison"',
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


def test_simulation_comparison_materializes_child_tomls(tmp_path: Path) -> None:
    _write_base_simulation_config(tmp_path / "base.toml")
    config_path = tmp_path / "compare.toml"
    _write_comparison_config(config_path)

    cfg = _load_comparison_cfg(config_path)
    children = materialize_child_configs(cfg)

    assert [child.simulation_id for child in children] == ["mf6_ref", "bouss_candidate"]
    mf6_raw = load_toml_with_base_config(children[0].config_path)
    bouss_raw = load_toml_with_base_config(children[1].config_path)
    assert mf6_raw["workflow"] == "simulation"
    assert mf6_raw["simulation"]["name"] == "demo_sim_compare__mf6_ref"
    assert mf6_raw["simulation"]["process"][0]["solvers"] == ["modflow6"]
    assert bouss_raw["simulation"]["run_id"] == "demo_sim_compare__bouss_candidate"
    assert bouss_raw["simulation"]["process"][0]["solvers"] == ["boussinesq"]


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
                'workflow = "comparison"',
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
    assert [child.run_folder for child in children] == [run_a.resolve(), run_b.resolve()]
    assert not (tmp_path / "comparison" / "existing_runs" / "_generated_configs").exists()


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
                'workflow = "comparison"',
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
        variant_summaries,
    ) -> list[dict[str, object]]:
        assert [summary["config_path"] for summary in variant_summaries] == [None, None]
        assert [Path(str(summary["run_folder"])).name for summary in variant_summaries] == [
            "mf6",
            "bouss",
        ]
        assert [variant.id for variant in comparison_cfg.comparison.variant] == [
            "mf6_ref",
            "bouss_candidate",
        ]
        return [
            {
                "comparison_id": "existing_runs",
                "variant": "mf6_ref",
                "variant_label": "mf6_ref",
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
                "variant": "bouss_candidate",
                "variant_label": "bouss_candidate",
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
            "reference_variant": kwargs["reference_variant"],
            "issues": [],
        },
    )
    monkeypatch.setattr(output_pipeline_module, "generate_comparison_figures", lambda **kwargs: [])

    manifest = SimulationComparisonLauncher(config_path).run()

    assert manifest["base_simulation_config"] is None
    assert manifest["generated_config_paths"] == []
    assert manifest["variants"][0]["status"] == "reused"
    assert manifest["variants"][0]["config_path"] is None
    assert manifest["n_observable_rows"] == 2


def test_simulation_comparison_rejects_physical_overlay_changes(tmp_path: Path) -> None:
    _write_base_simulation_config(tmp_path / "base.toml")
    config_path = tmp_path / "compare.toml"
    config_path.write_text(
        "\n".join(
            [
                'workflow = "comparison"',
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


def test_simulation_comparison_allows_flow_parameter_sweep_overlay(tmp_path: Path) -> None:
    _write_base_simulation_config(tmp_path / "base.toml")
    config_path = tmp_path / "compare.toml"
    config_path.write_text(
        "\n".join(
            [
                'workflow = "comparison"',
                "",
                "[comparison]",
                'base_simulation_config = "base.toml"',
                "",
                "[[comparison.simulation]]",
                'id = "k_mid"',
                'solver = "modflow6"',
                "",
                "[comparison.simulation.overlay.flow.param.K.field_homogeneous]",
                'value = "2e-4 m/s"',
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

    assert raw["flow"]["param"]["K"]["field_homogeneous"]["value"] == "2e-4 m/s"


def test_simulation_comparison_allows_flow_boundary_sweep_overlay(tmp_path: Path) -> None:
    _write_base_simulation_config(tmp_path / "base.toml")
    config_path = tmp_path / "compare.toml"
    config_path.write_text(
        "\n".join(
            [
                'workflow = "comparison"',
                "",
                "[comparison]",
                'base_simulation_config = "base.toml"',
                "",
                "[[comparison.simulation]]",
                'id = "drainage_high"',
                'solver = "modflow6"',
                "",
                "[comparison.simulation.overlay.flow.bc.cauchy.drainage]",
                'value = "3e-3 m2/s"',
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

    assert raw["flow"]["bc"]["cauchy"]["drainage"]["value"] == "3e-3 m2/s"


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
                'workflow = "comparison"',
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


def test_simulation_comparison_rejects_unknown_observable_variant(tmp_path: Path) -> None:
    _write_base_simulation_config(tmp_path / "base.toml")
    config_path = tmp_path / "compare.toml"
    config_path.write_text(
        "\n".join(
            [
                'workflow = "comparison"',
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
                'variants = ["missing_candidate"]',
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

    with pytest.raises(ValueError, match="comparison.comparison_id cannot contain"):
        SimulationComparisonConfig.from_toml(raw, config_path=config_path)


def test_cli_resolves_comparison_workflow(tmp_path: Path) -> None:
    config_path = tmp_path / "compare.toml"
    config_path.write_text(
        'workflow = "comparison"\n[comparison]\nbase_simulation_config = "base.toml"\n',
        encoding="utf-8",
    )

    assert resolve_workflow(config_path, cli_workflow=None, require_toml_field=True) == "comparison"
    assert _infer_workflow_from_sections({"comparison": {}}) == "comparison"


def test_resolve_bundle_cells_reads_mesh_input_from_generated_config(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "cells.csv").write_text(
        "\n".join(
            [
                "cell_id,centroid_x,centroid_y,area_m2,storage_coefficient",
                "0,12.0,34.0,56.0,0.1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "generated_child.toml"
    config_path.write_text(
        "\n".join(
            [
                'workflow = "simulation"',
                "",
                "[workspace]",
                'project_root = "."',
                "",
                "[simulation]",
                'run_id = "demo"',
                "",
                "[mesh_input]",
                'bundle_dir = "bundle"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cells = resolve_bundle_cells(
        tmp_path / "run_without_metrics",
        config_path=config_path,
        expected_size=1,
    )

    assert cells is not None
    assert cells.cell_ids.tolist() == [0]
    assert cells.x.tolist() == [12.0]
    assert cells.area_m2 is not None
    assert cells.area_m2.tolist() == [56.0]


def test_equivalence_audit_flags_physical_config_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_config = tmp_path / "mf6_ref.toml"
    candidate_config = tmp_path / "bouss_candidate.toml"
    common = [
        'workflow = "simulation"',
        "",
        "[simulation.time]",
        'start_datetime = "2020-01-01 00:00:00"',
        'end_datetime = "2020-01-15 00:00:00"',
        'step_value = "7 day"',
        "",
        "[flow]",
        'flow_regime = "transient"',
        'active_sinks_sources = ["recharge"]',
        "active_bc = []",
        "",
        "[flow.param.K]",
        'value = "1e-5 m/s"',
        "",
        "[flow.ic]",
        'type = "top"',
        "",
        "[flow.sinks_sources.recharge]",
        'first_clim = "mean"',
        "",
        "[data.recharge]",
        'date_start = "2020-01-01"',
        'date_end = "2020-01-15"',
        "",
        "[[data.recharge.sources]]",
        'source = "synthetic"',
        'freq = "7D"',
    ]
    ref_config.write_text(
        "\n".join([*common, "values = [1.0, 2.0]"]) + "\n",
        encoding="utf-8",
    )
    candidate_config.write_text(
        "\n".join([*common, "values = [1.0, 4.0]"]) + "\n",
        encoding="utf-8",
    )

    class FakeStore:
        def __init__(self, sim_id: str) -> None:
            self.sim_id = sim_id

        @property
        def connection(self) -> object:
            raise AttributeError("no parameter table")

        def list_simulations(self) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "sim_id": self.sim_id,
                        "mesh_hash": "same",
                        "n_cells": 1,
                        "n_timesteps": 2,
                        "crs_epsg": 2154,
                    }
                ]
            )

        def query_budget(self, sim_id: str) -> pd.DataFrame:
            assert sim_id == self.sim_id
            return pd.DataFrame()

        def close(self) -> None:
            pass

    def fake_discover_result_store(
        config_path: Path | None,
        *,
        preferred_sim_id: str | None = None,
        preferred_name: str | None = None,
    ) -> tuple[FakeStore, str]:
        del config_path, preferred_name
        sim_id = preferred_sim_id or "sim"
        return FakeStore(sim_id), sim_id

    monkeypatch.setattr(audit_module, "discover_result_store", fake_discover_result_store)

    audit = build_equivalence_audit(
        variant_summaries=[
            {
                "id": "mf6_ref",
                "status": "completed",
                "sim_id": "ref",
                "config_path": str(ref_config),
            },
            {
                "id": "bouss_candidate",
                "status": "completed",
                "sim_id": "candidate",
                "config_path": str(candidate_config),
            },
        ],
        reference_variant="mf6_ref",
        on_mismatch="warn",
    )

    assert audit["status"] == "warn"
    assert any(
        issue["kind"] == "config_section_mismatch" and issue["field"] == "data.recharge"
        for issue in audit["issues"]
    )


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
        variant_id = child_config_path.stem
        return ChildRunResult(
            config_path=child_config_path,
            returncode=0,
            wall_time_seconds=0.25,
            sim_id=sim_ids[variant_id],
            stdout="",
            stderr=f"  sim_id: {sim_ids[variant_id]}\n",
        )

    def fake_extract_observables(
        self: SimulationComparisonLauncher,
        method_cfg,
        variant_summaries: list[dict],
    ) -> list[dict]:
        del self, method_cfg, variant_summaries
        return [
            {
                "comparison_id": "demo_sim_compare",
                "variant_id": "mf6_ref",
                "variant_label": "MF6 reference",
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
                "variant_id": "bouss_candidate",
                "variant_label": "Boussinesq candidate",
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
            "reference_variant": kwargs["reference_variant"],
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
        variant_id = child_config_path.stem
        return ChildRunResult(
            config_path=child_config_path,
            returncode=0,
            wall_time_seconds=0.25,
            sim_id=sim_ids[variant_id],
            stdout="",
            stderr=f"  sim_id: {sim_ids[variant_id]}\n",
        )

    monkeypatch.setattr(launcher_module, "run_child_with_hmp", fake_run_child_with_hmp)
    monkeypatch.setattr(
        SimulationComparisonLauncher,
        "_extract_observables",
        lambda self, method_cfg, variant_summaries: [
            {
                "comparison_id": "demo_sim_compare",
                "variant_id": "mf6_ref",
                "variant_label": "MF6 reference",
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
                "variant_id": "bouss_candidate",
                "variant_label": "Boussinesq candidate",
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
            "reference_variant": kwargs["reference_variant"],
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
