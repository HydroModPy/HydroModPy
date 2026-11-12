"""Lake outline (polygon in EPSG:2154) read in place from a vector file."""

from __future__ import annotations

import geopandas as gpd
from shapely.geometry import box

from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.provenance.sidecars import CacheIndex, sidecar_path_for
from hydromodpy.data.variables.lake_geometry.config import LakeGeometryConfig
from hydromodpy.data.variables.lake_geometry.variable import LakeGeometryVariable


def test_load_emits_a_field_record_and_no_cache_row(tmp_path) -> None:
    src = tmp_path / "lac0.gpkg"
    gpd.GeoDataFrame(
        {"name": ["lac0"]}, geometry=[box(0.0, 0.0, 100.0, 100.0)], crs="EPSG:2154"
    ).to_file(str(src), driver="GPKG")
    data_dir = tmp_path / "lake_geometry"
    data_dir.mkdir()
    index = CacheIndex(tmp_path)
    variable = LakeGeometryVariable(
        config=LakeGeometryConfig.from_vector(src), index=index, data_dir=data_dir
    )

    result = variable.load()

    assert result.has_fields
    assert not result.has_tables
    (record,) = result.fields
    assert isinstance(record, FieldRecord)
    assert record.variable == "lake_geometry"
    assert record.is_file_reference
    assert str(record.data).endswith(".parquet")
    assert record.crs.upper().endswith("2154")
    # A user file is no row of the data cache, and nothing writes a sidecar beside it.
    assert index.rows() == []
    assert not sidecar_path_for(src).exists()
