"""Extent a data source asks over, with its CRS (bounds in m for EPSG:2154, degrees for EPSG:4326).

A mask file says which CRS its bounds are in, and the reprojection uses that
one. A raster mask is read on its valid cells, not on its footprint. No manager
takes a project-scoped ``geographic`` object to find where to fetch.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin
from shapely.geometry import Polygon, box
from shapely.ops import transform

from hydromodpy.core.exceptions import DataRequestError
from hydromodpy.data.common.source_extent import (
    PROJECT_EXTENT_CRS,
    mask_extent,
    mask_extent_in,
    mask_geometry,
    mask_geometry_wgs84,
    resolve_source_extent,
)
from hydromodpy.data.loading.store import DataStore
from hydromodpy.data.source.port import Extent
from hydromodpy.data.variables.dem.config import DemConfig, IgnGeoplateformeDemSource
from hydromodpy.data.variables.dem.variable import DemVariable
from hydromodpy.data.variables.geology.variable import GeologyVariable
from hydromodpy.data.variables.oceanic.variable import OceanicVariable

# A one-kilometer square near Rennes, in Lambert-93 meters and in the WGS84
# degrees the same ground occupies.
RENNES_2154 = (350000.0, 6790000.0, 351000.0, 6791000.0)
RENNES_4326 = (-1.7068965, 48.1164744, -1.6926817, 48.1259921)

# Five vertices of a basin-shaped mask, in Lambert-93 meters.
BASIN = Polygon(
    [
        (372000.0, 6835000.0),
        (388000.0, 6832000.0),
        (392000.0, 6845000.0),
        (378000.0, 6851000.0),
        (370000.0, 6843000.0),
    ]
)


class Source:
    """The two attributes ``resolve_source_extent`` reads."""

    def __init__(self, *, mask_path=None, extent=None):
        self.mask_path = mask_path
        self.extent = extent


def write_vector_mask(path, bbox, crs):
    gpd.GeoDataFrame(geometry=[box(*bbox)], crs=crs).to_file(path)
    return path


def write_raster_mask(path, bbox, crs, values=None):
    """A mask raster, with every cell valid when ``values`` is not given."""
    size = 4 if values is None else values.shape[0]
    xmin, ymin, xmax, ymax = bbox
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=size,
        width=size,
        count=1,
        dtype="uint8",
        crs=crs,
        nodata=0,
        transform=from_origin(xmin, ymax, (xmax - xmin) / size, (ymax - ymin) / size),
    ) as dst:
        dst.write(np.ones((size, size), dtype="uint8") if values is None else values, 1)
    return path


def write_dem_tile(path, bbox):
    """A one-cell DEM at 17 m in Lambert-93, standing for an IGN download."""
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=1,
        width=1,
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        transform=from_origin(bbox[0], bbox[3], 5.0, 5.0),
        nodata=-9999.0,
    ) as dst:
        dst.write(np.full((1, 1), 17.0, dtype="float32"), 1)


MASKS = [
    pytest.param(write_vector_mask, "mask.gpkg", id="vector"),
    pytest.param(write_raster_mask, "mask.tif", id="raster"),
]


@pytest.mark.parametrize(("write_mask", "name"), MASKS)
def test_mask_reports_its_crs(write_mask, name, tmp_path):
    path = write_mask(tmp_path / name, RENNES_2154, "EPSG:2154")

    extent = mask_extent(path)

    assert extent.crs.upper().endswith("2154")
    assert extent.bbox == pytest.approx(RENNES_2154, abs=1e-6)


def test_raster_mask_valid_cells(tmp_path):
    # The catchment mask is 1 on the catchment and nodata elsewhere, in a
    # rectangle sized to the accumulation grid. Here the valid cells are the
    # central quarter of a 100 m square.
    values = np.zeros((10, 10), dtype="uint8")
    values[3:7, 3:7] = 1
    path = write_raster_mask(
        tmp_path / "catchment.tif", (0.0, 0.0, 100.0, 100.0), "EPSG:2154", values
    )

    extent = mask_extent(path)

    assert extent.bbox == pytest.approx((30.0, 30.0, 70.0, 70.0), abs=1e-6)


def test_mask_wins_over_project_extent(tmp_path):
    path = write_vector_mask(tmp_path / "mask.gpkg", RENNES_2154, "EPSG:2154")
    source = Source(mask_path=path, extent="watershed")

    extent = resolve_source_extent(source, project_extent=(0.0, 0.0, 1.0, 1.0))

    assert extent.bbox == pytest.approx(RENNES_2154, abs=1e-6)


def test_project_extent_crs():
    extent = resolve_source_extent(Source(extent="study_area"), project_extent=RENNES_2154)

    assert extent.crs == PROJECT_EXTENT_CRS
    assert extent.bbox == pytest.approx(RENNES_2154, abs=1e-6)


def test_mask_reprojected_from_own_crs(tmp_path, monkeypatch):
    # A WGS84 mask must leave for IGN as Lambert-93 meters over Rennes, not as
    # degrees read as meters.
    captured = {}

    def fake_fetch_ign_dem(*, output_dir, bbox, **_kwargs):
        captured["bbox"] = bbox
        path = Path(output_dir) / "dem.tif"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_dem_tile(path, bbox)
        return path

    monkeypatch.setattr(
        "hydromodpy.data.variables.dem.apis.ign_dem_fr.fetch_ign_dem", fake_fetch_ign_dem
    )
    path = write_vector_mask(tmp_path / "mask.gpkg", RENNES_4326, "EPSG:4326")
    DemVariable(
        config=DemConfig(sources=[IgnGeoplateformeDemSource(mask_path=path)]),
        index=None,
        data_dir=tmp_path / "dem",
    ).load()

    assert captured["bbox"] == pytest.approx(RENNES_2154, abs=200.0)


def test_extent_measured_on_the_shape(tmp_path):
    # The bounds of a reprojected polygon are the image of its own vertices.
    # The bounds of a reprojected box are the image of a rectangle around it,
    # which is wider, and a wider box forces a download the cache could serve.
    path = tmp_path / "basin.gpkg"
    gpd.GeoDataFrame(geometry=[BASIN], crs="EPSG:2154").to_file(path)

    on_shape = mask_extent_in(path, "EPSG:4326")
    on_box = mask_extent(path).to_crs("EPSG:4326")

    assert on_shape.crs == "EPSG:4326"
    assert on_box.xmin < on_shape.xmin
    assert on_box.ymin < on_shape.ymin
    assert on_shape.xmax < on_box.xmax
    assert on_shape.ymax < on_box.ymax
    expected = gpd.GeoSeries([BASIN], crs="EPSG:2154").to_crs("EPSG:4326").total_bounds
    assert on_shape.bbox == pytest.approx(tuple(expected))


def test_mask_in_target_crs_unchanged(tmp_path):
    shape = Polygon([(-1.8, 48.0), (-1.5, 48.0), (-1.5, 48.3), (-1.8, 48.3)])
    path = tmp_path / "mask.gpkg"
    gpd.GeoDataFrame(geometry=[shape], crs="EPSG:4326").to_file(path)

    assert mask_extent_in(path, "EPSG:4326").bbox == pytest.approx((-1.8, 48.0, -1.5, 48.3))


def test_raster_mask_wgs84_hull(tmp_path):
    values = np.zeros((10, 10), dtype="uint8")
    values[2:8, 3:6] = 1
    path = write_raster_mask(tmp_path / "catchment.tif", RENNES_2154, "EPSG:2154", values)
    hull, crs = mask_geometry(path)
    transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)

    assert mask_geometry_wgs84(path).equals_exact(
        transform(transformer.transform, hull), tolerance=0.0
    )


def test_geojson_mask(tmp_path):
    path = tmp_path / "mask.geojson"
    gpd.GeoDataFrame(geometry=[box(-2.0, 47.0, -1.0, 49.0)], crs="EPSG:4326").to_file(
        path, driver="GeoJSON"
    )

    geometry, _ = mask_geometry(path)

    assert geometry.bounds[0] == pytest.approx(-2.0)
    assert geometry.bounds[3] == pytest.approx(49.0)


def test_wgs84_mask_without_crs(tmp_path):
    # The station path never refused a CRS-less mask. The native path does.
    path = tmp_path / "mask.shp"
    gpd.GeoDataFrame(geometry=[box(*RENNES_4326)]).to_file(path)
    path.with_suffix(".prj").unlink(missing_ok=True)
    assert gpd.read_file(path).crs is None

    assert mask_geometry_wgs84(path).bounds == pytest.approx(RENNES_4326)
    with pytest.raises(DataRequestError, match="declares no CRS"):
        mask_geometry(path)


@pytest.mark.parametrize("manager_cls", [DemVariable, GeologyVariable, OceanicVariable])
def test_variable_refuses_geographic(manager_cls):
    with pytest.raises(TypeError, match="geographic"):
        manager_cls(config=None, index=None, geographic=object())


def test_load_path_takes_no_kwargs():
    params = inspect.signature(DataStore.load_variable).parameters

    assert not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def test_mask_without_crs_refused(tmp_path):
    path = write_vector_mask(tmp_path / "mask.gpkg", RENNES_2154, None)

    with pytest.raises(DataRequestError, match="declares no CRS"):
        mask_extent(path)


def test_missing_mask_names_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="absent.gpkg"):
        mask_extent(tmp_path / "absent.gpkg")


def test_missing_mask_geometry():
    with pytest.raises(FileNotFoundError):
        mask_geometry(Path("/nonexistent.shp"))


def test_unsupported_mask_format(tmp_path):
    path = tmp_path / "mask.xyz"
    path.write_text("dummy")

    with pytest.raises(ValueError, match="Unsupported mask format"):
        mask_geometry(path)


def test_unknown_crs_refused():
    extent = Extent(xmin=0.0, ymin=0.0, xmax=1.0, ymax=1.0, crs="not a crs")

    with pytest.raises(DataRequestError, match="Cannot resolve a CRS"):
        extent.to_crs("EPSG:4326")
