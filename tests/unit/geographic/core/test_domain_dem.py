"""The DEM clipped to the buffered box, through either shape of the backend."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
import rasterio

from hydromodpy.spatial.geographic.core.domain_dem import clip_dem_to_box_buffer
from tests._helpers.geotiffs import write_geotiff


def _in_memory(calls: list[str]) -> SimpleNamespace:
    """The raster API of the registered backend: rasters held as objects."""
    return SimpleNamespace(
        read_raster=lambda path: ("raster", path),
        read_vector=lambda path: ("vector", path),
        clip_raster_to_polygon_raster=lambda r, v, maintain_dimensions: calls.append("clip") or r,
        modify_no_data_value_raster=lambda r, new_value: calls.append(f"nodata {new_value}") or r,
        write_raster=lambda r, path: write_geotiff(path, np.ones((2, 2)), crs=None),
    )


def _on_disk(calls: list[str]) -> SimpleNamespace:
    """The file API a backend registered through ``register_backend`` may offer instead."""
    return SimpleNamespace(
        clip_raster_to_polygon=lambda src, poly, dst, maintain_dimensions: write_geotiff(
            dst, np.ones((2, 2)), crs=None
        ),
        modify_no_data_value=lambda path, new_value: calls.append(f"nodata {new_value}"),
    )


@pytest.mark.parametrize("raster_api", [_in_memory, _on_disk], ids=["in memory", "on disk"])
def test_the_clip_is_written_with_its_nodata_and_the_project_crs(tmp_path, raster_api) -> None:
    calls: list[str] = []
    backend = SimpleNamespace(raster=raster_api(calls))

    out = clip_dem_to_box_buffer(
        dem_init_path=tmp_path / "dem.tif",
        box_buff_shp=tmp_path / "box_buff.shp",
        output_dem_path=tmp_path / "domain" / "clip.tif",
        crs_project="EPSG:2154",
        nodata=-1.0,
        backend=backend,
    )

    assert "nodata -1.0" in calls
    with rasterio.open(out) as src:
        assert src.crs.to_epsg() == 2154
