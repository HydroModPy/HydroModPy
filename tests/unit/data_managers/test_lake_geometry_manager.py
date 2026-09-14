"""LakeGeometryManager.load(): emits a FieldRecord into LoadResult.fields.

Guards that the lake-geometry manager follows the
hand-written GeologyManager pattern: a custom vector source becomes a
Path-backed ``FieldRecord`` (GeoParquet pivot) registered as custom.
"""

from __future__ import annotations

import geopandas as gpd
from shapely.geometry import box

from hydromodpy.data.contracts import FieldRecord
from hydromodpy.data.variables.lake_geometry.config import LakeGeometryConfig
from hydromodpy.data.variables.lake_geometry.manager import LakeGeometryManager


class _RecordingCatalog:
    def __init__(self) -> None:
        self.registrations: list[dict] = []

    def register(self, **kwargs) -> int:
        self.registrations.append(kwargs)
        return len(self.registrations)


def _write_lake_polygon(path) -> None:
    gdf = gpd.GeoDataFrame(
        {"name": ["lac0"]},
        geometry=[box(0.0, 0.0, 100.0, 100.0)],
        crs="EPSG:2154",
    )
    gdf.to_file(str(path), driver="GPKG")


def test_load_emits_field_record_and_registers_custom(tmp_path) -> None:
    src = tmp_path / "lac0.gpkg"
    _write_lake_polygon(src)
    data_dir = tmp_path / "lake_geometry"
    data_dir.mkdir()

    config = LakeGeometryConfig.from_vector(src)
    catalog = _RecordingCatalog()
    manager = LakeGeometryManager(config=config, catalog=catalog, data_dir=data_dir)

    result = manager.load()

    assert result.has_fields is True
    assert not result.has_tables
    assert len(result.fields) == 1

    rec = result.fields[0]
    assert isinstance(rec, FieldRecord)
    assert rec.variable == "lake_geometry"
    assert rec.is_file_reference is True
    assert str(rec.data).endswith(".parquet")
    assert rec.crs.upper().endswith("2154")

    assert len(catalog.registrations) == 1
    reg = catalog.registrations[0]
    assert reg["variable"] == "lake_geometry"
    assert reg["source"] == "custom"
    assert reg["is_custom"] is True
