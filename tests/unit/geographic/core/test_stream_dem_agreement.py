"""Measure how far the computed D8 paths stray from the mapped stream network.

The D8 code table must be the one the solver actually writes. ``D8_WBT_OFFSETS``
once declared the ESRI encoding while Whitebox writes its own, the same eight
octants rotated by one. Every descent walked beside the talweg, and alpha sat
near 0.45 even on the network the DEM derives from its own pointer, where it is
1.0 by construction. Two tests hold the table, because either alone can be
satisfied by a wrong one.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from shapely.geometry import LineString, box

from hydromodpy.spatial.geographic.core.stream_dem_agreement import (
    measure_network_dem_agreement,
    read_network_map,
    report_network_dem_agreement,
)
from hydromodpy.spatial.terrain.port import D8_WBT_OFFSETS
from tests._helpers.geographic_cases import write_features
from tests._helpers.geotiffs import write_geotiff

_N = 20
_RES = 10.0
# Down the middle of column 10, from the north edge to the south edge.
_STREAM = LineString([(105.0, 195.0), (105.0, 5.0)])


def _write_d8(path: str, code: int) -> None:
    """Top-left (0, 200), 10 m cells, every cell pointing the same way."""
    write_geotiff(path, np.full((_N, _N), code, dtype="int16"), cell=_RES, nodata=-32768)


def _write_catchment(path: str) -> None:
    write_features(path, [box(0.0, 0.0, _N * _RES, _N * _RES)])


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


def _plant_network(path, line: LineString) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame(geometry=[line], crs="EPSG:2154").to_file(path, driver="GPKG")


def _report_inputs(tmp_path, *, code: int):
    network = tmp_path / "streams.gpkg"
    _plant_network(network, _PROJECT_LINE)
    d8 = tmp_path / "direc.tif"
    _write_d8(str(d8), code)
    _write_catchment(str(tmp_path / "watershed.shp"))
    paths = SimpleNamespace(
        watershed_shp=str(tmp_path / "watershed.shp"), geographic_path=str(tmp_path / "geographic")
    )
    return SimpleNamespace(crs_project="EPSG:2154", paths=paths), network, d8


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


def test_a_map_that_cannot_be_measured_is_skipped_and_its_old_journal_removed(
    tmp_path, caplog
) -> None:
    setup, _network, d8 = _report_inputs(tmp_path, code=8)
    far_away = tmp_path / "far.gpkg"
    _plant_network(far_away, LineString([(50_000.0, 50_000.0), (50_100.0, 50_100.0)]))
    journal = tmp_path / "geographic" / "stream_dem_agreement.json"
    journal.parent.mkdir(parents=True)
    journal.write_text("{}")

    with caplog.at_level(logging.WARNING):
        agreement = report_network_dem_agreement(
            setup, network_map_path=far_away, d8_pointer_path=d8
        )

    assert agreement is None
    assert not journal.exists()
    assert "could not be measured" in caplog.text


# ---------------------------------------------------------------------------
# The code table Whitebox writes
# ---------------------------------------------------------------------------

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
    pointer = tmp_path / "direc.tif"
    backend.flow.d8_pointer(str(dem), str(pointer))
    with rasterio.open(pointer) as src:
        return src.read(1)


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
