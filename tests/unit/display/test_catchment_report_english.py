"""The catchment report is written in English, and reads no file of the repository.

Every title, label and caption of the page is English. The geology legend and the
DEM are found from the report file and the user cache, never from a folder of the
HydroModPy source tree.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hydromodpy.display.catchment_report import CatchmentReportConfig, build_catchment_report
from hydromodpy.display.catchment_report.artifacts import (
    context_dem_path,
    geology_cache_candidates,
    geology_legend_rows,
)
from hydromodpy.display.catchment_report.block_specs import DEFAULT_BLOCK_SPECS
from hydromodpy.display.catchment_report.context import _observed_series

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

    for page in (html_path, *(config.output_dir / "web_review").glob("*/index.html")):
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


def test_the_geology_legend_falls_back_on_the_user_cache(tmp_path: Path, monkeypatch) -> None:
    pytest.importorskip("geopandas")
    monkeypatch.setenv("HMP_CACHE_HOME", str(tmp_path / "cache"))
    cache = tmp_path / "cache" / "geology"
    cache.mkdir(parents=True)
    _write_geology(cache / "geology_brgm_50k_abc123.gpkg", "9")
    scratch = _write_watershed(tmp_path / "geographic")

    assert [path.name for path in geology_cache_candidates()] == ["geology_brgm_50k_abc123.gpkg"]
    assert [row["code"] for row in geology_legend_rows(scratch)] == ["9"]


def test_without_a_geology_file_the_legend_is_empty(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HMP_CACHE_HOME", str(tmp_path / "cache"))

    assert geology_legend_rows(tmp_path / "geographic") == ()


def test_a_relative_dem_is_read_from_the_folder_of_the_simulation_file(tmp_path: Path) -> None:
    scratch = tmp_path / "geographic"

    assert context_dem_path({"dem": "data/dem.tif"}, scratch, tmp_path) == tmp_path / "data/dem.tif"
    assert context_dem_path({}, scratch, tmp_path) == scratch / "watershed_box_buff_dem.tif"


def test_a_missing_observed_discharge_file_is_named_in_a_warning(tmp_path: Path) -> None:
    import logging

    from hydromodpy.core.logging import get_logger

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
