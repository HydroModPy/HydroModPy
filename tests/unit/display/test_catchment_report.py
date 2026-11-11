"""The catchment report: context, English text, postflight and settings."""

from __future__ import annotations

import json
import logging
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import get_args

import pandas as pd
import pytest

from hydromodpy.config.hydromodpy_config import ROOT_CONFIG
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.core.logging import get_logger
from hydromodpy.display.catchment_report import (
    CatchmentReportConfig,
    CatchmentReportInputs,
    build_catchment_report,
)
from hydromodpy.display.catchment_report.artifacts import (
    artifact_candidate,
    artifact_spec,
    context_dem_path,
    geology_cache_candidates,
    geology_legend_rows,
)
from hydromodpy.display.catchment_report.blocks import DEFAULT_BLOCK_SPECS
from hydromodpy.display.catchment_report.builder import PRESETS_BY_NAME, CatchmentReportPreset
from hydromodpy.display.catchment_report.context import _observed_series
from hydromodpy.display.catchment_report.pipeline import (
    CatchmentReportPostflightError,
    write_figure_postflight_report,
)
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
from hydromodpy.results.catalog.listing import SEALED_SOLVE_METRIC
from hydromodpy.results.storage.run_profile import Profile, ProfileLine, write_profile

# The catchment report context reads the run, whatever solver made it.
#
# The cell count comes from the simulated run, not from a solver section of the
# TOML. A context figure that cannot be drawn is logged with its name and the
# reason, instead of disappearing from the report without a word.


def _inputs(tmp_path: Path) -> SimpleNamespace:
    transient = tmp_path / "transient.toml"
    transient.write_text('[workflow]\nmode = "simulation"\n', encoding="utf-8")
    return SimpleNamespace(
        context_dir=tmp_path / "context",
        context_summary=tmp_path / "context" / "context_summary.json",
        context_assets=tmp_path / "context" / "web" / "assets",
        transient_config=transient,
        observed_discharge_path=None,
        observed_discharge_station_id=None,
        simulation_figures=tmp_path / "figures",
        simulation_name="baseline",
        site_label="Nancon",
        run_dir=tmp_path / "runs" / "baseline",
    )


@pytest.mark.parametrize("n_cells", [4321, None])
def test_the_cell_count_is_the_one_of_the_simulated_run(monkeypatch, tmp_path, n_cells) -> None:
    """The TOML holds no ``[solver.modflow_nwt]``, as for any MODFLOW 6 or Boussinesq run."""
    import hydromodpy.display.catchment_report.context as context_module

    @contextmanager
    def open_run(inputs):
        yield SimpleNamespace(facts=SimpleNamespace(n_cells=n_cells))

    discharge = pd.DataFrame(
        {"datetime": pd.date_range("2020-01-01", periods=3, freq="D"), "value": [1.0, 2.0, 3.0]}
    )
    monkeypatch.setattr(context_module, "open_simulation_run", open_run)
    monkeypatch.setattr(
        context_module, "read_simulated_discharge", lambda store, station=None: discharge
    )
    monkeypatch.setattr(context_module, "simulation_parquet_dir", lambda store: None)

    summary_path = context_module.build_context(_inputs(tmp_path), root=ROOT_CONFIG)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["baseline_run"]["n_cells"] == n_cells


@pytest.mark.parametrize(
    ("profile_s", "metrics_s", "expected"),
    [
        pytest.param(12.5, 26.3, 12.5, id="the_profile_comes_first"),
        pytest.param(None, 26.3, 26.3, id="a_run_of_the_2_0_release_reads_metrics_parquet"),
        pytest.param(None, None, None, id="no_solve_time_anywhere"),
    ],
)
def test_the_solve_time_is_read_from_the_profile_before_metrics_parquet(
    monkeypatch, tmp_path, profile_s, metrics_s, expected
) -> None:
    import hydromodpy.display.catchment_report.context as context_module

    inputs = _inputs(tmp_path)
    tables = tmp_path / "tables"
    tables.mkdir()
    if metrics_s is not None:
        pd.DataFrame({"metric": [SEALED_SOLVE_METRIC], "value": [metrics_s]}).to_parquet(
            tables / "metrics.parquet"
        )
    if profile_s is not None:
        line = ProfileLine(
            kind="solve",
            name="flow_main::modflow6",
            attempt=1,
            started_at=datetime(2026, 11, 10, 9, 0, tzinfo=UTC),
            duration_s=profile_s,
        )
        inputs.run_dir.mkdir(parents=True)
        write_profile(inputs.run_dir, Profile(lines=(line,)))

    @contextmanager
    def open_run(_inputs):
        yield SimpleNamespace(facts=SimpleNamespace(n_cells=4))

    discharge = pd.DataFrame(
        {"datetime": pd.date_range("2020-01-01", periods=3, freq="D"), "value": [1.0, 2.0, 3.0]}
    )
    monkeypatch.setattr(context_module, "open_simulation_run", open_run)
    monkeypatch.setattr(
        context_module, "read_simulated_discharge", lambda store, station=None: discharge
    )
    monkeypatch.setattr(context_module, "simulation_parquet_dir", lambda store: tables)

    summary = json.loads(
        context_module.build_context(inputs, root=ROOT_CONFIG).read_text(encoding="utf-8")
    )

    assert summary["baseline_run"]["runtime_seconds"] == expected


