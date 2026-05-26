from __future__ import annotations

from pathlib import Path

from hydromodpy.display.catchment_report import CatchmentReportConfig, CatchmentReportInputs
from hydromodpy.display.catchment_report.presets import (
    GENERIC_REPORT_PRESET,
    NANCON_REPORT_PRESET,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DOC_PATH = REPO_ROOT / "docs" / "source" / "user_guide" / "catchment-report.rst"
NANCON_CONFIG = (
    REPO_ROOT / "examples" / "projects" / "16_nancon_natural_calibration" / "catchment_report.toml"
)
SELUNE_CONFIG = (
    REPO_ROOT / "examples" / "projects" / "06_vire_selune" / "catchment_report_selune.toml"
)


def test_catchment_report_documentation_mentions_contract_fields() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")

    for token in (
        "hmp report catchment",
        "--report-only",
        "--context-only",
        "--run-simulation",
        "--run-overview",
        "--stream-run-logs",
        "site_label",
        "station_label",
        "output_dir",
        "watershed_project_dir",
        "context_outputs_dir",
        "simulation_workspace_dir",
        "transient_config_name",
        "overview_config_name",
        "context.observed_discharge",
        "[pipeline]",
        "run_simulation",
        "build_context_artifacts",
        "build_report_html",
        "stream_run_logs",
        "generic_catchment_report",
        "nancon_reference",
    ):
        assert token in text


def test_documented_example_configs_resolve_to_expected_presets() -> None:
    nancon_inputs = CatchmentReportInputs.from_toml(NANCON_CONFIG)
    selune_inputs = CatchmentReportInputs.from_toml(SELUNE_CONFIG)

    nancon_config = CatchmentReportConfig.from_inputs(nancon_inputs)
    selune_config = CatchmentReportConfig.from_inputs(selune_inputs)

    assert nancon_config.preset is NANCON_REPORT_PRESET
    assert selune_config.preset is GENERIC_REPORT_PRESET
    assert nancon_inputs.pipeline_build_context_artifacts is False
    assert nancon_inputs.pipeline_build_report_html is True
    assert selune_inputs.pipeline_run_simulation is True
    assert selune_inputs.pipeline_build_report_html is True
    assert selune_inputs.pipeline_stream_run_logs is False
    assert nancon_inputs.transient_config.name == "run_transient_nwt.toml"
    assert selune_inputs.transient_config.name == "run_selune_nwt_report.toml"
    assert selune_inputs.observed_discharge_path is not None
