"""Fakes and files shared by the step tests."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import xarray as xr
from shapely.geometry import LineString, box

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.spatial.geographic.core.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
)


@dataclasses.dataclass
class FakeRecord:
    variable: str
    source: str
    metadata: dict | None = None
    date_start: object = None
    date_end: object = None
    station_id: str | None = None


@dataclasses.dataclass
class FakeLoadResult:
    points: tuple = ()
    fields: tuple = ()


def write_network_vector(path: Path, *, crs: str | None = "EPSG:2154") -> Path:
    gdf = gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[LineString([(0.0, 0.0), (1000.0, 0.0)])],
        crs=crs,
    )
    if crs is None:
        with pytest.warns(UserWarning, match="'crs' was not provided"):
            gdf.to_file(path)
    else:
        gdf.to_file(path)
    return path


def write_watershed(path: Path) -> Path:
    gdf = gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[box(0.0, -500.0, 1000.0, 500.0)],
        crs="EPSG:2154",
    )
    gdf.to_file(path)
    return path


def hydrography_load_result(
    *,
    vector_path: Path,
    raster_path: Path,
    array: np.ndarray,
) -> LoadResult:
    data = xr.Dataset(
        {
            HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME: (
                ("y", "x"),
                array,
            )
        }
    )
    record = FieldRecord(
        variable=HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
        source="hydrography",
        unit="",
        data=data,
        bbox=(0.0, 0.0, float(array.shape[1]), float(array.shape[0])),
        crs="EPSG:2154",
        metadata={
            "raster_path": str(raster_path),
            "vector_path": str(vector_path),
            "array_name": HYDROGRAPHIC_NETWORK_REFERENCE_RASTER_FORCING_NAME,
        },
    )
    return LoadResult(fields=[record])
