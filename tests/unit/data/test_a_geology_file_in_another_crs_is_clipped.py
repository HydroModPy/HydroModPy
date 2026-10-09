"""A custom geology vector in another CRS than the project is clipped.

The request box comes in the CRS of the mask (the project CRS). It was laid
over the file's coordinates as they were, so a file in WGS84 gave "No
geology feature intersects bbox after clipping". The box is now reprojected
into the file CRS before the clip.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import box

from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
from hydromodpy.data.variables.geology.config import CustomGeologySource, GeologyConfig
from hydromodpy.data.variables.geology.custom import load_custom_geology
from hydromodpy.data.variables.geology.manager import GeologyManager

# Two units side by side near Rennes, drawn in Lambert-93.
_UNITS_L93 = [
    box(350_000, 6_780_000, 352_000, 6_784_000),
    box(352_000, 6_780_000, 354_000, 6_784_000),
]
_MASK_L93 = (351_000, 6_781_000, 353_000, 6_783_000)


def _write_units_in_wgs84(path: Path) -> Path:
    frame = gpd.GeoDataFrame({"CODE": ["A", "B"]}, geometry=_UNITS_L93, crs="EPSG:2154")
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_crs("EPSG:4326").to_file(str(path), driver="GPKG")
    return path


def test_the_manager_clips_a_wgs84_file_with_a_lambert_mask(tmp_path: Path) -> None:
    data_root = tmp_path / "ws" / "data"
    user_file = _write_units_in_wgs84(data_root / "geology" / "units.gpkg")
    mask = tmp_path / "mask.gpkg"
    gpd.GeoDataFrame(geometry=[box(*_MASK_L93)], crs="EPSG:2154").to_file(str(mask))

    catalog = DataCatalogDuckDB(data_root / "cache.duckdb")
    try:
        manager = GeologyManager(
            config=GeologyConfig(
                sources=[
                    CustomGeologySource(
                        source="custom", path=user_file, code_field="CODE", mask_path=mask
                    )
                ]
            ),
            catalog=catalog,
            data_dir=data_root / "geology",
        )
        record = manager.load().fields[0]
    finally:
        catalog.close()

    clipped = gpd.read_file(str(record.data))
    assert sorted(clipped["CODE"]) == ["A", "B"]
    assert str(record.crs).upper().endswith("4326")
    # The clip covers the mask and keeps little more: the box reprojected into
    # WGS84 is a slightly turned square, and the clip takes its envelope.
    held = clipped.to_crs("EPSG:2154").total_bounds
    assert held[0] <= _MASK_L93[0] and held[1] <= _MASK_L93[1]
    assert held[2] >= _MASK_L93[2] and held[3] >= _MASK_L93[3]
    assert held[0] > 350_000 and held[2] < 354_000


def test_a_box_that_misses_the_file_names_the_file_and_its_crs(tmp_path: Path) -> None:
    user_file = _write_units_in_wgs84(tmp_path / "units.gpkg")
    source = CustomGeologySource(source="custom", path=user_file, code_field="CODE")
    with pytest.raises(ValueError, match=r"No geology feature of units\.gpkg intersects"):
        load_custom_geology(
            source,
            code_field="CODE",
            bbox=(100_000, 6_100_000, 101_000, 6_101_000),
            bbox_crs="EPSG:2154",
            derived_dir=tmp_path / "derived",
        )
