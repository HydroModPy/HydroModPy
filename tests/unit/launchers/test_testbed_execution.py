from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import hydromodpy
from hydromodpy.analysis.testbed.contracts import register_testbed_runner_provider
from hydromodpy.analysis.testbed.runtime import TestbedLauncher as MethodTestbedLauncher
from hydromodpy.core.toml_io import load_toml_with_base_config

from ._testbed_builders import _write_calibration_base, _write_comparison_base, _write_flow_base


@pytest.fixture(autouse=True)
def _bootstrap_analysis_contracts() -> None:
    """Install the default analysis runner contracts before each case.

    Each test re-registers a fake provider, but the comparison and
    calibration dispatch paths require the project contracts installed by
    ``hydromodpy.bootstrap()``. The original single-file module obtained
    this implicitly from test ordering; make it explicit here.
    """
    hydromodpy.bootstrap()


def test_testbed_launcher_runs_comparison_cases_and_collects_metrics(
    tmp_path: Path,
) -> None:
    base_config = tmp_path / "comparison_base.toml"
    _write_comparison_base(base_config)
    config_path = tmp_path / "comparison_testbed.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "testbed"',
                "",
                "[testbed]",
                'id = "comparison_campaign"',
                'subject = "flow"',
                'base_config = "comparison_base.toml"',
                'output_root = "outputs/testbed"',
                "",
                "[testbed.runner]",
                'type = "comparison"',
                "",
                "[[testbed.case]]",
                'id = "candidate"',
                'axis = "method_pair"',
                "",
                "[testbed.case.overlay.comparison]",
                'comparison_id = "candidate_comparison"',
                "",
                "[[testbed.metric]]",
                'name = "comparison_id"',
                "",
                "[[testbed.metric]]",
                'name = "n_metric_rows"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    calls: list[Path] = []

    class _FakeProvider:
        def run_simulation(self, child_config: Path, *, no_display: bool) -> dict[str, object]:
            raise AssertionError("simulation runner should not be used")

        def run_comparison(self, child_config: Path) -> dict[str, object]:
            calls.append(child_config)
            payload = load_toml_with_base_config(child_config)
            return {
                "comparison_id": payload["comparison"]["comparison_id"],
                "n_metric_rows": 3,
                "web_index": str(child_config.with_suffix(".html")),
            }

    register_testbed_runner_provider(_FakeProvider())

    summary = MethodTestbedLauncher(config_path).run()

    assert len(calls) == 1
    assert summary["successful_count"] == 1
    metrics_text = Path(summary["metrics_csv"]).read_text(encoding="utf-8")
    assert "case_id,case_label,axis,status,comparison_id,n_metric_rows" in metrics_text
    assert "candidate,candidate,method_pair,ok,candidate_comparison,3" in metrics_text


def test_testbed_launcher_runs_calibration_cases_and_collects_metrics(
    tmp_path: Path,
) -> None:
    base_config = tmp_path / "calibration_base.toml"
    _write_calibration_base(base_config)
    config_path = tmp_path / "calibration_testbed.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "testbed"',
                "",
                "[testbed]",
                'id = "calibration_campaign"',
                'subject = "flow"',
                'base_config = "calibration_base.toml"',
                'output_root = "outputs/testbed"',
                "",
                "[testbed.runner]",
                'type = "calibration"',
                "",
                "[[testbed.case]]",
                'id = "site_01"',
                'axis = "site"',
                "",
                "[testbed.case.overlay.calibration]",
                'campaign_id = "site_01_calibration"',
                'output_root = "calibration_outputs/site_01"',
                "",
                "[[testbed.metric]]",
                'name = "calibration_id"',
                "",
                "[[testbed.metric]]",
                'name = "best_score"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    calls: list[Path] = []

    class _FakeProvider:
        def run_simulation(self, child_config: Path, *, no_display: bool) -> dict[str, object]:
            raise AssertionError("simulation runner should not be used")

        def run_comparison(self, child_config: Path) -> dict[str, object]:
            raise AssertionError("comparison runner should not be used")

        def run_calibration(self, child_config: Path) -> dict[str, object]:
            calls.append(child_config)
            payload = load_toml_with_base_config(child_config)
            assert payload["workflow"] == "calibration"
            return {
                "calibration_id": payload["calibration"]["campaign_id"],
                "best_score": 0.92,
                "manifest_path": str(child_config.with_suffix(".json")),
            }

    register_testbed_runner_provider(_FakeProvider())

    summary = MethodTestbedLauncher(config_path).run()

    assert len(calls) == 1
    assert summary["successful_count"] == 1
    generated = Path(summary["generated_configs_dir"]) / "site_01.toml"
    child_payload = load_toml_with_base_config(generated)
    assert child_payload["workflow"] == "calibration"
    assert child_payload["calibration"]["campaign_id"] == "site_01_calibration"
    assert child_payload["calibration"]["output_root"].endswith("calibration_outputs/site_01")
    metrics_text = Path(summary["metrics_csv"]).read_text(encoding="utf-8")
    assert "case_id,case_label,axis,status,calibration_id,best_score" in metrics_text
    assert "site_01,site_01,site,ok,site_01_calibration,0.92" in metrics_text


