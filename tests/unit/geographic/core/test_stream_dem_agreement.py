"""Measure how far the computed D8 paths stray from the mapped stream network.

The D8 code table must be the one the solver writes. ``D8_WBT_OFFSETS`` once
declared the ESRI encoding while Whitebox writes its own, the same eight octants
rotated by one, and alpha sat near 0.45 where it is 1.0 by construction. Two
tests hold the table, because either alone can be satisfied by a wrong one.
"""

import json
import logging
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, box

from hydromodpy.spatial.geographic.core.stream_dem_agreement import (
    measure_network_dem_agreement,
    read_network_map,
    report_network_dem_agreement,
)
from hydromodpy.spatial.terrain.port import D8_WBT_OFFSETS
from tests._helpers.geographic_cases import read_band, write_features
from tests._helpers.geotiffs import write_geotiff

_N, _RES = 20, 10.0
# Down the middle of column 10, from the north edge to the south edge.
_STREAM = LineString([(105.0, 195.0), (105.0, 5.0)])
_DECOY = LineString([(15.0, 195.0), (15.0, 5.0)])
_FAR = LineString([(50_000.0, 50_000.0), (50_100.0, 50_100.0)])


def _write_inputs(tmp_path, code: int):
    """A D8 raster of 10 m cells from (0, 200), every cell pointing the same way."""
    pointer = np.full((_N, _N), code, dtype="int16")
    d8 = write_geotiff(tmp_path / "direc.tif", pointer, cell=_RES, nodata=-32768)
    watershed = write_features(tmp_path / "watershed.shp", [box(0.0, 0.0, _N * _RES, _N * _RES)])
    return str(d8), str(watershed)


def _plant_network(path, line: LineString):
    path.parent.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame(geometry=[line], crs="EPSG:2154").to_file(path, driver="GPKG")
    return path


@pytest.mark.parametrize("code", [8, 4], ids=["due south", "south-east"])
def test_agreement_is_one_only_while_the_paths_never_leave_the_network(tmp_path, code) -> None:
    # Due south (WBT code 8), the closure of the trace down column 10 is that
    # column. South-east (code 4) walks off it at the first step, a staircase.
    d8, watershed = _write_inputs(tmp_path, code)
    agreement = measure_network_dem_agreement(
        d8_pointer_path=d8, watershed_shp=watershed, stream_lines=[_STREAM]
    )
    assert agreement.n_network_cells == _N
    if code == 8:
        assert agreement.n_closure_cells == _N
        assert agreement.alpha == pytest.approx(1.0)
    else:
        assert agreement.n_closure_cells > _N
        assert agreement.alpha < 1.0


@pytest.mark.parametrize(
    ("lines", "reason"),
    [([_FAR], "do not share a single cell"), ([], "no stream geometry")],
    ids=["outside the catchment", "no geometry"],
)
def test_a_network_that_cannot_be_measured_raises(tmp_path, lines, reason) -> None:
    d8, watershed = _write_inputs(tmp_path, 8)
    with pytest.raises(ValueError, match=reason):
        measure_network_dem_agreement(
            d8_pointer_path=d8, watershed_shp=watershed, stream_lines=lines
        )


def test_the_map_is_read_from_the_file_it_names_and_a_relative_one_says_so(
    tmp_path, monkeypatch, caplog
) -> None:
    # A configuration built without the loader keeps the declared value. It is
    # still read, but the working-directory read is announced, not silent.
    named = _plant_network(tmp_path / "project" / "streams.gpkg", _STREAM)
    _plant_network(tmp_path / "elsewhere" / "streams.gpkg", _DECOY)
    monkeypatch.chdir(tmp_path / "elsewhere")
    with caplog.at_level(logging.WARNING):
        lines = read_network_map(named, "EPSG:2154")
        assert "working directory" not in caplog.text
        relative = read_network_map("streams.gpkg", "EPSG:2154")
    assert len(lines) == 1
    assert lines[0].equals(_STREAM)
    assert relative[0].equals(_DECOY)
    assert "working directory" in caplog.text
    with pytest.raises(FileNotFoundError, match="streams.gpkg"):
        read_network_map(tmp_path / "data" / "hydrography" / "streams.gpkg", "EPSG:2154")


