"""LakeBathymetryManager.load(): emits a FieldRecord into LoadResult.fields.

Guards that the lake-bathymetry manager follows the
hand-written GeologyManager pattern: a custom raster source becomes a
Path-backed ``FieldRecord`` (COG GeoTIFF pivot) registered as custom.
"""

from __future__ import annotations

import numpy as np
import rasterio
from rasterio.transform import from_origin

from hydromodpy.data.contracts import FieldRecord
from hydromodpy.data.variables.lake_bathymetry.config import LakeBathymetryConfig
from hydromodpy.data.variables.lake_bathymetry.manager import LakeBathymetryManager


class _RecordingCatalog:
    def __init__(self) -> None:
        self.registrations: list[dict] = []

    def register(self, **kwargs) -> int:
        self.registrations.append(kwargs)
        return len(self.registrations)


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


def test_load_emits_field_record_and_registers_custom(tmp_path) -> None:
    src = tmp_path / "lac0.tif"
    _write_lake_bathymetry(src)
    data_dir = tmp_path / "lake_bathymetry"
    data_dir.mkdir()

    config = LakeBathymetryConfig.from_raster(src)
    catalog = _RecordingCatalog()
    manager = LakeBathymetryManager(config=config, catalog=catalog, data_dir=data_dir)

    result = manager.load()

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

    assert len(catalog.registrations) == 1
    reg = catalog.registrations[0]
    assert reg["variable"] == "lake_bathymetry"
    assert reg["source"] == "custom"
    assert reg["is_custom"] is True
