"""Shared builders for the split hydrography test modules.

Co-located non-test module. Imported with a relative import by the sibling
``test_hydrography_*`` files. Holds the GeoDataFrame/raster fixtures, the
LoadResult accessors, and the deterministic Whitebox stub backend.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import geopandas as gpd
import numpy as np
import xarray as xr
from shapely.geometry import LineString, Point, Polygon

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.spatial.geographic.core.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
)


def _make_lines_gdf(crs="EPSG:4326", n=3):
    """Create a small GeoDataFrame with LineString geometries."""
    lines = [LineString([(i, 48.0), (i + 0.01, 48.01)]) for i in range(n)]
    return gpd.GeoDataFrame(
        {"waterway": ["river"] * n, "id": list(range(n))},
        geometry=lines,
        crs=crs,
    )


def _make_polygon_gdf(crs="EPSG:4326"):
    return gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])],
        crs=crs,
    )


def _make_point_gdf(crs="EPSG:4326"):
    return gpd.GeoDataFrame(
        {"id": [1, 2]},
        geometry=[Point(0, 0), Point(1, 1)],
        crs=crs,
    )


def _watershed_gdf(crs="EPSG:2154"):
    """Fake watershed polygon big enough to contain test data once reprojected."""
    return gpd.GeoDataFrame(
        geometry=[
            Polygon(
                [
                    (300000, 6700000),
                    (400000, 6700000),
                    (400000, 6800000),
                    (300000, 6800000),
                ]
            )
        ],
        crs=crs,
    )


def _fake_geographic(tmp_path, crs="EPSG:2154"):
    """Mock geographic object with required attributes."""
    ws_path = tmp_path / "watershed.shp"
    _watershed_gdf(crs).to_file(ws_path)

    dem_path = tmp_path / "dem.tif"
    _write_dummy_tif(dem_path, crs=crs)

    geo = MagicMock()
    geo.watershed_shp = str(ws_path)
    geo.watershed_dem = str(dem_path)
    geo.crs_proj = crs
    return geo


def _write_dummy_tif(path, crs="EPSG:2154", shape=(100, 100)):
    """Write a minimal GeoTIFF for backend calls."""
    import rasterio
    from rasterio.transform import from_bounds

    transform = from_bounds(300000, 6700000, 400000, 6800000, shape[1], shape[0])
    with rasterio.open(
        str(path),
        "w",
        driver="GTiff",
        height=shape[0],
        width=shape[1],
        count=1,
        dtype="float32",
        crs=crs,
        transform=transform,
    ) as ds:
        ds.write(np.ones(shape, dtype=np.float32), 1)


def _make_hydrography_load_result(
    *,
    array: np.ndarray | None = None,
    raster_path: str = "/tmp/streams.tif",
    vector_path: str | None = None,
    crs: str = "EPSG:2154",
) -> LoadResult:
    values = np.zeros((5, 5), dtype=float) if array is None else array
    data = xr.Dataset(
        {
            HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME: (
                ("y", "x"),
                values,
            )
        }
    )
    record = FieldRecord(
        variable=HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
        source="hydrography",
        unit="",
        data=data,
        bbox=(0.0, 0.0, float(values.shape[1]), float(values.shape[0])),
        crs=crs,
        metadata={
            "raster_path": raster_path,
            "vector_path": vector_path,
            "array_name": HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
        },
    )
    return LoadResult(fields=[record])


def _hydrography_record(result: LoadResult) -> FieldRecord:
    assert isinstance(result, LoadResult)
    assert len(result.fields) == 1
    return result.fields[0]


def _hydrography_array(result: LoadResult) -> np.ndarray:
    record = _hydrography_record(result)
    return np.asarray(record.data[record.variable].values)


def _hydrography_vector_path(result: LoadResult) -> str | None:
    metadata = _hydrography_record(result).metadata
    value = metadata.get("vector_path")
    return None if value is None else str(value)


def _hydrography_raster_path(result: LoadResult) -> str:
    value = _hydrography_record(result).metadata["raster_path"]
    return str(value)


class WhiteboxStubBackend:
    """Deterministic in-test substitute for the split Whitebox facade.

    Records each call and produces real synthetic raster/vector outputs so
    the manager pipeline can be exercised end-to-end without the real
    Whitebox runtime. The facade exposes ``raster`` and ``delineation``
    sub-backends that mirror the production split.
    """

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.raster = _WhiteboxStubRaster(self.calls)
        self.delineation = _WhiteboxStubDelineation(self.calls)

    def method_names(self) -> list[str]:
        return [c[0] for c in self.calls]


class _WhiteboxStubRaster:
    def __init__(self, calls: list[tuple]) -> None:
        self._calls = calls

    def vector_lines_to_raster(self, shp: str, tif: str, *, field: str, base: str) -> None:
        self._calls.append(("vector_lines_to_raster", shp, tif, field))
        _write_dummy_tif(tif)

    def vector_polygons_to_raster(self, shp: str, tif: str, *, field: str, base: str) -> None:
        self._calls.append(("vector_polygons_to_raster", shp, tif, field))
        _write_dummy_tif(tif)

    def vector_points_to_raster(self, shp: str, tif: str, *, field: str, base: str) -> None:
        self._calls.append(("vector_points_to_raster", shp, tif, field))
        _write_dummy_tif(tif)

    def set_nodata_value(self, src: str, dst: str, *, back_value: float) -> None:
        import shutil

        self._calls.append(("set_nodata_value", src, dst, back_value))
        if str(src) != str(dst):
            shutil.copy(src, dst)


class _WhiteboxStubDelineation:
    def __init__(self, calls: list[tuple]) -> None:
        self._calls = calls

    def raster_to_vector_points(self, tif: str, out_shp: str) -> None:
        self._calls.append(("raster_to_vector_points", tif, out_shp))
        Path(out_shp).parent.mkdir(parents=True, exist_ok=True)
        gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[Point(350000, 6750000)],
            crs="EPSG:2154",
        ).to_file(out_shp)
