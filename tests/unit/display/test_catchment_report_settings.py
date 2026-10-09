from __future__ import annotations

from pathlib import Path
from typing import get_args

import pytest

from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.display.catchment_report import CatchmentReportInputs
from hydromodpy.display.catchment_report.presets import PRESETS_BY_NAME
from hydromodpy.display.catchment_report.settings import (
    CatchmentReportSettings,
    ContextSection,
    GeologySection,
    LayoutSection,
    ObservedDischargeSection,
    PipelineSection,
    PresetName,
    ReportConfig,
    ReportSection,
)

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
    assert not hasattr(settings, "simulation_export")

    assert inputs.context_summary == (
        tmp_path / "context" / "context" / "test_basin_gauged_context_summary.json"
    )
    assert inputs.transient_config == tmp_path / "run_transient_nwt.toml"
    assert inputs.overview_config == tmp_path / "config_overview.toml"
    assert not hasattr(inputs, "simulation_export")


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
    assert settings.pipeline.strict_figure_postflight is True


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

    with pytest.raises(ConfigValidationError, match="run_simulation"):
        CatchmentReportSettings.from_toml(config_path)


def _write_report_file(tmp_path: Path, extra: str = "") -> Path:
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
""".lstrip()
        + extra,
        encoding="utf-8",
    )
    return config_path


def test_a_misspelled_key_is_refused_with_its_location(tmp_path) -> None:
    config_path = _write_report_file(tmp_path, "\n[pipeline]\nrun_simulaton = true\n")

    with pytest.raises(ConfigValidationError, match="run_simulaton") as raised:
        CatchmentReportSettings.from_toml(config_path)

    assert "pipeline.run_simulaton" in str(raised.value)
    assert raised.value.details[0]["pointer"] == "/pipeline/run_simulaton"


def test_a_misspelled_table_is_refused(tmp_path) -> None:
    config_path = _write_report_file(tmp_path, "\n[pipline]\nrun_simulation = true\n")

    with pytest.raises(ConfigValidationError, match="pipline"):
        CatchmentReportSettings.from_toml(config_path)


def test_a_missing_table_or_key_is_named(tmp_path) -> None:
    no_layout = tmp_path / "no_layout.toml"
    no_layout.write_text(
        '[report]\nsite_label = "T"\nstation_label = "S"\noutput_dir = "r"\n', encoding="utf-8"
    )
    with pytest.raises(ConfigValidationError, match="layout"):
        CatchmentReportSettings.from_toml(no_layout)

    no_output = tmp_path / "no_output.toml"
    no_output.write_text(
        '[report]\nsite_label = "T"\nstation_label = "S"\n'
        '[layout]\nwatershed_project_dir = "."\ncontext_outputs_dir = "c"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigValidationError, match="output_dir"):
        CatchmentReportSettings.from_toml(no_output)


def test_an_unknown_preset_is_refused_at_load(tmp_path) -> None:
    config_path = _write_report_file(tmp_path)
    text = config_path.read_text(encoding="utf-8").replace(
        'output_dir = "report"', 'output_dir = "report"\npreset = "made_up"'
    )
    config_path.write_text(text, encoding="utf-8")

    with pytest.raises(ConfigValidationError, match="report.preset"):
        CatchmentReportSettings.from_toml(config_path)


def test_an_observed_discharge_table_needs_its_path(tmp_path) -> None:
    config_path = _write_report_file(
        tmp_path, '\n[context.observed_discharge]\nstation_id = "X1"\n'
    )

    with pytest.raises(ConfigValidationError, match="context.observed_discharge.path"):
        CatchmentReportSettings.from_toml(config_path)


def test_relative_paths_resolve_from_the_report_file(tmp_path) -> None:
    config_path = _write_report_file(
        tmp_path,
        '\n[context.observed_discharge]\npath = "obs/q.csv"\nstation_id = "X1"\n',
    )

    settings = CatchmentReportSettings.from_toml(config_path)

    assert settings.observed_discharge is not None
    assert settings.observed_discharge.path == tmp_path / "obs" / "q.csv"
    assert settings.layout.data_overview_project_dir == tmp_path
    assert settings.layout.simulation_workspace_dir == tmp_path


def test_the_geology_table_is_read_and_resolved(tmp_path) -> None:
    config_path = _write_report_file(tmp_path, '\n[context.geology]\npath = "geo/map.gpkg"\n')

    settings = CatchmentReportSettings.from_toml(config_path)

    assert settings.geology is not None
    assert settings.geology.path == tmp_path / "geo" / "map.gpkg"
    assert CatchmentReportInputs.from_settings(settings).geology_path == tmp_path / "geo/map.gpkg"


def test_every_field_of_the_report_file_is_described() -> None:
    for model in (
        ReportConfig,
        ReportSection,
        LayoutSection,
        ContextSection,
        GeologySection,
        ObservedDischargeSection,
        PipelineSection,
    ):
        for name, info in model.model_fields.items():
            assert info.description, f"{model.__name__}.{name} has no description"


def test_the_preset_names_match_the_presets() -> None:
    assert set(get_args(PresetName)) == set(PRESETS_BY_NAME)
