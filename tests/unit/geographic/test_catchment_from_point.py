from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from hydromodpy.core.exceptions import EmptyCatchmentError, TerrainProductError
from hydromodpy.spatial.geographic.core.catchment_from_point import (
    CATCHMENT_LAYOUT,
    extract_catchment_from_point,
)
from tests._helpers.terrain_doubles import fake_accumulation
from tests._helpers.whitebox_double import FakeVector, FakeWhiteboxBackend


def _accumulation_on_disk(tmp_path: Path):
    """Write a small real ``ln`` accumulation and describe it.

    Real and not a path string, because ``delineate`` reads the raster back to
    check that float32 still orders the counts it carries. A product that names
    a file nobody wrote would only ever exercise the file-missing branch.
    """
    acc = tmp_path / "acc.tif"
    with rasterio.open(
        str(acc),
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        transform=from_origin(0.0, 100.0, 25.0, 25.0),
        nodata=-9999.0,
    ) as dst:
        dst.write(np.log(np.arange(1, 17, dtype="float32").reshape(4, 4)), 1)
    return fake_accumulation(acc=acc, direc=tmp_path / "direc.tif")


def _backend(monkeypatch: pytest.MonkeyPatch) -> FakeWhiteboxBackend:
    """A conforming double whose CRS stamping is a no-op on absent files."""
    backend = FakeWhiteboxBackend()
    monkeypatch.setattr(
        "hydromodpy.spatial.terrain.whitebox_engine.ensure_crs",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.geographic.core.catchment_from_point.ensure_crs",
        lambda *args, **kwargs: None,
    )
    return backend


def test_the_flat_layout_is_the_one_geographic_paths_publish() -> None:
    """The names are the contract: every golden in the tree reads them."""
    assert CATCHMENT_LAYOUT.per_outlet_directory is False
    assert CATCHMENT_LAYOUT.mask_name == "watershed.tif"
    assert CATCHMENT_LAYOUT.boundary_name == "watershed.shp"


def test_extract_catchment_from_point_rejects_empty_snapped_outlet(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backend = _backend(monkeypatch)
    monkeypatch.setattr(
        backend.delineation,
        "snap_pour_points_vector",
        lambda *args, **kwargs: FakeVector(frame=[]),
    )
    monkeypatch.setattr(
        backend.raster,
        "vector_record_count",
        lambda vector: 0,
    )
    monkeypatch.setattr(
        backend.raster,
        "read_raster",
        lambda path: object(),
    )

    with pytest.raises(TerrainProductError, match="produced no feature"):
        extract_catchment_from_point(
            x_outlet=10.0,
            y_outlet=20.0,
            snap_dist=50,
            accumulation=_accumulation_on_disk(tmp_path),
            output_dir=tmp_path / "geo",
            crs_project="EPSG:2154",
            backend=backend,
        )


def test_a_refused_snap_names_the_configuration_keys_to_change(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The engine knows rasters; only this layer knows the TOML keys."""
    backend = _backend(monkeypatch)
    monkeypatch.setattr(backend.raster, "read_raster", lambda path: object())
    monkeypatch.setattr(backend.raster, "vector_record_count", lambda vector: 0)

    with pytest.raises(TerrainProductError, match="geographic.snap_dist"):
        extract_catchment_from_point(
            x_outlet=10.0,
            y_outlet=20.0,
            snap_dist=50,
            accumulation=_accumulation_on_disk(tmp_path),
            output_dir=tmp_path / "geo",
            crs_project="EPSG:2154",
            backend=backend,
        )


def test_extract_catchment_from_point_rejects_empty_watershed_polygon(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backend = _backend(monkeypatch)
    counts = iter([1, 0])
    monkeypatch.setattr(backend.raster, "read_raster", lambda path: object())
    monkeypatch.setattr(backend.raster, "write_raster", lambda raster, path: None)
    monkeypatch.setattr(backend.raster, "write_vector", lambda vector, path: None)
    monkeypatch.setattr(backend.raster, "vector_record_count", lambda vector: next(counts))
    monkeypatch.setattr(backend.delineation, "watershed_raster", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        backend.delineation,
        "raster_to_vector_polygons_raster",
        lambda raster: FakeVector(frame=[]),
    )
    monkeypatch.setattr(
        "hydromodpy.spatial.terrain.whitebox_engine._read_point",
        lambda path: (10.0, 20.0),
    )

    with pytest.raises(EmptyCatchmentError):
        extract_catchment_from_point(
            x_outlet=10.0,
            y_outlet=20.0,
            snap_dist=50,
            accumulation=_accumulation_on_disk(tmp_path),
            output_dir=tmp_path / "geo",
            crs_project="EPSG:2154",
            backend=backend,
        )
