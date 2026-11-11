"""The variables of the lakes read a user file in place and record no cache row."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.contracts.table import TableRecord
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.provenance.sidecars import CacheIndex, sidecar_path_for
from hydromodpy.data.variables.lake_abacus.config import LakeAbacusConfig
from hydromodpy.data.variables.lake_abacus.variable import LakeAbacusVariable
from hydromodpy.data.variables.lake_bathymetry.config import LakeBathymetryConfig
from hydromodpy.data.variables.lake_bathymetry.variable import LakeBathymetryVariable
from hydromodpy.data.variables.lake_geometry.config import LakeGeometryConfig
from hydromodpy.data.variables.lake_geometry.variable import LakeGeometryVariable
from hydromodpy.data.variables.lake_series import LakeLevelsConfig, LakeLevelsVariable


def _no_cache_row(index: CacheIndex, *files) -> None:
    """A user file is no row of the data cache, and nothing writes a sidecar beside it."""
    assert index.rows() == []
    for path in files:
        assert not sidecar_path_for(path).exists()


def test_load_emits_table_record_and_records_no_cache_row(tmp_path) -> None:
    src = tmp_path / "lake_abacus_custom_lac0.csv"
    src.write_text(
        "stage,volume,sarea\n85.0,0.0,0.0\n90.0,1.0e6,4.0e5\n",
        encoding="utf-8",
    )
    data_dir = tmp_path / "lake_abacus"
    data_dir.mkdir()

    config = LakeAbacusConfig.from_csv(src, lake_id="lac0")
    index = CacheIndex(tmp_path)
    variable = LakeAbacusVariable(config=config, index=index, data_dir=data_dir)

    result = variable.load()

    assert result.has_tables is True
    assert not result.has_points
    assert not result.has_fields
    assert len(result.tables) == 1

    rec = result.tables[0]
    assert isinstance(rec, TableRecord)
    assert rec.variable == "lake_abacus"
    assert rec.table_id == "lac0"
    assert rec.is_file_reference is True

    # The validated Parquet pivot round-trips through the record frame.
    frame = rec.frame
    assert frame["lake_id"].unique().tolist() == ["lac0"]
    assert frame["stage"].tolist() == [85.0, 90.0]

    _no_cache_row(index, src)


def _write_lake_bathymetry(path) -> None:
    data = np.full((4, 4), 82.0, dtype="float32")
    transform = from_origin(0.0, 100.0, 25.0, 25.0)
    with rasterio.open(
        str(path),
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        transform=transform,
    ) as dst:
        dst.write(data, 1)


def test_bathymetry_load_emits_field_record_and_records_no_cache_row(tmp_path) -> None:
    src = tmp_path / "lac0.tif"
    _write_lake_bathymetry(src)
    data_dir = tmp_path / "lake_bathymetry"
    data_dir.mkdir()

    config = LakeBathymetryConfig.from_raster(src)
    index = CacheIndex(tmp_path)
    variable = LakeBathymetryVariable(config=config, index=index, data_dir=data_dir)

    result = variable.load()

    assert result.has_fields is True
    assert not result.has_points
    assert len(result.fields) == 1

    rec = result.fields[0]
    assert isinstance(rec, FieldRecord)
    assert rec.variable == "lake_bathymetry"
    assert rec.is_file_reference is True
    assert str(rec.data).endswith(".tif")
    assert rec.crs.upper().endswith("2154")
    assert rec.bbox == (0.0, 0.0, 100.0, 100.0)

    _no_cache_row(index, src)


def _write_lake_polygon(path) -> None:
    gdf = gpd.GeoDataFrame(
        {"name": ["lac0"]},
        geometry=[box(0.0, 0.0, 100.0, 100.0)],
        crs="EPSG:2154",
    )
    gdf.to_file(str(path), driver="GPKG")


def test_geometry_load_emits_field_record_and_records_no_cache_row(tmp_path) -> None:
    src = tmp_path / "lac0.gpkg"
    _write_lake_polygon(src)
    data_dir = tmp_path / "lake_geometry"
    data_dir.mkdir()

    config = LakeGeometryConfig.from_vector(src)
    index = CacheIndex(tmp_path)
    variable = LakeGeometryVariable(config=config, index=index, data_dir=data_dir)

    result = variable.load()

    assert result.has_fields is True
    assert not result.has_tables
    assert len(result.fields) == 1

    rec = result.fields[0]
    assert isinstance(rec, FieldRecord)
    assert rec.variable == "lake_geometry"
    assert rec.is_file_reference is True
    assert str(rec.data).endswith(".parquet")
    assert rec.crs.upper().endswith("2154")

    _no_cache_row(index, src)


def _write_lake_levels(data_dir, lake_id: str) -> None:
    pd.DataFrame(
        {
            "id": [lake_id],
            "x": [350000.0],
            "y": [6800000.0],
            "crs": ["EPSG:2154"],
            "unit": ["m"],
        }
    ).to_csv(data_dir / "lake_levels_custom_LOC.csv", index=False)

    pd.DataFrame(
        {
            "datetime": ["2020-01-01", "2020-01-02", "2020-01-03"],
            "value": [85.0, 85.5, 86.0],
        }
    ).to_csv(
        data_dir / f"lake_levels_custom_{lake_id}_20200101_20200103_D.csv",
        index=False,
    )


def test_load_emits_point_record_keyed_by_lake_id(tmp_path) -> None:
    data_dir = tmp_path / "lake_levels"
    data_dir.mkdir()
    _write_lake_levels(data_dir, "lac0")

    config = LakeLevelsConfig.from_csv_directory(data_dir)
    index = CacheIndex(tmp_path)
    variable = LakeLevelsVariable(config=config, index=index, data_dir=data_dir)

    result = variable.load()

    assert result.has_points is True
    assert not result.has_fields
    assert not result.has_tables
    assert len(result.points) == 1

    rec = result.points[0]
    assert isinstance(rec, PointRecord)
    assert rec.variable == "lake_level"
    assert rec.source == "file"
    assert rec.station_id == "lac0"
    assert rec.unit == "m"

    assert rec.data["value"].tolist() == [85.0, 85.5, 86.0]

    _no_cache_row(index, *sorted(data_dir.glob("*.csv")))
