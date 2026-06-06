from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.data.variables.dem.custom import load_custom_dem


@pytest.mark.fast
def test_custom_dem_directory_with_multiple_tiles_is_mosaicked(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    np = pytest.importorskip("numpy")
    from rasterio.transform import from_origin

    dem_dir = tmp_path / "dem_tiles"
    dem_dir.mkdir()
    _write_tile(
        dem_dir / "tile_west.tif",
        value=10,
        transform=from_origin(0.0, 2.0, 1.0, 1.0),
        rasterio=rasterio,
        np=np,
    )
    _write_tile(
        dem_dir / "tile_east.tif",
        value=20,
        transform=from_origin(2.0, 2.0, 1.0, 1.0),
        rasterio=rasterio,
        np=np,
    )

    records = load_custom_dem(
        SimpleNamespace(path=dem_dir),
        data_dir=tmp_path / "cache" / "dem",
    )

    assert len(records) == 1
    mosaic_path = records[0].data
    assert mosaic_path.is_file()
    assert mosaic_path.parent.name == "custom_mosaics"
    assert mosaic_path.name.startswith("dem_custom_mosaic_")

    with rasterio.open(str(mosaic_path)) as src:
        assert src.width == 4
        assert src.height == 2
        assert tuple(src.bounds) == pytest.approx((0.0, 0.0, 4.0, 2.0))


def _write_tile(path, *, value, transform, rasterio, np):
    data = np.full((1, 2, 2), value, dtype="float32")
    with rasterio.open(
        str(path),
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        transform=transform,
    ) as dst:
        dst.write(data)
