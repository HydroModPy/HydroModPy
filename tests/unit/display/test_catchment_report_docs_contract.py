from __future__ import annotations

from pathlib import Path

from hydromodpy.display.catchment_report import (
    CatchmentReportBuildOptions,
    CatchmentReportConfig,
    CatchmentReportInputs,
)
from hydromodpy.display.catchment_report.presets import GENERIC_REPORT_PRESET

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
        "--strict-figure-postflight",
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
        "strict_figure_postflight",
        "preflight",
        "postflight",
        "generic_catchment_report",
    ):
        assert token in text


def test_catchment_report_documentation_declares_html_profile_support() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")

    for token in (
        "Current profile support is intentionally narrow",
        "``catchment_gauged``",
        "Supported for simulation runs",
        "``site_selection``",
        "Supported by the site-selection workflow",
        "``generic_simulation``",
        "Reserved",
        "no end-of-run HTML builder is shipped for it yet",
    ):
        assert token in text


def test_documented_example_configs_resolve_to_expected_presets() -> None:
    nancon_inputs = CatchmentReportInputs.from_toml(NANCON_CONFIG)
    selune_inputs = CatchmentReportInputs.from_toml(SELUNE_CONFIG)
    nancon_options = CatchmentReportBuildOptions.from_toml(NANCON_CONFIG)
    selune_options = CatchmentReportBuildOptions.from_toml(SELUNE_CONFIG)

    nancon_config = CatchmentReportConfig.from_inputs(nancon_inputs)
    selune_config = CatchmentReportConfig.from_inputs(selune_inputs)

    assert nancon_config.preset is GENERIC_REPORT_PRESET
    assert selune_config.preset is GENERIC_REPORT_PRESET
    assert nancon_options.run_overview is False
    assert nancon_options.run_simulation is False
    assert nancon_options.build_context_artifacts is True
    assert nancon_options.build_report_html is True
    assert nancon_options.strict_figure_postflight is False
    assert selune_options.run_overview is False
    assert selune_options.run_simulation is False
    assert selune_options.build_report_html is True
    assert selune_options.stream_run_logs is False
    assert selune_options.strict_figure_postflight is False
    assert nancon_inputs.transient_config.name == "run_transient_nwt.toml"
    assert nancon_inputs.overview_config.name == "run_overview_all_apis.toml"
    assert nancon_inputs.observed_discharge_path is not None
    assert selune_inputs.transient_config.name == "run_selune_nwt_report.toml"
    assert selune_inputs.observed_discharge_path is not None