def test_the_context_reads_the_station_the_observed_discharge_names(monkeypatch, tmp_path) -> None:
    import hydromodpy.display.catchment_report.context as context_module

    @contextmanager
    def open_run(inputs):
        yield SimpleNamespace(facts=SimpleNamespace(n_cells=4))

    asked = []
    discharge = pd.DataFrame(
        {"datetime": pd.date_range("2020-01-01", periods=3, freq="D"), "value": [1.0, 2.0, 3.0]}
    )

    def read(store, station=None):
        asked.append(station)
        return discharge

    monkeypatch.setattr(context_module, "open_simulation_run", open_run)
    monkeypatch.setattr(context_module, "read_simulated_discharge", read)
    monkeypatch.setattr(context_module, "simulation_parquet_dir", lambda store: None)
    inputs = _inputs(tmp_path)
    inputs.observed_discharge_station_id = "NANCON"

    context_module.build_context(inputs, root=ROOT_CONFIG)

    assert asked == ["NANCON"]


def _two_station_store() -> SimpleNamespace:
    """A run that kept the simulated discharge at two stations."""
    times = pd.date_range("2000-01-01", periods=2, freq="MS", tz="UTC")
    rows = [
        {
            "variable": "discharge",
            "source": "simulated",
            "station_id": station,
            "time": t,
            "value": v,
        }
        for station, values in (("NANCON", (1.0, 2.0)), ("catchment", (10.0, 20.0)))
        for t, v in zip(times, values, strict=True)
    ]
    return SimpleNamespace(run_dir=Path("runs/demo"), read_table=lambda name: pd.DataFrame(rows))


def test_a_run_with_two_stations_is_read_at_the_station_the_report_names() -> None:
    from hydromodpy.display.catchment_report.simulation_source import read_simulated_discharge

    store = _two_station_store()

    assert read_simulated_discharge(store, station="NANCON")["value"].tolist() == [1.0, 2.0]
    assert read_simulated_discharge(store, station="catchment")["value"].tolist() == [10.0, 20.0]


@pytest.mark.parametrize("station", [None, "ELSEWHERE"])
def test_a_run_with_two_stations_and_no_matching_name_is_refused_with_the_key_to_set(
    station,
) -> None:
    from hydromodpy.display.catchment_report.simulation_source import read_simulated_discharge

    with pytest.raises(KeyError, match="station_id") as exc_info:
        read_simulated_discharge(_two_station_store(), station=station)

    assert "NANCON, catchment" in str(exc_info.value)


