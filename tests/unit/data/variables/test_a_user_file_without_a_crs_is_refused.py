"""A DEM, a geology file or a river network without a CRS is refused by name.

They used to be labeled EPSG:2154 (DEM, geology) or EPSG:4326 (river network)
without a word. A file in another frame was then cut by the wrong box, or
placed kilometers away.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, box

from hydromodpy.cli.exit_codes import EXIT_VALIDATION, exit_code_for
from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.data.variables.dem.custom import load_custom_dem
from hydromodpy.data.variables.geology.custom import load_custom_geology
from hydromodpy.data.variables.hydrography.custom import load_file


def _raster(path: Path, *, crs: str | None) -> Path:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=4,
        height=4,
        count=1,
        dtype="float32",
        transform=from_origin(350000.0, 6790000.0, 25.0, 25.0),
        crs=crs,
        nodata=-9999.0,
    ) as dst:
        dst.write(np.ones((1, 4, 4), dtype="float32"))
    return path


@pytest.mark.fast
def test_a_dem_without_a_crs_is_refused(tmp_path: Path) -> None:
    path = _raster(tmp_path / "dem.tif", crs=None)

    with pytest.raises(DataContractViolation, match=r"dem: .*dem\.tif declares no CRS") as info:
        load_custom_dem(SimpleNamespace(path=path))

    assert exit_code_for(info.value) == EXIT_VALIDATION


@pytest.mark.fast
def test_a_dem_with_a_crs_keeps_it(tmp_path: Path) -> None:
    path = _raster(tmp_path / "dem.tif", crs="EPSG:32630")

    (record,) = load_custom_dem(SimpleNamespace(path=path))

    assert "32630" in record.crs


@pytest.mark.fast
def test_a_geology_raster_without_a_crs_is_refused(tmp_path: Path) -> None:
    path = _raster(tmp_path / "geology.tif", crs=None)

    with pytest.raises(DataContractViolation, match="geology: .*declares no CRS"):
        load_custom_geology(SimpleNamespace(path=path))


@pytest.mark.fast
def test_a_geology_vector_without_a_crs_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "geology.gpkg"
    gpd.GeoDataFrame({"code": [1]}, geometry=[box(0, 0, 10, 10)]).to_file(path)

    with pytest.raises(DataContractViolation, match="geology: .*declares no CRS"):
        load_custom_geology(SimpleNamespace(path=path), code_field="code")


@pytest.mark.fast
def test_a_river_network_without_a_crs_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "rivers.gpkg"
    gpd.GeoDataFrame(geometry=[LineString([(0, 0), (10, 10)])]).to_file(path)

    with pytest.raises(DataContractViolation, match="hydrography: .*declares no CRS"):
        load_file(SimpleNamespace(path=path))


@pytest.mark.fast
def test_a_river_raster_without_a_crs_is_refused(tmp_path: Path) -> None:
    path = _raster(tmp_path / "rivers.tif", crs=None)

    with pytest.raises(DataContractViolation, match="hydrography: .*declares no CRS"):
        load_file(SimpleNamespace(path=path))


@pytest.mark.fast
def test_a_dem_that_rasterio_does_not_open_is_left_to_the_step_that_reads_it(
    tmp_path: Path,
) -> None:
    from hydromodpy.data.variables.dem.resolver import require_dem_crs

    (tmp_path / "points.xyz").write_text("0 0 1\n")
    (tmp_path / "broken.tif").write_bytes(b"not a tiff")

    assert require_dem_crs(tmp_path / "points.xyz") is None
    assert require_dem_crs(tmp_path / "broken.tif") is None
    assert require_dem_crs(tmp_path / "absent.tif") is None


@pytest.mark.fast
def test_the_resolve_step_refuses_a_file_dem_without_a_crs(tmp_path: Path) -> None:
    """``dem_init_path`` is gone; the DEM a ``file`` source names meets the same refusal."""
    from hydromodpy.data.variables.dem.resolver import resolve_dem

    path = _raster(tmp_path / "regional.tif", crs=None)
    source = SimpleNamespace(source="file", path=path)
    cfg = SimpleNamespace(data=SimpleNamespace(dem=SimpleNamespace(sources=[source])))

    with pytest.raises(DataContractViolation, match=r"declares no CRS"):
        resolve_dem(cfg, data_dir=tmp_path)
