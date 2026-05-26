from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.display.catchment_report import CatchmentReportInputs
from hydromodpy.display.catchment_report.settings import CatchmentReportSettings

REPO_ROOT = Path(__file__).resolve().parents[3]
SELUNE_CONFIG = (
    REPO_ROOT / "examples" / "projects" / "06_vire_selune" / "catchment_report_selune.toml"
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
    assert settings.pipeline.run_simulation is False
    assert settings.pipeline.build_report_html is True
    assert settings.pipeline.strict_figure_postflight is False
    assert settings.pipeline.context_builder_command is None
    assert not hasattr(settings, "simulation_export")

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
    assert settings.pipeline.run_overview is True
    assert settings.pipeline.run_simulation is True
    assert settings.pipeline.stream_run_logs is False
    assert settings.pipeline.strict_figure_postflight is False
    assert settings.pipeline.context_builder_command is None


def test_settings_parse_context_builder_command(tmp_path) -> None:
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
context_builder_command = ["{python}", "build_context.py", "--report-config", "{report_config}"]
""".lstrip(),
        encoding="utf-8",
    )

    settings = CatchmentReportSettings.from_toml(config_path)

    assert settings.pipeline.context_builder_command == (
        "{python}",
        "build_context.py",
        "--report-config",
        "{report_config}",
    )


def test_settings_validate_boolean_pipeline_fields(tmp_path) -> None:
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

    with pytest.raises(ValueError, match="run_simulation"):
        CatchmentReportSettings.from_toml(config_path)


def test_settings_validate_context_builder_command(tmp_path) -> None:
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
context_builder_command = "python build_context.py"
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="context_builder_command"):
        CatchmentReportSettings.from_toml(config_path)
