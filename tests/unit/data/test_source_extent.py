"""The extent a raster manager asks over comes from the config, and carries its CRS.

Two claims, and the second is the one that used to be false.

**No manager reads a ``geographic`` object to find out where to fetch.** The
object is project-scoped, and a capability that needs one needs a workspace.
``DemManager`` and ``GeologyManager`` no longer take the parameter at all, and
:func:`test_a_raster_manager_refuses_a_geographic_object` holds that the
mechanism was removed rather than merely left unused.

**A mask says which CRS its bounds are in, and the reprojection uses that one.**
The pair these managers carried resolved a bare bbox from ``mask_path`` and
then reopened ``geographic.watershed_shp`` to learn what frame to reproject it
from. Right while the two files are the same one, wrong the moment a caller
points ``mask_path`` somewhere else --
:func:`test_a_mask_in_its_own_crs_is_reprojected_from_that_crs` is that case,
and the old pair put the request at ``-1.36 E, -5.98 S``, in the Gulf of
Guinea, reading degrees as Lambert-93 metres.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Polygon, box

from hydromodpy.core.exceptions import DataRequestError
from hydromodpy.data.common.source_extent import (
    PROJECT_EXTENT_CRS,
    mask_extent,
    mask_extent_in,
    resolve_source_extent,
)
from hydromodpy.data.variables.dem.config import DemConfig, IgnGeoplateformeDemSource
from hydromodpy.data.variables.dem.manager import DemManager
from hydromodpy.data.variables.geology.manager import GeologyManager

# A one-kilometre square near Rennes, written twice: in Lambert-93 metres and
# in the WGS84 degrees the same ground occupies.
RENNES_2154 = (350000.0, 6790000.0, 351000.0, 6791000.0)
RENNES_4326 = (-1.7068965, 48.1164744, -1.6926817, 48.1259921)


class _Source:
    """The two attributes :func:`resolve_source_extent` reads, and nothing else."""

    def __init__(self, *, mask_path=None, extent=None):
        self.mask_path = mask_path
        self.extent = extent


def _write_vector_mask(path, bbox, crs):
    gpd.GeoDataFrame(geometry=[box(*bbox)], crs=crs).to_file(path)
    return path


def _write_raster_mask(path, bbox, crs, values=None):
    """A mask raster; ``values`` defaults to every cell valid."""
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


@pytest.mark.fast
def test_a_vector_mask_reports_its_own_crs(tmp_path):
    path = _write_vector_mask(tmp_path / "mask.gpkg", RENNES_2154, "EPSG:2154")

    extent = mask_extent(path)

    assert extent.crs.upper().endswith("2154")
    assert extent.bbox == pytest.approx(RENNES_2154, abs=1e-6)


@pytest.mark.fast
def test_a_raster_mask_reports_its_own_crs(tmp_path):
    path = _write_raster_mask(tmp_path / "mask.tif", RENNES_2154, "EPSG:2154")

    extent = mask_extent(path)

    assert extent.crs.upper().endswith("2154")
    assert extent.bbox == pytest.approx(RENNES_2154, abs=1e-6)


@pytest.mark.fast
def test_a_raster_mask_is_read_on_its_valid_cells_and_not_its_footprint(tmp_path):
    """A catchment mask is a rectangle that is mostly nodata.

    ``spatial/terrain/port.py:316``: ``mask_path`` holds ``1`` on the catchment
    and the raster nodata elsewhere, in a rectangle sized to the accumulation
    grid. Reading ``src.bounds`` would hand a provider the whole grid -- here
    the full square instead of the central quarter -- and the fixture of
    :func:`test_a_raster_mask_reports_its_own_crs` cannot tell the two apart,
    being valid everywhere.
    """
    values = np.zeros((10, 10), dtype="uint8")
    values[3:7, 3:7] = 1
    path = _write_raster_mask(
        tmp_path / "catchment.tif", (0.0, 0.0, 100.0, 100.0), "EPSG:2154", values
    )

    extent = mask_extent(path)

    assert extent.bbox == pytest.approx((30.0, 30.0, 70.0, 70.0), abs=1e-6), extent.bbox


@pytest.mark.fast
def test_a_mask_without_a_crs_is_refused(tmp_path):
    """It used to inherit the watershed's, which is a guess and not an answer."""
    path = _write_vector_mask(tmp_path / "mask.gpkg", RENNES_2154, None)

    with pytest.raises(DataRequestError, match="declares no CRS"):
        mask_extent(path)


