"""``ensure_crs`` stamps a producer's own output, and nothing else.

The helper moved here from ``spatial.geographic.geographic_io`` so that a
terrain engine can stamp what it writes without importing a sibling package.
The raster branch had no test before that move; it has one now, because the
whole point of the function is that it rewrites metadata and not pixels.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
import rasterio
from pyproj import CRS
from rasterio.transform import from_origin

from hydromodpy.core.io import crs as crs_io


def _write_tif_without_crs(path: Path) -> np.ndarray:
    values = np.arange(12, dtype="float32").reshape(3, 4)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=3,
        width=4,
        count=1,
        dtype="float32",
        transform=from_origin(0.0, 75.0, 25.0, 25.0),
        nodata=-9999.0,
    ) as dst:
        dst.write(values, 1)
    return values


def test_the_shapefile_branch_writes_a_prj_without_reopening_the_vector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    shp_path = tmp_path / "domain.shp"
    shp_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        crs_io.gpd,
        "read_file",
        lambda *_args, **_kwargs: pytest.fail("shapefile should not be reopened"),
    )

    crs_io.ensure_crs(shp_path, "EPSG:2154")

    expected_wkt = CRS.from_user_input("EPSG:2154").to_wkt(version="WKT1_ESRI")
    assert shp_path.with_suffix(".prj").read_text(encoding="utf-8") == expected_wkt


def test_a_missing_shapefile_is_named_in_the_refusal(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Shapefile not found"):
        crs_io.ensure_crs(tmp_path / "missing.shp", "EPSG:2154")


def test_the_raster_branch_declares_the_crs_and_leaves_the_band_alone(tmp_path: Path) -> None:
    tif_path = tmp_path / "accumulation.tif"
    values = _write_tif_without_crs(tif_path)
    with rasterio.open(tif_path) as src:
        assert src.crs is None
        before = hashlib.sha256(src.read(1).tobytes()).hexdigest()

    crs_io.ensure_crs(tif_path, "EPSG:2154")

    with rasterio.open(tif_path) as src:
        assert src.crs == rasterio.crs.CRS.from_user_input("EPSG:2154")
        assert hashlib.sha256(src.read(1).tobytes()).hexdigest() == before
        assert src.nodata == -9999.0
        np.testing.assert_array_equal(src.read(1), values)


def test_declaring_nothing_leaves_the_file_untouched(tmp_path: Path) -> None:
    """A caller with no CRS to declare is not a caller in error."""
    tif_path = tmp_path / "accumulation.tif"
    _write_tif_without_crs(tif_path)
    before = tif_path.read_bytes()

    crs_io.ensure_crs(tif_path, None)
    crs_io.ensure_crs(tmp_path / "missing.shp", None)

    assert tif_path.read_bytes() == before
