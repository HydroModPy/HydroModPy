"""A Whitebox facade double that serves both shapes of the backend contract.

The geographic pipeline reaches its backend two ways: through file-in/file-out
members, and through the in-memory ``*_raster`` / ``*_vector`` members the
terrain engine uses so a batch reads its shared products once. A double that
only serves the first makes the engine fail on an attribute, which is a test
artefact and not a finding, so this one serves both from the same synthetic
answers.

Deliberately not a simulation: the flow pointer is all ones, the accumulation
counts cells in row-major order, and the watershed is the quadrant south-west
of the outlet. What these tests lock is the facade contract around those
answers, not the hydrology.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import geometry_mask, rasterize, shapes
from shapely.geometry import shape as shapely_shape


@dataclass(frozen=True)
class FakeRaster:
    """A raster held in memory, as the real backend holds one."""

    data: np.ndarray
    profile: dict[str, Any]


@dataclass(frozen=True)
class FakeVector:
    """A vector layer held in memory, with the record list the backend counts."""

    frame: gpd.GeoDataFrame

    @property
    def records(self) -> list[int]:
        return list(range(len(self.frame)))


def _read(path: str | Path) -> FakeRaster:
    with rasterio.open(str(path)) as src:
        return FakeRaster(data=src.read(1), profile=src.profile.copy())


def _write(raster: FakeRaster, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(str(path), "w", **raster.profile) as dst:
        dst.write(raster.data.astype(raster.profile["dtype"]), 1)


def _pointer(raster: FakeRaster) -> FakeRaster:
    profile = raster.profile.copy()
    profile.update(dtype=np.int16, nodata=-32768, count=1)
    return FakeRaster(data=np.ones(raster.data.shape, dtype=np.int16), profile=profile)


def _accumulation(raster: FakeRaster, *, log: bool) -> FakeRaster:
    """Count cells in row-major order, and honour the transform that was asked.

    ``log`` used to be ignored here. A double that answers the same numbers
    whatever transform it is handed lets a caller declare ``ln`` over a raster of
    raw counts, which is exactly the mismatch the port refuses.
    """
    profile = raster.profile.copy()
    profile.update(dtype=np.float32, nodata=-9999.0, count=1)
    size = raster.data.shape[0] * raster.data.shape[1]
    counts = np.arange(1, size + 1, dtype=np.float32).reshape(raster.data.shape)
    return FakeRaster(data=np.log(counts) if log else counts, profile=profile)


def _watershed(pointer: FakeRaster, outlet_frame: gpd.GeoDataFrame) -> FakeRaster:
    outlet = outlet_frame.geometry.iloc[0]
    transform = pointer.profile["transform"]
    height, width = pointer.data.shape
    cols = np.arange(width, dtype=float)
    rows = np.arange(height, dtype=float)
    xx = transform.c + (cols + 0.5) * transform.a
    yy = transform.f + (rows + 0.5) * transform.e
    xg, yg = np.meshgrid(xx, yy)

    # Deterministic synthetic watershed: cells "upstream" of outlet in XY space.
    mask = (xg <= float(outlet.x)) & (yg <= float(outlet.y))
    if not np.any(mask):
        # Ensure at least one cell belongs to watershed if outlet is near edge.
        col = int(np.clip(round((float(outlet.x) - transform.c) / transform.a - 0.5), 0, width - 1))
        row = int(
            np.clip(round((float(outlet.y) - transform.f) / transform.e - 0.5), 0, height - 1)
        )
        mask[row, col] = True

    profile = pointer.profile.copy()
    profile.update(dtype=np.uint8, nodata=0, count=1)
    return FakeRaster(data=np.where(mask, 1, 0).astype(np.uint8), profile=profile)


def _polygonize(raster: FakeRaster) -> FakeVector:
    geometries = [
        shapely_shape(geom)
        for geom, value in shapes(raster.data, transform=raster.profile["transform"])
        if int(value) == 1
    ]
    return FakeVector(
        gpd.GeoDataFrame(
            data={"id": list(range(1, len(geometries) + 1))},
            geometry=geometries,
            crs=raster.profile.get("crs"),
        )
    )


class FakeRasterOps:
    """Raster IO and conversion subset of the fake Whitebox facade."""

    @staticmethod
    def _copy_raster(src_path: str | Path, dst_path: str | Path) -> None:
        _write(_read(src_path), dst_path)

    def read_raster(self, path: str) -> FakeRaster:
        return _read(path)

    def write_raster(self, raster: FakeRaster, path: str) -> None:
        _write(raster, path)

    def read_vector(self, path: str) -> FakeVector:
        return FakeVector(gpd.read_file(str(path)))

    def write_vector(self, vector: FakeVector, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        vector.frame.to_file(str(path))

    def vector_record_count(self, vector: FakeVector) -> int:
        return len(vector.frame)

    def clip_raster_to_polygon(
        self,
        in_raster: str,
        in_polygon: str,
        out_raster: str,
        maintain_dimensions: bool = False,
    ) -> None:
        _ = maintain_dimensions
        polygons = gpd.read_file(in_polygon)
        with rasterio.open(in_raster) as src_ds:
            data = src_ds.read(1)
            profile = src_ds.profile.copy()
            nodata = src_ds.nodata if src_ds.nodata is not None else -9999.0
            keep_mask = geometry_mask(
                [geom for geom in polygons.geometry],
                out_shape=data.shape,
                transform=src_ds.transform,
                invert=True,
            )
            clipped = np.where(keep_mask, data, nodata)
            profile.update(count=1, nodata=nodata)
        Path(out_raster).parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(out_raster, "w", **profile) as dst_ds:
            dst_ds.write(clipped.astype(profile["dtype"]), 1)

    def modify_no_data_value(self, raster_path: str, *, new_value: float) -> None:
        with rasterio.open(raster_path, "r+") as dst_ds:
            dst_ds.nodata = float(new_value)

    def vector_lines_to_raster(
        self,
        in_shp: str,
        out_raster: str,
        *,
        field: str | None = None,
        zero_background: bool | None = None,
        cell_size: float | None = None,
        base: str | None = None,
    ) -> None:
        _ = field, zero_background, cell_size
        lines = gpd.read_file(in_shp)
        with rasterio.open(base) as base_ds:
            profile = base_ds.profile.copy()
            transform = base_ds.transform
            shape = (base_ds.height, base_ds.width)
        profile.update(dtype=np.uint8, nodata=0, count=1)
        data = rasterize(
            [(geom, 1) for geom in lines.geometry],
            out_shape=shape,
            transform=transform,
            fill=0,
            dtype=np.uint8,
        )
        Path(out_raster).parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(out_raster, "w", **profile) as dst_ds:
            dst_ds.write(data, 1)


class FakeFlowOps:
    """DEM flow analysis subset of the fake Whitebox facade."""

    def __init__(self, raster: FakeRasterOps) -> None:
        self._raster = raster

    def fill_depressions(self, dem_in: str, dem_out: str) -> None:
        self._raster._copy_raster(dem_in, dem_out)

    def fill_depressions_raster(self, dem: FakeRaster) -> FakeRaster:
        return dem

    def breach_depressions(self, dem_in: str, dem_out: str) -> None:
        self._raster._copy_raster(dem_in, dem_out)

    def breach_depressions_raster(self, dem: FakeRaster) -> FakeRaster:
        return dem

    def d8_pointer(self, dem_in: str, out_path: str, esri_pntr: bool = False) -> None:
        _ = esri_pntr
        _write(_pointer(_read(dem_in)), out_path)

    def d8_pointer_raster(self, dem: FakeRaster, *, esri_pntr: bool = False) -> FakeRaster:
        _ = esri_pntr
        return _pointer(dem)

    def d8_flow_accumulation(self, dem_in: str, out_path: str, log: bool = True) -> None:
        _write(_accumulation(_read(dem_in), log=log), out_path)

    def d8_flow_accumulation_raster(
        self,
        dem: FakeRaster,
        *,
        log: bool = True,
        out_type: str = "cells",
        input_is_pointer: bool = False,
    ) -> FakeRaster:
        """Accumulate, and refuse a flag that contradicts what was handed over.

        The synthetic answer counts cells in row-major order whatever it is
        handed, so on its own this double cannot tell a caller that accumulates
        the pointer from one that accumulates the DEM -- which would make every
        test built on it blind to that plumbing. The flag is therefore checked
        against the raster: a pointer is what :func:`_pointer` writes, ``int16``,
        and a conditioned DEM is not.
        """
        _ = out_type
        looks_like_pointer = np.dtype(dem.profile["dtype"]) == np.int16
        if input_is_pointer != looks_like_pointer:
            raise AssertionError(
                f"input_is_pointer={input_is_pointer} but the raster handed over is "
                f"{'a pointer' if looks_like_pointer else 'not a pointer'} "
                f"(dtype {dem.profile['dtype']})."
            )
        return _accumulation(dem, log=log)


class FakeDelineationOps:
    """Watershed and stream-network subset of the fake Whitebox facade."""

    def snap_pour_points(
        self,
        pour_points: str,
        flow_accumulation: str,
        output: str,
        snap_dist: int,
    ) -> None:
        _ = flow_accumulation, snap_dist
        gdf = gpd.read_file(pour_points)
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        gdf.to_file(output)

    def snap_pour_points_vector(
        self,
        pour_points: FakeVector,
        flow_accumulation: FakeRaster,
        snap_dist: int,
    ) -> FakeVector:
        _ = flow_accumulation, snap_dist
        return pour_points

    def watershed(
        self,
        d8_pntr: str,
        pour_pts: str,
        output: str,
        esri_pntr: bool = False,
    ) -> None:
        _ = esri_pntr
        _write(_watershed(_read(d8_pntr), gpd.read_file(pour_pts)), output)

    def watershed_raster(
        self,
        d8_pntr: FakeRaster,
        pour_pts: FakeVector,
        esri_pntr: bool = False,
    ) -> FakeRaster:
        _ = esri_pntr
        return _watershed(d8_pntr, pour_pts.frame)

    def raster_to_vector_polygons(self, input_raster: str, output_shp: str) -> None:
        vector = _polygonize(_read(input_raster))
        Path(output_shp).parent.mkdir(parents=True, exist_ok=True)
        vector.frame.to_file(output_shp)

    def raster_to_vector_polygons_raster(self, raster: FakeRaster) -> FakeVector:
        return _polygonize(raster)

    def polygons_to_lines(self, in_shp: str, out_shp: str) -> None:
        gdf = gpd.read_file(in_shp)
        union_geom = (
            gdf.geometry.union_all() if hasattr(gdf.geometry, "union_all") else gdf.unary_union
        )
        out = gpd.GeoDataFrame({"id": [1]}, geometry=[union_geom.boundary], crs=gdf.crs)
        Path(out_shp).parent.mkdir(parents=True, exist_ok=True)
        out.to_file(out_shp)


class FakeWhiteboxBackend:
    """Facade composing fake raster, flow and delineation sub-backends."""

    verbose = False

    def __init__(self) -> None:
        self.raster = FakeRasterOps()
        self.flow = FakeFlowOps(self.raster)
        self.delineation = FakeDelineationOps()


__all__ = [
    "FakeDelineationOps",
    "FakeFlowOps",
    "FakeRaster",
    "FakeRasterOps",
    "FakeVector",
    "FakeWhiteboxBackend",
]
