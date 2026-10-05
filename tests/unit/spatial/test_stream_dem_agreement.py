"""Measure how far the computed D8 paths stray from the mapped stream network."""

from __future__ import annotations

import json
import logging

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, box

from hydromodpy.spatial.geographic.core.stream_dem_agreement import (
    measure_network_dem_agreement,
    read_network_map,
    report_network_dem_agreement,
)

_N = 20
_RES = 10.0
_TRANSFORM = from_origin(0.0, _N * _RES, _RES, _RES)  # top-left (0, 200), 10 m cells
# Down the middle of column 10, from the north edge to the south edge.
_STREAM = LineString([(105.0, 195.0), (105.0, 5.0)])


def _write_d8(path: str, code: int) -> None:
    profile = {
        "driver": "GTiff",
        "height": _N,
        "width": _N,
        "count": 1,
        "dtype": "int16",
        "crs": "EPSG:2154",
        "transform": _TRANSFORM,
        "nodata": -32768,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(np.full((_N, _N), code, dtype="int16"), 1)


def _write_catchment(path: str) -> None:
    gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[box(0.0, 0.0, _N * _RES, _N * _RES)],
        crs="EPSG:2154",
    ).to_file(path)


def _agreement(tmp_path, *, code: int, stream_lines=None):
    d8 = str(tmp_path / "direc.tif")
    catchment = str(tmp_path / "watershed.shp")
    _write_d8(d8, code)
    _write_catchment(catchment)
    return measure_network_dem_agreement(
        d8_pointer_path=d8,
        watershed_shp=catchment,
        stream_lines=[_STREAM] if stream_lines is None else stream_lines,
    )


def test_agreement_is_one_when_the_paths_never_leave_the_network(tmp_path) -> None:
    # Everything flows due south (WBT code 8), so the closure of a north-south
    # trace down column 10 is that column and nothing more.
    agreement = _agreement(tmp_path, code=8)

    assert agreement.n_network_cells == _N
    assert agreement.n_closure_cells == _N
    assert agreement.alpha == pytest.approx(1.0)


def test_agreement_falls_when_the_paths_leave_the_network(tmp_path) -> None:
    # Everything flows south-east (WBT code 4): a trace down column 10 walks off
    # it at the first step, so the closure is a staircase far larger than the
    # trace.
    agreement = _agreement(tmp_path, code=4)

    assert agreement.n_network_cells == _N
    assert agreement.n_closure_cells > _N
    assert agreement.alpha < 1.0


def test_a_network_outside_the_catchment_raises(tmp_path) -> None:
    far_away = [LineString([(50_000.0, 50_000.0), (50_100.0, 50_100.0)])]

    with pytest.raises(ValueError, match="do not share a single cell"):
        _agreement(tmp_path, code=8, stream_lines=far_away)


def test_no_geometry_raises(tmp_path) -> None:
    with pytest.raises(ValueError, match="no stream geometry"):
        _agreement(tmp_path, code=8, stream_lines=[])


# ---------------------------------------------------------------------------
# Reading the map and reporting alpha
# ---------------------------------------------------------------------------

_PROJECT_LINE = LineString([(105.0, 195.0), (105.0, 5.0)])
_DECOY_LINE = LineString([(15.0, 195.0), (15.0, 5.0)])


class _Paths:
    def __init__(self, folder) -> None:
        self.watershed_shp = str(folder / "watershed.shp")
        self.geographic_path = str(folder / "geographic")


class _Setup:
    crs_project = "EPSG:2154"

    def __init__(self, folder) -> None:
        self.paths = _Paths(folder)


def _plant_network(path, line: LineString) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame(geometry=[line], crs="EPSG:2154").to_file(path, driver="GPKG")


def _report_inputs(tmp_path, *, code: int):
    network = tmp_path / "streams.gpkg"
    _plant_network(network, _PROJECT_LINE)
    d8 = tmp_path / "direc.tif"
    _write_d8(str(d8), code)
    _write_catchment(str(tmp_path / "watershed.shp"))
    return _Setup(tmp_path), network, d8


def test_the_map_is_read_from_the_file_it_names_not_the_one_underfoot(
    tmp_path, monkeypatch
) -> None:
    project = tmp_path / "project"
    decoy = tmp_path / "elsewhere"
    _plant_network(project / "streams.gpkg", _PROJECT_LINE)
    _plant_network(decoy / "streams.gpkg", _DECOY_LINE)
    monkeypatch.chdir(decoy)

    lines = read_network_map(project / "streams.gpkg", "EPSG:2154")

    assert len(lines) == 1
    assert lines[0].equals(_PROJECT_LINE)


def test_a_map_that_points_to_nothing_names_the_path(tmp_path) -> None:
    missing = tmp_path / "data" / "hydrography" / "streams.gpkg"

    with pytest.raises(FileNotFoundError, match="streams.gpkg"):
        read_network_map(missing, "EPSG:2154")


def test_a_relative_map_says_it_depends_on_the_working_directory(
    tmp_path, monkeypatch, caplog
) -> None:
    # A configuration built without the loader keeps the declared value. It is
    # still read, but the working-directory read is announced, not silent.
    decoy = tmp_path / "elsewhere"
    _plant_network(decoy / "streams.gpkg", _DECOY_LINE)
    monkeypatch.chdir(decoy)

    with caplog.at_level(logging.WARNING):
        lines = read_network_map("streams.gpkg", "EPSG:2154")

    assert lines[0].equals(_DECOY_LINE)
    assert "working directory" in caplog.text


def test_alpha_does_not_run_without_a_map(tmp_path) -> None:
    setup, _network, d8 = _report_inputs(tmp_path, code=8)

    assert report_network_dem_agreement(setup, network_map_path=None, d8_pointer_path=d8) is None
    assert not (tmp_path / "geographic" / "stream_dem_agreement.json").exists()


def test_alpha_is_journaled_without_a_burn_key(tmp_path) -> None:
    setup, network, d8 = _report_inputs(tmp_path, code=8)

    agreement = report_network_dem_agreement(setup, network_map_path=network, d8_pointer_path=d8)

    assert agreement is not None
    assert agreement.alpha == pytest.approx(1.0)
    journal = json.loads((tmp_path / "geographic" / "stream_dem_agreement.json").read_text())
    assert set(journal) == {"n_network_cells", "n_closure_cells", "alpha"}


def test_alpha_below_the_criterion_default_warns_without_prescribing_a_burn(
    tmp_path, caplog
) -> None:
    setup, network, d8 = _report_inputs(tmp_path, code=4)

    with caplog.at_level(logging.WARNING):
        agreement = report_network_dem_agreement(
            setup, network_map_path=network, d8_pointer_path=d8
        )

    assert agreement is not None and agreement.alpha < 0.90
    assert "Stream/DEM agreement is low" in caplog.text
    assert "burn" not in caplog.text.lower()
