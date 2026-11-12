"""A refinement zone is a vector layer, or the pixels where a field passes a threshold.

The table reads like the layer one: ``where`` names the field, ``below`` or
``above`` the threshold, ``run`` the earlier run a field of a run comes from. A
layer is read in the project CRS from the data directory or beside the
configuration; a zone drawn by a threshold reads the DEM, the traced network
or the field of an earlier run, and is left out where the engine sizes nothing.

A field of an earlier run reaches the planner as its extremes over time, per
cell. A threshold is passed when the field went below it, or above it, at some
time step, and never on a cell where the field was undefined. The cells the
threshold selects mark the pixels of the DEM grid whose center they hold, and
a cell smaller than a pixel still marks the pixel under it.
"""

from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from pyogrio.errors import DataSourceError
from shapely.geometry import LineString, Polygon, box

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.mesh.planning.refinement_zones import (
    CriterionInputs,
    RunFieldEnvelope,
    cells_on_grid,
    load_refinement_zones,
)
from hydromodpy.mesh.planning.size_field import PixelRegion
from hydromodpy.mesh.refinement_config import RefinementZoneConfig
from tests._helpers.mesh_cases import grid_spec

_GRID = grid_spec(100, 100, 10.0)
_THALWEG_X = 505.0
_STREAM = LineString([(_THALWEG_X, 995.0), (_THALWEG_X, 5.0)])
_HAND = {"where": "height_above_stream", "below": 2.0, "cell_size": 20.0}
_RUN_ZONE = {"where": "watertable_depth", "below": 1.0, "run": "coarse", "cell_size": 20.0}
_SIM_ID = "0123456789abcdef0123456789abcdef"
_VERTICES = np.array([[0, 0], [500, 0], [1000, 0], [1000, 1000], [500, 1000], [0, 1000]], float)
_HALVES = np.array([[0, 1, 4, 5], [1, 2, 3, 4]])


def _valley() -> np.ndarray:
    """A V valley whose thalweg runs north-south at x = 505 m, 0.1 m of rise per meter."""
    x = _GRID.xmin + _GRID.dx * (np.arange(_GRID.ncol) + 0.5)
    y = _GRID.ymax - _GRID.dy * (np.arange(_GRID.nrow) + 0.5)
    return 100.0 + 0.1 * np.abs(x[None, :] - _THALWEG_X) + 0.01 * y[:, None]


def _envelope() -> RunFieldEnvelope:
    """Two cells, west and east halves; the water table came within 0.5 m of the west one."""
    return RunFieldEnvelope(
        sim_id=_SIM_ID,
        run="coarse",
        field="watertable_depth",
        unit="m",
        vertices=_VERTICES,
        connectivity=_HALVES,
        minimum=np.array([0.5, 3.0]),
        maximum=np.array([4.0, 6.0]),
    )


def _criteria(*, streams: bool = True) -> CriterionInputs:
    return CriterionInputs(
        grid=_GRID,
        elevation=_valley(),
        stream_lines=(_STREAM,) if streams else None,
        run_fields={("coarse", "watertable_depth"): _envelope()},
    )


def _zones(*tables: dict, criteria: CriterionInputs | None, **where: Path | None) -> tuple:
    return load_refinement_zones(
        [RefinementZoneConfig.model_validate(table) for table in tables],
        config_dir=where.get("config_dir"),
        data_dir=where.get("data_dir"),
        crs_wkt="EPSG:2154",
        criteria=criteria,
    )


def _layer(path: Path, *geometries, crs: str | None = "EPSG:2154") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame(geometry=list(geometries), crs=crs).to_file(path)
    return path


def test_stream_height_zone() -> None:
    (zone,) = _zones(_HAND, criteria=_criteria())

    assert isinstance(zone.region, PixelRegion)
    columns = np.flatnonzero(zone.region.mask.all(axis=0))
    assert columns.tolist() == [49, 50, 51]
    assert zone.region.mask.sum() == 3 * _GRID.nrow
    assert zone.source_run is None
    assert zone.cell_size_m == _HAND["cell_size"] and zone.ramp_m == 2.0 * _HAND["cell_size"]


def test_run_field_zone() -> None:
    (shallow,) = _zones(_RUN_ZONE, criteria=_criteria())
    (deep,) = _zones({**_RUN_ZONE, "below": None, "above": 5.0}, criteria=_criteria())

    assert shallow.source_run == _SIM_ID
    assert shallow.region.mask[:, :50].all() and not shallow.region.mask[:, 50:].any()
    assert deep.region.mask[:, 50:].all() and not deep.region.mask[:, :50].any()


CRITERIA_REFUSALS = [
    pytest.param(
        _HAND, False, r"\[geographic.river_network\]", id="stream height without a network"
    ),
    pytest.param({**_RUN_ZONE, "run": "other"}, True, "read no such field", id="run not read"),
]