@pytest.mark.fast
def test_a_missing_mask_says_which_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="absent.gpkg"):
        mask_extent(tmp_path / "absent.gpkg")


@pytest.mark.fast
def test_the_mask_wins_over_the_project_extent(tmp_path):
    """``mask_path`` is the specific answer, and the loader fills it in."""
    path = _write_vector_mask(tmp_path / "mask.gpkg", RENNES_2154, "EPSG:2154")
    source = _Source(mask_path=path, extent="watershed")

    extent = resolve_source_extent(source, project_extent=(0.0, 0.0, 1.0, 1.0))

    assert extent.bbox == pytest.approx(RENNES_2154, abs=1e-6)


@pytest.mark.fast
def test_the_project_extent_is_read_in_the_crs_its_producer_builds():
    source = _Source(extent="study_area")

    extent = resolve_source_extent(source, project_extent=RENNES_2154)

    assert extent.crs == PROJECT_EXTENT_CRS
    assert extent.bbox == pytest.approx(RENNES_2154, abs=1e-6)


@pytest.mark.fast
def test_a_source_naming_neither_resolves_to_nothing():
    """``custom`` sources load a file happily with no extent at all."""
    assert resolve_source_extent(_Source(), project_extent=RENNES_2154) is None
    assert resolve_source_extent(_Source(extent="watershed"), project_extent=None) is None


@pytest.mark.fast
def test_the_project_extent_crs_matches_what_site_selection_builds():
    """Anti-vacuity for the constant, on one branch of its producer.

    ``bbox_for_departments`` is what ``_dem_request_bbox`` returns for a
    territory given as departments, and its module says EPSG:2154. Read back
    through the declared constant, department 35 has to land on
    Ille-et-Vilaine; read as degrees it would land in the Gulf of Guinea.

    **This is one branch of four**, and the net is narrower than it looks:
    ``polygon_file`` reprojects to EPSG:2154 explicitly
    (``_site_selection_dem.py:376``), ``outlets`` is metric by construction of
    the delineation, and ``territory.bbox`` is passed through unreprojected
    with no CRS documented anywhere -- that last one is a footgun this phase
    did not introduce and does not close.
    """
    from hydromodpy.data.common.administrative.france import bbox_for_departments
    from hydromodpy.data.source.port import Extent

    bbox = bbox_for_departments(["35"], margin_m=0.0)
    lonlat = Extent(*bbox, crs=PROJECT_EXTENT_CRS).to_crs("EPSG:4326")

    assert -2.6 < lonlat.xmin < -0.9, lonlat
    assert 47.5 < lonlat.ymin < 48.7, lonlat


@pytest.mark.fast
@pytest.mark.parametrize("manager_cls", [DemManager, GeologyManager])
def test_a_raster_manager_refuses_a_geographic_object(manager_cls):
    """The parameter is gone, not ignored."""
    with pytest.raises(TypeError, match="geographic"):
        manager_cls(config=None, catalog=None, geographic=object())


MANAGERS_STILL_TAKING_GEOGRAPHIC = {
    "oceanic": (
        "its extent is a centroid read off the object as centroid_long_lat, "
        "not a box, which is why the DataSource port left shom.py unported in "
        "F5b. F5d-2."
    ),
}
"""Every manager that still accepts a ``geographic`` object, with the reason.

Pinned rather than counted: three more -- ``lake_abacus``,
``lake_bathymetry`` and ``lake_geometry`` -- took the parameter, stored it,
read it nowhere, and were passed it by nobody. A parameter no caller fills and
no body reads is the decoration D34 refuses, and they lost it with this phase.
A sixth manager growing one has to say here why.
"""


