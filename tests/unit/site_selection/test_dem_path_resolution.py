from __future__ import annotations

import pytest

from hydromodpy.workflow.site_selection import _resolve_local_site_selection_dem_path


@pytest.mark.fast
def test_site_selection_dem_path_directory_is_mosaicked_in_data_root(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    np = pytest.importorskip("numpy")
    from rasterio.transform import from_origin

    dem_dir = tmp_path / "local_dem_tiles"
    dem_dir.mkdir()
    _write_tile(
        dem_dir / "west.tif",
        value=1,
        transform=from_origin(0.0, 2.0, 1.0, 1.0),
        rasterio=rasterio,
        np=np,
    )
    _write_tile(
        dem_dir / "east.tif",
        value=2,
        transform=from_origin(2.0, 2.0, 1.0, 1.0),
        rasterio=rasterio,
        np=np,
    )

    mosaic = _resolve_local_site_selection_dem_path(
        dem_dir,
        workspace_root=None,
        data_root=tmp_path / "data",
        project_extent=None,
    )

    assert mosaic.is_file()
    assert mosaic.parent == tmp_path / "data" / "dem" / "custom_mosaics"
    with rasterio.open(str(mosaic)) as src:
        assert src.width == 4
        assert src.height == 2


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
