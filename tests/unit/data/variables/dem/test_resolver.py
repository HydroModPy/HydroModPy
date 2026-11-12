"""The DEM resolver seals the source with the state its row declares, and refuses a file without a CRS."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.data.variables.dem.resolver import require_dem_crs, resolve_dem
from tests._helpers.geotiffs import write_geotiff


def _cfg(path, *, state: str | None = None) -> dict:
    source = {"source": "file", "path": str(path)}
    if state is not None:
        source["state"] = state
    return {"data": {"dem": {"sources": [source]}}}


def test_a_file_source_reads_its_declared_state(tmp_path) -> None:
    dem = write_geotiff(tmp_path / "dem.tif", np.ones((4, 4)), cell=25.0, crs="EPSG:2154")

    record = resolve_dem(_cfg(dem, state="conditioned"))

    assert record.state == "conditioned"
    assert record.origin == "file"


def test_a_file_source_defaults_to_raw_when_it_says_none(tmp_path) -> None:
    dem = write_geotiff(tmp_path / "dem.tif", np.ones((4, 4)), cell=25.0, crs="EPSG:2154")

    assert resolve_dem(_cfg(dem)).state == "raw"


def test_no_source_resolves_to_none() -> None:
    assert resolve_dem({"data": {"dem": {"sources": []}}}) is None


def test_a_file_dem_without_a_crs_is_refused(tmp_path) -> None:
    path = write_geotiff(tmp_path / "regional.tif", np.ones((4, 4)), cell=25.0, crs=None)
    source = SimpleNamespace(source="file", path=path)
    cfg = SimpleNamespace(data=SimpleNamespace(dem=SimpleNamespace(sources=[source])))

    with pytest.raises(DataContractViolation, match=r"declares no CRS"):
        resolve_dem(cfg, data_dir=tmp_path)


def test_a_dem_rasterio_cannot_open_is_left_to_the_reading_step(tmp_path) -> None:
    (tmp_path / "points.xyz").write_text("0 0 1\n")
    (tmp_path / "broken.tif").write_bytes(b"not a tiff")

    assert require_dem_crs(tmp_path / "points.xyz") is None
    assert require_dem_crs(tmp_path / "broken.tif") is None
    assert require_dem_crs(tmp_path / "absent.tif") is None