def _report_inputs(tmp_path, *, code: int):
    d8, watershed = _write_inputs(tmp_path, code)
    paths = SimpleNamespace(watershed_shp=watershed, geographic_path=str(tmp_path / "geographic"))
    setup = SimpleNamespace(crs_project="EPSG:2154", paths=paths)
    return setup, _plant_network(tmp_path / "streams.gpkg", _STREAM), d8


def test_alpha_is_journaled_without_a_burn_key_and_only_with_a_map(tmp_path) -> None:
    setup, network, d8 = _report_inputs(tmp_path, code=8)
    journal = tmp_path / "geographic" / "stream_dem_agreement.json"
    assert report_network_dem_agreement(setup, network_map_path=None, d8_pointer_path=d8) is None
    assert not journal.exists()
    agreement = report_network_dem_agreement(setup, network_map_path=network, d8_pointer_path=d8)
    assert agreement is not None
    assert agreement.alpha == pytest.approx(1.0)
    assert set(json.loads(journal.read_text())) == {"n_network_cells", "n_closure_cells", "alpha"}


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


# Whitebox's non-ESRI pointer, clockwise from the north-east:
#     64 128   1
#     32   X   2
#     16   8   4
CARDINALS = {
    "east": ((0, 1), 2),
    "south": ((1, 0), 8),
    "west": ((0, -1), 32),
    "north": ((-1, 0), 128),
}


@pytest.fixture(scope="module")
def backend():
    pytest.importorskip("whitebox_workflows")
    from tests._helpers.whitebox import configure_whitebox_single_thread

    monkeypatch = pytest.MonkeyPatch()
    try:
        configure_whitebox_single_thread(monkeypatch)
        from hydromodpy.spatial.delineation import get_whitebox_backend

        yield get_whitebox_backend()
    finally:
        monkeypatch.undo()


def _pointer_of(backend, tmp_path, surface: np.ndarray) -> np.ndarray:
    dem = write_geotiff(tmp_path / "dem.tif", surface.astype("float32"), cell=25.0, nodata=-9999.0)
    backend.flow.d8_pointer(str(dem), str(tmp_path / "direc.tif"))
    return read_band(tmp_path / "direc.tif")


@pytest.mark.xdist_group(name="whitebox_backend")
@pytest.mark.parametrize("direction", sorted(CARDINALS))
def test_the_table_matches_the_code_whitebox_writes(direction, backend, tmp_path) -> None:
    offset, expected_code = CARDINALS[direction]
    rows, cols = np.mgrid[0:40, 0:40]
    # Fall by one metre per cell in the wanted direction.
    codes = _pointer_of(backend, tmp_path, 100.0 - (offset[0] * rows + offset[1] * cols))
    # Drop the frame: an edge cell has no downslope neighbour to point at.
    inner = codes[5:-5, 5:-5]
    values, counts = np.unique(inner[inner > 0], return_counts=True)
    dominant = int(values[np.argmax(counts)])
    assert dominant == expected_code, f"a plane falling {direction} is coded {dominant}"
    assert D8_WBT_OFFSETS[expected_code] == offset


@pytest.mark.xdist_group(name="whitebox_backend")
def test_a_valley_floor_closed_under_descent_has_an_alpha_of_one(backend, tmp_path) -> None:
    """The regression the rotated table failed: it measured 0.45 on a network that
    cannot, by construction, leave itself. The floor is used rather than an
    accumulation threshold so the test depends on the pointer alone."""
    size, floor = 60, 30
    rows, cols = np.mgrid[0:size, 0:size]
    # A V-shaped valley draining south: every floor cell descends to the next one.
    codes = _pointer_of(backend, tmp_path, 100.0 - rows * 0.5 + np.abs(cols - floor) * 2.0)
    d8 = write_geotiff(tmp_path / "codes.tif", codes, cell=25.0)
    watershed = write_features(tmp_path / "watershed.shp", [box(0.0, 0.0, 1500.0, 1500.0)])
    x = (floor + 0.5) * 25.0
    agreement = measure_network_dem_agreement(
        d8_pointer_path=str(d8),
        watershed_shp=str(watershed),
        stream_lines=[LineString([(x, 1500.0 - 12.5), (x, 12.5)])],
    )
    assert agreement.n_network_cells == size
    assert agreement.alpha == pytest.approx(1.0)