@pytest.mark.fast
def test_no_manager_grows_back_a_geographic_parameter():
    """Anti-vacuity included: the two that remain must really still take one."""
    import inspect

    from hydromodpy.data.loading._dispatch import VARIABLE_SPECS, get_manager_class

    taking = {
        name
        for name in VARIABLE_SPECS
        if "geographic" in inspect.signature(get_manager_class(name).__init__).parameters
    }

    assert taking == set(MANAGERS_STILL_TAKING_GEOGRAPHIC), (
        "a manager took or lost the geographic object without this pin moving; "
        f"the tree says {sorted(taking)}"
    )


@pytest.mark.fast
def test_a_mask_in_its_own_crs_is_reprojected_from_that_crs(tmp_path, monkeypatch):
    """The defect the old pair carried, measured through the public path.

    A WGS84 mask used to be read as four bare floats and then reprojected out
    of whatever CRS ``geographic.watershed_shp`` happened to declare. Here the
    mask is the only thing that says where it is, and what leaves for IGN is
    Lambert-93 metres over Rennes.
    """
    captured: dict[str, object] = {}

    def fake_fetch_ign_dem(*, output_dir, bbox, **_kwargs):
        captured["bbox"] = bbox
        path = Path(output_dir) / "dem.tif"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("dem", encoding="utf-8")
        return path

    monkeypatch.setattr(
        "hydromodpy.data.variables.dem.apis.ign_dem_fr.fetch_ign_dem",
        fake_fetch_ign_dem,
    )
    path = _write_vector_mask(tmp_path / "mask.gpkg", RENNES_4326, "EPSG:4326")
    DemManager(
        config=DemConfig(sources=[IgnGeoplateformeDemSource(mask_path=path)]),
        catalog=None,
        data_dir=tmp_path / "dem",
    ).load()

    assert captured["bbox"] == pytest.approx(RENNES_2154, abs=200.0), captured["bbox"]


@pytest.mark.fast
def test_a_box_in_another_crs_is_measured_on_the_shape_not_on_the_box(tmp_path):
    """``mask_extent_in`` is tighter than converting the box, and by kilometres.

    The bounds of a reprojected polygon are the image of its own vertices; the
    bounds of a reprojected box are the image of a rectangle that contains it.
    On a basin-shaped mask the second is the wider answer, and the catalog
    serves a cached download only when its entry is a superset of the request,
    so the extra width is a download that did not have to happen.

    Anti-vacuity: the assertion is strict on every side, so swapping the body
    back to ``mask_extent(path).to_crs(crs)`` fails it rather than passing by
    a tolerance.
    """
    basin = Polygon(
        [
            (372000.0, 6835000.0),
            (388000.0, 6832000.0),
            (392000.0, 6845000.0),
            (378000.0, 6851000.0),
            (370000.0, 6843000.0),
        ]
    )
    path = tmp_path / "basin.gpkg"
    gpd.GeoDataFrame(geometry=[basin], crs="EPSG:2154").to_file(path)

    on_shape = mask_extent_in(path, "EPSG:4326")
    on_box = mask_extent(path).to_crs("EPSG:4326")

    assert on_shape.crs == "EPSG:4326"
    assert on_box.xmin < on_shape.xmin
    assert on_box.ymin < on_shape.ymin
    assert on_shape.xmax < on_box.xmax
    assert on_shape.ymax < on_box.ymax

    expected = gpd.GeoSeries([basin], crs="EPSG:2154").to_crs("EPSG:4326").total_bounds
    assert on_shape.bbox == pytest.approx(tuple(expected))


@pytest.mark.fast
def test_a_mask_already_in_the_target_crs_is_not_round_tripped(tmp_path):
    """No reprojection, so no chance of one moving the numbers."""
    shape = Polygon([(-1.8, 48.0), (-1.5, 48.0), (-1.5, 48.3), (-1.8, 48.3)])
    path = tmp_path / "mask.gpkg"
    gpd.GeoDataFrame(geometry=[shape], crs="EPSG:4326").to_file(path)

    assert mask_extent_in(path, "EPSG:4326").bbox == pytest.approx((-1.8, 48.0, -1.5, 48.3))
