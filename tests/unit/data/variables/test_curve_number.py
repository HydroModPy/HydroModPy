"""The curve number built from land cover: crosswalk, soil group, then the GCN250 row.

Small grids stand for the land cover, so each test reads the map the source writes. The
OCS GE archives are replaced by a few cover polygons, the user raster by a tiny GeoTIFF.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from pydantic import ValidationError
from rasterio.transform import from_origin
from shapely.geometry import box

from hydromodpy.core.exceptions import DataProductError
from hydromodpy.data.variables.curve_number import from_land_cover
from hydromodpy.data.variables.curve_number.config import CurveNumberConfig
from hydromodpy.data.variables.curve_number.maps import (
    NODATA,
    coded,
    crosswalk_of,
    curve_number_grid,
    soil_groups,
)

TRANSFORM = from_origin(0.0, 10.0, 10.0, 10.0)


def read(path):
    with rasterio.open(path) as raster:
        return raster.read(1)[0].tolist()


def test_each_class_reads_its_row_and_a_sealed_class_is_no_data():
    classes, labels = coded(np.array([[211, 231, 112, 512]]), None)
    groups = np.full((1, 4), 2, dtype=np.int8)

    grid = curve_number_grid(classes, labels, crosswalk_of("clc", {}), groups, section="s")

    # arable land 10 and pasture 11 on C, urban fabric and water left out
    assert grid[0].tolist() == [75.0, 75.0, NODATA, NODATA]


def test_a_class_no_table_names_is_refused_with_its_share():
    classes, labels = coded(np.array([[211, 999, 999, 999]]), None)
    groups = np.zeros((1, 4), dtype=np.int8)

    with pytest.raises(DataProductError, match=r"999 \(75\.0 %\)"):
        curve_number_grid(classes, labels, crosswalk_of("clc", {}), groups, section="s")


def test_the_section_overrides_a_row_and_a_custom_legend_writes_every_class():
    classes, labels = coded(np.array([[30, 40]]), None)
    groups = np.zeros((1, 2), dtype=np.int8)

    default = curve_number_grid(
        classes, labels, crosswalk_of("worldcover", {}), groups, section="s"
    )
    meadow = curve_number_grid(
        classes, labels, crosswalk_of("worldcover", {"30": 11}), groups, section="s"
    )
    custom = curve_number_grid(
        classes, labels, crosswalk_of("custom", {"30": 60, "40": 0}), groups, section="s"
    )

    assert default[0].tolist() == [54.0, 57.0]
    assert meadow[0].tolist() == [57.0, 57.0]
    assert custom[0].tolist() == [35.0, NODATA]


def test_a_hysogs_raster_gives_its_group_and_reads_a_wet_group_as_d(tmp_path):
    path = tmp_path / "hysogs.tif"
    codes = np.array([[1, 2, 3, 4, 13, 255]], dtype=np.uint8)
    transform = from_origin(0.0, 10.0, 10.0, 10.0)
    with rasterio.open(path, "w", driver="GTiff", width=6, height=1, count=1, dtype="uint8",
                       crs="EPSG:2154", transform=transform, nodata=255) as out:  # fmt: skip
        out.write(codes, 1)

    groups = soil_groups((1, 6), transform, "EPSG:2154", hsg=None, hsg_path=path)

    assert groups[0].tolist() == [0, 1, 2, 3, 3, -1]
    assert soil_groups((1, 2), transform, "EPSG:2154", hsg="B", hsg_path=None).tolist() == [[1, 1]]


def test_ocsge_covers_burn_their_rows_and_leave_the_sealed_ground_out(monkeypatch, tmp_path):
    covers = gpd.GeoDataFrame(
        {"code_cs": ["CS1.1.1.2", "CS2.1.1.1", "CS2.2.1", "CS1.2.2"]},
        geometry=[box(0, 0, 10, 10), box(10, 0, 20, 10), box(20, 0, 30, 10), box(30, 0, 40, 10)],
        crs="EPSG:2154",
    )
    from hydromodpy.data.common.clients import ocsge

    monkeypatch.setattr(ocsge, "department_archives", lambda **kw: ([tmp_path / "a.7z"], ["D035"]))
    monkeypatch.setattr(ocsge, "cover_polygons", lambda archive, bbox: covers)

    path = from_land_cover.fetch_ocsge_curve_number(
        output_dir=tmp_path, bbox=(0.0, 0.0, 40.0, 10.0), year=2023, hsg="A", hsg_path=None,
        classes={},
    )  # fmt: skip

    assert read(path) == [NODATA, 35.0, 57.0, NODATA]
    assert ocsge.editions_of(path) == "D035"


def test_a_clc_raster_of_the_user_becomes_a_curve_number_map(tmp_path):
    path = tmp_path / "clc.tif"
    with rasterio.open(path, "w", driver="GTiff", width=3, height=1, count=1, dtype="uint16",
                       crs="EPSG:4326", transform=from_origin(-1.0, 48.0, 0.1, 0.1),
                       nodata=0) as out:  # fmt: skip
        out.write(np.array([[311, 211, 0]], dtype=np.uint16), 1)

    target = from_land_cover.fetch_land_cover_curve_number(
        output_dir=tmp_path, bbox=(-1.0, 47.9, -0.7, 48.0), path=path, nomenclature="clc",
        hsg="D", hsg_path=None, classes={},
    )  # fmt: skip

    assert read(target) == [79.0, 78.0, NODATA]


REFUSALS = [
    pytest.param({"source": "ocsge", "year": 2023}, "hydrologic soil group", id="no soil group"),
    pytest.param(
        {"source": "worldcover", "hsg": "C", "hsg_path": "s.tif"},
        "hydrologic soil group",
        id="both soil groups",
    ),
    pytest.param(
        {"source": "worldcover", "hsg": "C", "classes": {"30": 999}},
        "to no ESA CCI class",
        id="a class to nowhere",
    ),
    pytest.param(
        {"source": "land_cover", "path": "lc.tif", "nomenclature": "osm", "hsg": "C"},
        "nomenclature",
        id="an unknown legend",
    ),
]


@pytest.mark.parametrize(("source", "match"), REFUSALS)
def test_a_land_cover_source_is_refused_when_it_cannot_hold(source, match):
    with pytest.raises(ValidationError, match=match):
        CurveNumberConfig.model_validate({"sources": [source]})