@pytest.mark.parametrize(("table", "streams", "message"), CRITERIA_REFUSALS)
def test_criteria_refusals(table, streams, message) -> None:
    with pytest.raises(MeshRequestError, match=message):
        _zones(table, criteria=_criteria(streams=streams))


def test_empty_zone_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    nowhere = {**_RUN_ZONE, "below": 0.1}

    with caplog.at_level("WARNING"):
        (zone,) = _zones(nowhere, criteria=_criteria())

    assert zone.region.is_empty
    assert zone.source_run == _SIM_ID
    assert any(zone.label in record.getMessage() for record in caplog.records)


def test_no_criteria_keeps_layer_zone(tmp_path: Path) -> None:
    # An engine that does not grade its cells reads no field: only the layer zone stays.
    path = _layer(tmp_path / "zone.geojson", box(600.0, 600.0, 700.0, 700.0))

    zones = _zones(_HAND, {"path": str(path), "cell_size": 15.0}, criteria=None)

    (zone,) = zones
    assert zone.label == RefinementZoneConfig(path=path, cell_size=15.0).describe()


def test_layer_lookup_folders(tmp_path: Path) -> None:
    geometries = (box(600.0, 600.0, 700.0, 700.0), LineString([(100.0, 100.0), (200.0, 300.0)]))
    source = _layer(tmp_path / "data" / "refinement_zone" / "zones.geojson", *geometries)
    shutil.copy(source, tmp_path / "copy.geojson")

    (by_data_dir,) = _zones(
        {"path": "zones.geojson", "cell_size": 15.0},
        criteria=None,
        config_dir=tmp_path,
        data_dir=tmp_path / "data",
    )
    (by_config_dir,) = _zones(
        {"path": "copy.geojson", "cell_size": 15.0}, criteria=None, config_dir=tmp_path
    )
    (by_absolute_path,) = _zones({"path": str(source), "cell_size": 15.0}, criteria=None)

    assert by_data_dir.region.equals(by_config_dir.region)
    assert by_absolute_path.region.equals(by_data_dir.region)
    assert by_data_dir.ramp_m == 2.0 * 15.0


@pytest.mark.filterwarnings("ignore:'crs' was not provided")
def test_layer_without_crs(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    # A GeoJSON always reads as WGS 84, so the layer is a GeoPackage.
    path = _layer(tmp_path / "zones.gpkg", box(600.0, 600.0, 700.0, 700.0), crs=None)

    with caplog.at_level("WARNING", logger="hydromodpy.mesh.planning.refinement_zones"):
        (zone,) = _zones({"path": str(path), "cell_size": 15.0}, criteria=None)

    assert zone.region.equals(box(600.0, 600.0, 700.0, 700.0))
    assert [str(path) in record.getMessage() for record in caplog.records] == [True]


def test_layer_without_geometry(tmp_path: Path) -> None:
    path = tmp_path / "empty.geojson"
    gpd.GeoDataFrame(geometry=[None], crs="EPSG:2154").to_file(path, driver="GeoJSON")

    with pytest.raises(MeshRequestError, match="no usable geometry"):
        _zones({"path": str(path), "cell_size": 15.0}, criteria=None)


def test_layer_without_area(tmp_path: Path) -> None:
    flat = [Polygon([(600.0, y), (700.0, y), (650.0, y)]) for y in (600.0, 700.0)]
    path = _layer(tmp_path / "flat.gpkg", *flat)

    with pytest.raises(MeshRequestError, match="gives an empty region"):
        _zones({"path": str(path), "cell_size": 15.0}, criteria=None)


@pytest.mark.parametrize("data_dir", [True, False], ids=["data directory", "no directory"])
def test_missing_layer_named(tmp_path: Path, data_dir: bool) -> None:
    first = tmp_path / "data" / "refinement_zone" / "missing.gpkg" if data_dir else "missing.gpkg"

    with pytest.raises(DataSourceError, match=str(first)):
        _zones(
            {"path": "missing.gpkg", "cell_size": 15.0},
            criteria=None,
            data_dir=tmp_path / "data" if data_dir else None,
        )


def test_envelope_passing() -> None:
    envelope = dataclasses.replace(
        _envelope(), minimum=np.array([np.nan, 0.2]), maximum=np.array([np.nan, 0.9])
    )

    assert envelope.passing(below=0.5, above=None).tolist() == [False, True]
    assert envelope.passing(below=None, above=0.5).tolist() == [False, True]


@pytest.mark.parametrize(
    ("minimum", "maximum"),
    [([0.5], [4.0]), ([0.5, 3.0], [4.0]), ([0.5, 3.0, 1.0], [4.0, 6.0, 2.0])],
    ids=["one value", "maxima short", "one value too many"],
)
def test_extremes_length_refused(minimum, maximum) -> None:
    with pytest.raises(MeshRequestError, match="for 2 cells"):
        dataclasses.replace(_envelope(), minimum=np.array(minimum), maximum=np.array(maximum))


def test_no_cell_no_pixel() -> None:
    assert not cells_on_grid(_VERTICES, _HALVES, np.array([False, False]), _GRID).any()
