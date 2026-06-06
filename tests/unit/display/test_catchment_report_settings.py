from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.display.catchment_report import CatchmentReportBuildOptions, CatchmentReportInputs
from hydromodpy.display.catchment_report.settings import CatchmentReportSettings

REPO_ROOT = Path(__file__).resolve().parents[3]
SELUNE_CONFIG = (
    REPO_ROOT / "examples" / "projects" / "06_vire_selune" / "catchment_report_selune.toml"
)
NANCON_HTML_OVERLAY = (
    REPO_ROOT
    / "examples"
    / "projects"
    / "16_nancon_natural_calibration"
    / "catchment_report_transient_nwt_html.toml"
)


def test_settings_keep_toml_contract_separate_from_derived_inputs(tmp_path) -> None:
    config_path = tmp_path / "catchment_report.toml"
    config_path.write_text(
        """
[report]
site_label = "Test Basin"
station_label = "Test outlet"
output_dir = "report"

[layout]
watershed_project_dir = "."
context_outputs_dir = "context"
""".lstrip(),
        encoding="utf-8",
    )

    settings = CatchmentReportSettings.from_toml(config_path)
    inputs = CatchmentReportInputs.from_settings(settings)

    assert settings.report.output_dir == tmp_path / "report"
    assert settings.layout.context_summary_name is None
    assert settings.layout.transient_config_name is None
    assert settings.layout.overview_config_name is None
    assert settings.html_report.enabled is False
    assert settings.html_report.build_at_end is False
    assert settings.html_report.profile == "catchment_gauged"
    assert settings.html_report.strict is False
    assert not hasattr(settings, "pipeline")
    assert not hasattr(settings, "simulation_export")

    options = CatchmentReportBuildOptions.from_toml(config_path)
    assert options.run_simulation is False
    assert options.build_report_html is True
    assert options.strict_figure_postflight is False

    assert inputs.context_summary == (
        tmp_path / "context" / "context" / "test_basin_gauged_context_summary.json"
    )
    assert inputs.transient_config == tmp_path / "run_transient_nwt.toml"
    assert inputs.overview_config == tmp_path / "config_overview.toml"
    assert inputs.simulation_export == tmp_path / "exports" / "transient_nwt" / "timeseries.csv"


def test_inputs_from_toml_delegate_to_settings() -> None:
    settings = CatchmentReportSettings.from_toml(SELUNE_CONFIG)

    assert CatchmentReportInputs.from_settings(settings) == CatchmentReportInputs.from_toml(
        SELUNE_CONFIG
    )
    assert settings.report.site_label == "Selune"
    assert settings.layout.simulation_name == "selune_nwt_report"
    assert settings.observed_discharge is not None
    options = CatchmentReportBuildOptions.from_toml(SELUNE_CONFIG)
    assert options.run_overview is False
    assert options.run_simulation is False
    assert options.stream_run_logs is False
    assert options.strict_figure_postflight is False


def test_report_html_build_at_end_enables_report_without_enabled_key(tmp_path) -> None:
    config_path = tmp_path / "catchment_report.toml"
    config_path.write_text(
        """
[report]
site_label = "Test"
station_label = "Test outlet"
output_dir = "report"

[report.html]
build_at_end = true
profile = "catchment_gauged"

[layout]
watershed_project_dir = "."
context_outputs_dir = "context"
""".lstrip(),
        encoding="utf-8",
    )

    settings = CatchmentReportSettings.from_toml(config_path)

    assert settings.html_report.enabled is True
    assert settings.html_report.build_at_end is True
    assert settings.html_report.strict is False
    options = CatchmentReportBuildOptions.from_toml(config_path)
    assert options.build_report_html is True
    assert options.strict_figure_postflight is False


def test_settings_support_base_config_overlay(tmp_path) -> None:
    base_path = tmp_path / "catchment_report.toml"
    base_path.write_text(
        """
[report]
site_label = "Base Basin"
station_label = "Base outlet"
output_dir = "base_report"

[layout]
watershed_project_dir = "."
context_outputs_dir = "context"
simulation_name = "base_run"
""".lstrip(),
        encoding="utf-8",
    )
    overlay_path = tmp_path / "catchment_report_overlay.toml"
    overlay_path.write_text(
        """
base_config = "catchment_report.toml"

[report]
output_dir = "overlay_report"

[layout]
simulation_name = "overlay_run"
""".lstrip(),
        encoding="utf-8",
    )

    settings = CatchmentReportSettings.from_toml(overlay_path)

    assert settings.report.site_label == "Base Basin"
    assert settings.report.station_label == "Base outlet"
    assert settings.report.output_dir == tmp_path / "overlay_report"
    assert settings.layout.watershed_project_dir == tmp_path
    assert settings.layout.context_outputs_dir == tmp_path / "context"
    assert settings.layout.simulation_name == "overlay_run"


def test_nancon_html_report_overlay_points_to_demo_run() -> None:
    settings = CatchmentReportSettings.from_toml(NANCON_HTML_OVERLAY)
    inputs = CatchmentReportInputs.from_settings(settings)

    assert settings.report.site_label == "Nancon"
    assert settings.report.output_dir == (
        REPO_ROOT
        / "examples"
        / "projects"
        / "16_nancon_natural_calibration"
        / "outputs"
        / "nancon_transient_nwt_html_report"
    )
    assert settings.layout.simulation_name == "transient_nwt_html_report"
    assert inputs.transient_config == (
        REPO_ROOT
        / "examples"
        / "projects"
        / "02_nancon_watershed"
        / "run_transient_nwt_html_report.toml"
    )
    assert inputs.simulation_figures == (
        REPO_ROOT
        / "examples"
        / "projects"
        / "02_nancon_watershed"
        / "figures"
        / "transient_nwt_html_report"
    )
    options = CatchmentReportBuildOptions.from_toml(NANCON_HTML_OVERLAY)
    assert options.build_report_html is True


def test_report_html_enabled_can_prepare_artifacts_without_end_build(tmp_path) -> None:
    config_path = tmp_path / "catchment_report.toml"
    config_path.write_text(
        """
[report]
site_label = "Test"
station_label = "Test outlet"
output_dir = "report"

[report.html]
enabled = true
profile = "catchment_gauged"

[layout]
watershed_project_dir = "."
context_outputs_dir = "context"
""".lstrip(),
        encoding="utf-8",
    )

    settings = CatchmentReportSettings.from_toml(config_path)

    assert settings.html_report.enabled is True
    assert settings.html_report.build_at_end is False
    assert CatchmentReportBuildOptions.from_toml(config_path).build_report_html is False


def test_build_options_validate_boolean_pipeline_fields(tmp_path) -> None:
    config_path = tmp_path / "catchment_report.toml"
    config_path.write_text(
        """
[report]
site_label = "Test"
station_label = "Test outlet"
output_dir = "report"

[layout]
watershed_project_dir = "."
context_outputs_dir = "context"

[pipeline]
run_simulation = "yes"
""".lstrip(),
        encoding="utf-8",
    )

    settings = CatchmentReportSettings.from_toml(config_path)
    assert settings.report.site_label == "Test"

    with pytest.raises(ValueError, match="run_simulation"):
        CatchmentReportBuildOptions.from_toml(config_path)