def test_testbed_launcher_runs_catalog_backed_comparison_cases(
    tmp_path: Path,
) -> None:
    flow_base = tmp_path / "flow_base.toml"
    _write_flow_base(flow_base)
    base_config = tmp_path / "comparison_base.toml"
    base_config.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "comparison"',
                "",
                "[comparison]",
                'comparison_id = "comparison_base"',
                'base_simulation_config = "flow_base.toml"',
                'output_root = "comparison_outputs/base"',
                "",
                "[comparison.execution]",
                "run_simulations = false",
                "",
                "[[comparison.simulation]]",
                'id = "mf6"',
                'solver = "modflow6"',
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
    catalog_path = tmp_path / "sites.csv"
    catalog_path.write_text(
        "\n".join(
            [
                "site_id,site_label,area_class,x_outlet,y_outlet,target_area_km2,tags,enabled",
                "site_01,Site 01,10km2,131189.1,6833784.4,10.0,natural;comparison,true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "comparison_testbed.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "testbed"',
                "",
                "[testbed]",
                'id = "natural_comparison_catalog"',
                'subject = "flow"',
                'base_config = "comparison_base.toml"',
                'output_root = "outputs/testbed"',
                "",
                "[testbed.runner]",
                'type = "comparison"',
                "",
                "[testbed.catalog]",
                'path = "sites.csv"',
                'id_field = "site_id"',
                'label_field = "site_label"',
                'axis_field = "area_class"',
                'tags_field = "tags"',
                'tags = ["natural", "comparison"]',
                "",
                "[[testbed.case_from_catalog]]",
                'required_fields = ["x_outlet", "y_outlet", "target_area_km2"]',
                'id_template = "{site_id}"',
                'label_template = "{site_label}"',
                'axis_template = "{area_class}"',
                "",
                "[testbed.case_from_catalog.overlay.comparison]",
                'comparison_id = "{site_id}_mf6_bouss"',
                'output_root = "outputs/comparisons/{site_id}"',
                "",
                "[testbed.case_from_catalog.overlay.comparison.base_simulation_overlay.geographic.catchment]",
                'x_outlet = "{x_outlet}"',
                'y_outlet = "{y_outlet}"',
                "",
                "[testbed.case_from_catalog.overlay.comparison.base_simulation_overlay.geographic]",
                'target_area_km2 = "{target_area_km2}"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    calls: list[Path] = []

    class _FakeProvider:
        def run_simulation(self, child_config: Path, *, no_display: bool) -> dict[str, object]:
            raise AssertionError("simulation runner should not be used")

        def run_comparison(self, child_config: Path) -> dict[str, object]:
            calls.append(child_config)
            payload = load_toml_with_base_config(child_config)
            return {
                "comparison_id": payload["comparison"]["comparison_id"],
                "comparison_root": payload["comparison"]["output_root"],
                "comparison_web_report": str(child_config.with_suffix(".html")),
                "audit_status": "pass",
                "n_metric_rows": 3,
            }

    register_testbed_runner_provider(_FakeProvider())

    summary = MethodTestbedLauncher(config_path).run()

    assert len(calls) == 1
    generated = Path(summary["generated_configs_dir"]) / "site_01.toml"
    generated_text = generated.read_text(encoding="utf-8")
    assert "# Stable identifier for this comparison run." in generated_text
    assert "# Shared TOML overlay applied to the base simulation config" in generated_text
    assert "# X coordinate of the watershed outlet" in generated_text
    child_payload = load_toml_with_base_config(generated)
    assert child_payload["workflow"] == "comparison"
    assert child_payload["comparison"]["comparison_id"] == "site_01_mf6_bouss"
    assert child_payload["comparison"]["base_simulation_config"] == flow_base.resolve().as_posix()
    geographic = child_payload["comparison"]["base_simulation_overlay"]["geographic"]
    assert geographic["catchment"]["x_outlet"] == 131189.1
    assert geographic["catchment"]["y_outlet"] == 6833784.4
    assert geographic["target_area_km2"] == 10.0
    with Path(summary["cases_csv"]).open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["comparison_id"] == "site_01_mf6_bouss"
    assert rows[0]["comparison_web_report"].endswith("site_01.html")
    metrics_text = Path(summary["metrics_csv"]).read_text(encoding="utf-8")
    assert (
        "case_id,case_label,axis,status,comparison_id,audit_status,n_metric_rows,n_difference_rows"
    ) in metrics_text
    assert "site_01,Site 01,10km2,ok,site_01_mf6_bouss,pass,3," in metrics_text


def test_testbed_launcher_runs_mesh_cases_and_collects_metrics(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "testbed.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "testbed"',
                "",
                "[workspace]",
                'project_root = "mesh_outputs/base"',
                "",
                "[mesh_catchment]",
                'constraints_mode = "rivers_only"',
                "",
                "[testbed]",
                'id = "mesh_resolution"',
                'output_root = "outputs/testbed"',
                "",
                "[[testbed.case]]",
                'id = "coarse"',
                'axis = "resolution"',
                "",
                "[testbed.case.overlay.mesh_catchment.zone_meshing]",
                "global_size = 400.0",
                "",
                "[[testbed.case]]",
                'id = "fine"',
                'axis = "resolution"',
                "",
                "[testbed.case.overlay.mesh_catchment.zone_meshing]",
                "global_size = 100.0",
                "",
                "[[testbed.metric]]",
                'name = "n_cells"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    calls: list[Path] = []

    class _FakeProvider:
        def run_simulation(self, child_config: Path, *, no_display: bool) -> dict[str, object]:
            assert no_display is True
            calls.append(child_config)
            payload = load_toml_with_base_config(child_config)
            assert payload["workflow"] == "simulation"
            assert payload["simulation"]["process"][0]["type"] == "mesh"
            size = payload["mesh_catchment"]["zone_meshing"]["global_size"]
            n_cells = 10 if size == 400.0 else 40
            return {
                "summary_schema_version": "zone_conformal_sidecar_v1",
                "n_cells": n_cells,
                "output_mesh": str(child_config.with_suffix(".msh")),
            }

    register_testbed_runner_provider(_FakeProvider())

    summary = MethodTestbedLauncher(config_path).run()

    assert len(calls) == 2
    assert summary["successful_count"] == 2
    metrics_text = Path(summary["metrics_csv"]).read_text(encoding="utf-8")
    assert "case_id,case_label,axis,status,n_cells" in metrics_text
    assert "coarse,coarse,resolution,ok,10" in metrics_text
    assert "fine,fine,resolution,ok,40" in metrics_text
    manifest = json.loads(Path(summary["manifest_json"]).read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "testbed_manifest_v1"
    assert manifest["successful_count"] == 2


def test_testbed_launcher_runs_flow_cases_and_collects_metrics(
    tmp_path: Path,
) -> None:
    base_config = tmp_path / "flow_base.toml"
    _write_flow_base(base_config)
    config_path = tmp_path / "flow_testbed.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "testbed"',
                "",
                "[testbed]",
                'id = "flow_k_sensitivity"',
                'subject = "flow"',
                'base_config = "flow_base.toml"',
                'output_root = "outputs/testbed"',
                "",
                "[testbed.runner]",
                'type = "simulation"',
                "",
                "[[testbed.case]]",
                'id = "low_k"',
                'axis = "hydraulic_conductivity"',
                "",
                "[testbed.case.overlay.simulation]",
                'name = "flow_low_k"',
                "",
                "[testbed.case.overlay.flow.param.K.field]",
                'value = "5e-6 m/s"',
                "",
                "[[testbed.case]]",
                'id = "high_k"',
                'axis = "hydraulic_conductivity"',
                "",
                "[testbed.case.overlay.simulation]",
                'name = "flow_high_k"',
                "",
                "[testbed.case.overlay.flow.param.K.field]",
                'value = "2e-5 m/s"',
                "",
                "[[testbed.metric]]",
                'name = "sim_id"',
                "",
                "[[testbed.metric]]",
                'name = "k_value"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    calls: list[tuple[Path, bool]] = []

    class _FakeProvider:
        def run_simulation(self, child_config: Path, *, no_display: bool) -> dict[str, object]:
            calls.append((child_config, no_display))
            payload = load_toml_with_base_config(child_config)
            run_name = payload["simulation"]["name"]
            k_value = payload["flow"]["param"]["K"]["field"]["value"]
            return {
                "name": run_name,
                "sim_id": f"sim_{run_name}",
                "k_value": k_value,
                "wall_time_seconds": 1.25,
            }

    register_testbed_runner_provider(_FakeProvider())

    summary = MethodTestbedLauncher(config_path).run()

    assert len(calls) == 2
    assert all(no_display for _, no_display in calls)
    assert summary["successful_count"] == 2
    metrics_text = Path(summary["metrics_csv"]).read_text(encoding="utf-8")
    assert "case_id,case_label,axis,status,sim_id,k_value" in metrics_text
    assert "low_k,low_k,hydraulic_conductivity,ok,sim_flow_low_k,5e-6 m/s" in metrics_text
    assert "high_k,high_k,hydraulic_conductivity,ok,sim_flow_high_k,2e-5 m/s" in metrics_text
    cases_text = Path(summary["cases_csv"]).read_text(encoding="utf-8")
    assert "flow_low_k" in cases_text
    assert "sim_flow_high_k" in cases_text


def test_flow_testbed_enriches_metrics_from_simulation_catalog(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base_config = tmp_path / "flow_base.toml"
    _write_flow_base(base_config)
    config_path = tmp_path / "flow_testbed.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "testbed"',
                "",
                "[testbed]",
                'id = "flow_catalog_metrics"',
                'subject = "flow"',
                'base_config = "flow_base.toml"',
                'output_root = "outputs/testbed"',
                "",
                "[testbed.runner]",
                'type = "simulation"',
                "",
                "[[testbed.case]]",
                'id = "reference"',
                'axis = "catalog"',
                "",
                "[testbed.case.overlay.simulation]",
                'name = "flow_reference"',
                "",
                "[[testbed.metric]]",
                'name = "duration_s"',
                'source = "flow_metrics.duration_s"',
                "",
                "[[testbed.metric]]",
                'name = "param_K"',
                'source = "flow_metrics.param_K"',
                "",
                "[[testbed.metric]]",
                'name = "max_abs_balance_error"',
                'source = "flow_metrics.max_abs_mass_balance_percent_error"',
                "",
                "[[testbed.metric]]",
                'name = "head_range_m"',
                'source = "flow_metrics.head_range_m"',
                "",
                "[[testbed.metric]]",
                'name = "prescribed_head_out"',
                'source = "flow_metrics.budget_chd_total_out"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    class _FakeProvider:
        def run_simulation(self, child_config: Path, *, no_display: bool) -> dict[str, object]:
            assert no_display is True
            return {
                "name": "flow_reference",
                "sim_id": "11111111-1111-1111-1111-111111111111",
            }

    class _FakeRun:
        sim_id = "11111111-1111-1111-1111-111111111111"
        name = "flow_reference"
        project = "testbed"
        solver = "modflow6"
        solver_category = "distributed"
        flow_regime = "steady"
        status = "completed"
        duration_s = 12.5
        n_cells = 4
        n_layers = 1
        n_timesteps = 2

        @property
        def parameters(self) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "param_name": "K",
                        "zone_id": "__global__",
                        "value": 1.0e-5,
                        "unit": "m/s",
                    }
                ]
            )

        @property
        def mass_balance(self) -> pd.DataFrame:
            return pd.DataFrame({"percent_error": [0.1, -0.25]})

        def budget(self) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {"component": "chd", "flux_in": 0.0, "flux_out": 1.2},
                    {"component": "chd", "flux_in": 0.0, "flux_out": 1.8},
                    {"component": "rcha", "flux_in": 3.0, "flux_out": 0.0},
                ]
            )

        def has_field(self, variable: str) -> bool:
            return variable in {"head", "outflow_drain"}

        def field(self, variable: str, timestep: int = -1) -> np.ndarray:
            assert timestep == -1
            if variable == "head":
                return np.array([10.0, 12.0, np.nan, 14.0])
            return np.array([0.0, 2.0, 0.5, np.nan])

    class _FakeStore:
        closed = False

        def __getitem__(self, sim_id: str) -> _FakeRun:
            assert sim_id == _FakeRun.sim_id
            return _FakeRun()

        def close(self) -> None:
            self.closed = True

    fake_store = _FakeStore()

    def _fake_discover_result_store(
        config_path: Path | None,
        *,
        preferred_sim_id: str | None = None,
        preferred_name: str | None = None,
    ) -> tuple[_FakeStore, str]:
        assert config_path is not None
        assert preferred_sim_id == _FakeRun.sim_id
        assert preferred_name == "flow_reference"
        return fake_store, _FakeRun.sim_id

    register_testbed_runner_provider(_FakeProvider())
    monkeypatch.setattr(
        "hydromodpy.analysis.comparison.runtime.metadata.discover_result_store",
        _fake_discover_result_store,
    )

    summary = MethodTestbedLauncher(config_path).run()

    assert fake_store.closed is True
    assert summary["successful_count"] == 1
    metrics_text = Path(summary["metrics_csv"]).read_text(encoding="utf-8")
    assert (
        "case_id,case_label,axis,status,duration_s,param_K,"
        "max_abs_balance_error,head_range_m,prescribed_head_out"
    ) in metrics_text
    assert "reference,reference,catalog,ok,12.5,1e-05,0.25,4.0,3.0" in metrics_text
    manifest = json.loads(Path(summary["manifest_json"]).read_text(encoding="utf-8"))
    case = manifest["cases"][0]
    assert case["flow_metrics"]["n_cells"] == 4
    assert case["catalog"]["status"] == "completed"


def test_testbed_required_metric_failure_is_persisted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base_config = tmp_path / "flow_base.toml"
    _write_flow_base(base_config)
    config_path = tmp_path / "flow_testbed.toml"
    config_path.write_text(
        "\n".join(
            [
                '[workflow]\nmode = "testbed"',
                "",
                "[testbed]",
                'id = "flow_required_metric"',
                'subject = "flow"',
                'base_config = "flow_base.toml"',
                'output_root = "outputs/testbed"',
                "continue_on_error = false",
                "",
                "[testbed.runner]",
                'type = "simulation"',
                "",
                "[[testbed.case]]",
                'id = "reference"',
                'axis = "catalog"',
                "",
                "[testbed.case.overlay.simulation]",
                'name = "flow_reference"',
                "",
                "[[testbed.metric]]",
                'name = "missing_required_metric"',
                'source = "flow_metrics.missing_required_metric"',
                "required = true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    class _FakeProvider:
        def run_simulation(self, child_config: Path, *, no_display: bool) -> dict[str, object]:
            assert no_display is True
            return {"name": "flow_reference", "sim_id": "missing-catalog-run"}

    def _fake_discover_result_store(
        config_path: Path | None,
        *,
        preferred_sim_id: str | None = None,
        preferred_name: str | None = None,
    ) -> tuple[None, str]:
        assert config_path is not None
        assert preferred_sim_id == "missing-catalog-run"
        assert preferred_name == "flow_reference"
        return None, ""

    register_testbed_runner_provider(_FakeProvider())
    monkeypatch.setattr(
        "hydromodpy.analysis.comparison.runtime.metadata.discover_result_store",
        _fake_discover_result_store,
    )

    with pytest.raises(ValueError, match="Required testbed metric"):
        MethodTestbedLauncher(config_path).run()

    manifest_path = tmp_path / "outputs" / "testbed" / "testbed_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["failed_count"] == 1
    assert "Required testbed metric" in manifest["cases"][0]["error"]