def test_an_unreadable_generated_network_is_logged_by_figure_name(
    tmp_path, hmp_log_records
) -> None:
    from hydromodpy.display.catchment_report.artifacts import (
        generate_generated_network_context_figure,
    )
    from hydromodpy.results.storage.contract import PARQUET_FILE_SUFFIX, TABLES_DIRNAME

    runs = tmp_path / "runs"
    tables = runs / "baseline" / TABLES_DIRNAME
    tables.mkdir(parents=True)
    (tables / f"geographic_hydrographic_network_generated{PARQUET_FILE_SUFFIX}").write_bytes(
        b"not parquet"
    )
    scratch = tmp_path / "geographic"
    scratch.mkdir()
    (scratch / "watershed_box_buff_dem.tif").write_bytes(b"not a raster")
    (scratch / "watershed.shp").write_bytes(b"not a shapefile")
    copied: dict[str, Path] = {}

    generate_generated_network_context_figure(
        copied,
        figures_dir=tmp_path / "figures",
        config={},
        generated_network_root=runs,
        geographic_scratch=scratch,
        config_dir=tmp_path,
    )

    assert copied == {}
    warnings = [r.getMessage() for r in hmp_log_records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "context figure 'network_generated' skipped" in warnings[0]


def test_a_missing_generated_network_is_logged_as_information(tmp_path, hmp_log_records) -> None:
    """The figure is optional: saying why it is absent must not read as a fault."""
    from hydromodpy.display.catchment_report.artifacts import (
        generate_generated_network_context_figure,
    )

    generate_generated_network_context_figure(
        {},
        figures_dir=tmp_path / "figures",
        config={},
        generated_network_root=tmp_path / "runs",
        geographic_scratch=tmp_path / "geographic",
        config_dir=tmp_path,
    )

    messages = [(r.levelno, r.getMessage()) for r in hmp_log_records]
    assert [level for level, _ in messages] == [logging.INFO]
    assert (
        "context figure 'network_generated' not drawn, missing the generated network"
        in (messages[0][1])
    )


# The catchment report is written in English, and reads no file of the repository.
#
# Every title, label and caption of the page is English. The geology legend and the
# DEM are found from the report file and the user cache, never from a folder of the
# HydroModPy source tree.

# Words that exist in French and not in English, as they were written in the report.
_FRENCH = re.compile(
    r"\b(debit|reseau|bassin|fenetre|simule|simulee|geologi\w*|forcages|exutoire|"
    r"artefacts|proprietes|rapport|vue|niveau|bloc|aucun\w*|donnees|chroniques?|"
    r"pour|avec|des|les|du|et)\b",
    re.IGNORECASE,
)


def _french_words(text: str) -> list[str]:
    return sorted({match.group(0).lower() for match in _FRENCH.finditer(text)})


def test_block_specs_are_written_in_english() -> None:
    for spec in DEFAULT_BLOCK_SPECS:
        texts = [spec.title, spec.lead, *(figure.title for figure in spec.figures)]
        for text in texts:
            assert _french_words(text) == [], f"{spec.block_id}: {text!r}"


def test_the_report_pages_are_english(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HMP_CACHE_HOME", str(tmp_path / "cache"))
    empty = tmp_path / "empty"
    empty.mkdir()
    summary = tmp_path / "summary.json"
    summary.write_text(
        '{"configuration": {"crs": "EPSG:2154", "x_outlet": 1.0, "y_outlet": 2.0,'
        ' "configured_recharge_station_ids": ["R1"]},'
        ' "stats": {"observed_discharge": {"rows": 3, "mean": 0.5}},'
        ' "baseline_run": {"simulation_name": "run", "n_cells": 10}}\n',
        encoding="utf-8",
    )
    config = CatchmentReportConfig(
        output_dir=tmp_path / "report",
        site_label="Test",
        station_label="Test outlet",
        title="",
        context_summary=summary,
        context_assets=empty,
        overview_figures=empty,
        data_overview_figures=empty,
        simulation_figures=empty,
        geographic_scratch=empty,
        generated_network_root=empty,
        context_html=empty / "index.html",
        overview_standard_html=empty / "standard.html",
        transient_config=tmp_path / "run.toml",
        overview_config=tmp_path / "overview.toml",
    )

    html_path = build_catchment_report(config)

    assert html_path == config.output_dir / "index.html"
    for page in (html_path, *(config.output_dir / "review").glob("*/index.html")):
        html = page.read_text(encoding="utf-8")
        text = re.sub(r"<style>.*?</style>|<script>.*?</script>|<[^>]+>", " ", html, flags=re.S)
        assert '<html lang="en">' in html
        assert _french_words(text) == [], page
    standard = html_path.read_text(encoding="utf-8")
    assert "Hydraulic properties" in standard
    assert "Simulation HTML report" in standard
    assert "Test - catchment report" in standard


def _write_geology(path: Path, code: str) -> None:
    import geopandas as gpd
    from shapely.geometry import box

    gpd.GeoDataFrame(
        {"CODE_LEG": [code], "NOTATION": ["g1"], "DESCR": ["granite"]},
        geometry=[box(0, 0, 2000, 2000)],
        crs="EPSG:2154",
    ).to_file(path, driver="GPKG")


def _write_watershed(folder: Path) -> Path:
    import geopandas as gpd
    from shapely.geometry import box

    folder.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame(geometry=[box(500, 500, 1500, 1500)], crs="EPSG:2154").to_file(
        folder / "watershed.shp"
    )
    return folder


def test_the_geology_legend_is_read_from_the_file_the_report_names(tmp_path: Path) -> None:
    pytest.importorskip("geopandas")
    geology = tmp_path / "map.gpkg"
    _write_geology(geology, "7")
    scratch = _write_watershed(tmp_path / "geographic")

    rows = geology_legend_rows(scratch, geology)

    assert [row["code"] for row in rows] == ["7"]
    assert rows[0]["description"] == "granite"
    assert rows[0]["area_km2"] == "1.00"


def test_the_geology_legend_falls_back_on_the_data_folder(tmp_path: Path) -> None:
    pytest.importorskip("geopandas")
    data = tmp_path / "data"
    (data / "geology").mkdir(parents=True)
    _write_geology(data / "geology" / "geology_brgm_50k_abc123.gpkg", "9")
    scratch = _write_watershed(tmp_path / "geographic")

    assert [path.name for path in geology_cache_candidates(data)] == [
        "geology_brgm_50k_abc123.gpkg"
    ]
    assert [row["code"] for row in geology_legend_rows(scratch, data_dir=data)] == ["9"]


def test_without_a_geology_file_the_legend_is_empty(tmp_path: Path) -> None:
    assert geology_legend_rows(tmp_path / "geographic") == ()
    assert geology_cache_candidates(None) == []


def test_a_relative_dem_is_read_from_the_folder_of_the_simulation_file(tmp_path: Path) -> None:
    scratch = tmp_path / "geographic"

    assert context_dem_path({"dem": "data/dem.tif"}, scratch, tmp_path) == tmp_path / "data/dem.tif"
    assert context_dem_path({}, scratch, tmp_path) == scratch / "watershed_box_buff_dem.tif"


def test_a_missing_observed_discharge_file_is_named_in_a_warning(tmp_path: Path) -> None:
    import logging

    parent = get_logger("hydromodpy")
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture(level=logging.WARNING)
    parent.addHandler(handler)
    try:
        assert _observed_series(tmp_path / "missing.csv") is None
    finally:
        parent.removeHandler(handler)

    assert any("missing.csv" in record.getMessage() for record in records)
    assert _observed_series(None) is None


@dataclass(frozen=True)
class _Config:
    output_dir: Path
    preset: CatchmentReportPreset
    artifact_specs: tuple | None = None


def _write_manifest(output_dir: Path, copied: dict[str, Path]) -> None:
    payload = {
        "expected_figure_ids": ["alpha", "beta"],
        "copied_figures": {key: str(path) for key, path in copied.items()},
    }
    output_dir.mkdir(parents=True)
    (output_dir / "block_report_manifest.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def _config(output_dir: Path) -> _Config:
    preset = CatchmentReportPreset(
        name="test",
        artifact_specs=(
            artifact_spec("alpha", artifact_candidate("context_assets", "alpha.png")),
            artifact_spec("beta", artifact_candidate("context_assets", "beta.png")),
        ),
        block_specs=(),
    )
    return _Config(output_dir=output_dir, preset=preset)


def test_postflight_report_lists_present_and_missing_figures(tmp_path) -> None:
    alpha = tmp_path / "alpha.png"
    alpha.write_text("png", encoding="utf-8")
    _write_manifest(tmp_path / "report", {"alpha": alpha})

    postflight_path = write_figure_postflight_report(_config(tmp_path / "report"), strict=False)

    payload = json.loads(postflight_path.read_text(encoding="utf-8"))
    assert payload["expected_count"] == 2
    assert payload["present_figures"] == ["alpha"]
    assert payload["missing_figures"] == ["beta"]
    assert payload["missing_count"] == 1
    assert payload["dangling_count"] == 0


def test_strict_postflight_fails_on_missing_figures(tmp_path) -> None:
    _write_manifest(tmp_path / "report", {})

    with pytest.raises(CatchmentReportPostflightError) as exc_info:
        write_figure_postflight_report(_config(tmp_path / "report"), strict=True)

    assert "alpha" in str(exc_info.value)
    assert "beta" in str(exc_info.value)
    assert (tmp_path / "report" / "block_report_postflight.json").exists()


def test_a_strict_postflight_failure_exits_as_a_refused_input(tmp_path) -> None:
    from hydromodpy.cli.helpers import EXIT_VALIDATION, exit_code_for

    _write_manifest(tmp_path / "report", {})

    with pytest.raises(CatchmentReportPostflightError) as exc_info:
        write_figure_postflight_report(_config(tmp_path / "report"), strict=True)

    assert exit_code_for(exc_info.value) == EXIT_VALIDATION


def test_postflight_reports_dangling_copied_paths(tmp_path) -> None:
    missing_path = tmp_path / "missing.png"
    _write_manifest(tmp_path / "report", {"alpha": missing_path, "beta": missing_path})

    postflight_path = write_figure_postflight_report(_config(tmp_path / "report"), strict=False)

    payload = json.loads(postflight_path.read_text(encoding="utf-8"))
    assert payload["missing_figures"] == []
    assert payload["dangling_figures"] == ["alpha", "beta"]
    assert payload["dangling_count"] == 2


def test_an_optional_figure_is_not_expected_when_the_manifest_names_none(tmp_path) -> None:
    from hydromodpy.display.catchment_report.blocks import (
        BlockFigureSpec,
        ReportBlockSpec,
    )

    preset = CatchmentReportPreset(
        name="test",
        artifact_specs=(
            artifact_spec("alpha", artifact_candidate("context_assets", "alpha.png")),
            artifact_spec("beta", artifact_candidate("context_assets", "beta.png")),
        ),
        block_specs=(
            ReportBlockSpec(
                block_id="b",
                title="B",
                lead="",
                content_key="b",
                figures=(
                    BlockFigureSpec("compact", "alpha", "Alpha"),
                    BlockFigureSpec("compact", "beta", "Beta", required=False),
                ),
            ),
        ),
    )
    output_dir = tmp_path / "report"
    output_dir.mkdir()
    (output_dir / "block_report_manifest.json").write_text("{}", encoding="utf-8")

    path = write_figure_postflight_report(_Config(output_dir, preset), strict=False)

    assert json.loads(path.read_text(encoding="utf-8"))["expected_figures"] == ["alpha"]


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

[layout]
watershed_project_dir = "."
""".lstrip(),
        encoding="utf-8",
    )

    settings = CatchmentReportSettings.from_toml(config_path)
    inputs = CatchmentReportInputs.from_settings(settings)

    assert settings.layout.context_summary_name is None
    assert settings.layout.transient_config_name is None
    assert settings.layout.overview_config_name is None
    assert settings.pipeline.run_simulation is False
    assert settings.pipeline.build_report_html is True
    assert settings.pipeline.strict_figure_postflight is False
    assert not hasattr(settings, "simulation_export")

    run = tmp_path / "runs" / "transient_nwt"
    assert inputs.run_dir == run
    assert inputs.output_dir == run / "report"
    assert inputs.context_summary == (
        run / "report" / "context" / "test_basin_gauged_context_summary.json"
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

[layout]
watershed_project_dir = "."

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

[layout]
watershed_project_dir = "."
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
    no_layout.write_text('[report]\nsite_label = "T"\nstation_label = "S"\n', encoding="utf-8")
    with pytest.raises(ConfigValidationError, match="layout"):
        CatchmentReportSettings.from_toml(no_layout)

    no_station = tmp_path / "no_station.toml"
    no_station.write_text(
        '[report]\nsite_label = "T"\n[layout]\nwatershed_project_dir = "."\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigValidationError, match="station_label"):
        CatchmentReportSettings.from_toml(no_station)


@pytest.mark.parametrize(
    ("table", "key"), [("report", "output_dir"), ("layout", "context_outputs_dir")]
)
def test_a_retired_output_folder_is_refused_by_name(tmp_path, table, key) -> None:
    """The report is written into the run it describes: no folder of its own is accepted."""
    config_path = _write_report_file(tmp_path)
    text = config_path.read_text(encoding="utf-8").replace(
        f"[{table}]\n", f'[{table}]\n{key} = "elsewhere"\n'
    )
    config_path.write_text(text, encoding="utf-8")

    with pytest.raises(ConfigValidationError, match=f"'{key}' is not accepted any more") as raised:
        CatchmentReportSettings.from_toml(config_path)

    assert "runs/<simulation_name>/report/" in str(raised.value)


def test_an_unknown_preset_is_refused_at_load(tmp_path) -> None:
    config_path = _write_report_file(tmp_path)
    text = config_path.read_text(encoding="utf-8").replace(
        'station_label = "Test outlet"', 'station_label = "Test outlet"\npreset = "made_up"'
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
