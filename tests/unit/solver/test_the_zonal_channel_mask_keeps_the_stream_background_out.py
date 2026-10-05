"""The zonal channel mask holds the stream pixels, not the background of the raster.

GDAL moves a valid source pixel equal to the destination nodata to the next
float. With a destination nodata of 0, every background pixel of a stream raster
became 5e-324 and the channel class covered the whole catchment.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import rasterio
from rasterio.transform import from_origin

from hydromodpy.solver.modflow6 import build
from hydromodpy.spatial.mesh.cartesian_grid.sgrid_config import TopSamplingConfig


def test_only_the_stream_pixels_are_channel(tmp_path) -> None:
    links = np.zeros((20, 20), dtype=np.int32)
    links[:2, :] = -32768  # outside the catchment
    links[10, 3:9] = 185  # one reach of six pixels
    path = tmp_path / "river_stream_link_id.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=20,
        width=20,
        count=1,
        dtype="int32",
        nodata=-32768,
        crs="EPSG:2154",
        transform=from_origin(1000.0, 2000.0, 25.0, 25.0),
    ) as dst:
        dst.write(links, 1)
    # A wider support than the stream raster, so the reprojection really resamples.
    support = SimpleNamespace(
        xmin=950.0, xmax=1550.0, ymin=1450.0, ymax=2050.0, nrows=24, ncols=24, crs="EPSG:2154"
    )
    model = SimpleNamespace(
        modflow_config=SimpleNamespace(
            sgrid=SimpleNamespace(top_sampling=TopSamplingConfig(mode="zonal"))
        ),
        geographic=SimpleNamespace(river_stream_link_id_tif=str(path), river_streams_tif=None),
        domain=SimpleNamespace(surface_topo=SimpleNamespace(support=support)),
    )

    mask = build._resolve_channel_mask_for_zonal(model)

    assert mask is not None
    assert int(mask.sum()) == 6


def _write_links(
    path, links: np.ndarray, *, origin: tuple[float, float] = (1000.0, 2000.0)
) -> None:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=links.shape[0],
        width=links.shape[1],
        count=1,
        dtype="int32",
        nodata=-32768,
        crs="EPSG:2154",
        transform=from_origin(origin[0], origin[1], 25.0, 25.0),
    ) as dst:
        dst.write(links, 1)


def test_the_full_extent_tree_is_read_before_the_clipped_raster(tmp_path, caplog) -> None:
    clipped = np.zeros((20, 20), dtype=np.int32)
    clipped[10, 3:9] = 185  # six pixels inside the watershed
    full = clipped.copy()
    full[10, 12:18] = 185  # the same river below the outlet, in the buffer
    clipped_path = tmp_path / "river_stream_link_id.tif"
    _write_links(clipped_path, clipped)
    folder = tmp_path / "correcflow"
    folder.mkdir()
    _write_links(folder / "dem_stream_link_id_full.tif", full)
    support = SimpleNamespace(
        xmin=1000.0, xmax=1500.0, ymin=1500.0, ymax=2000.0, nrows=20, ncols=20, crs="EPSG:2154"
    )
    model = SimpleNamespace(
        modflow_config=SimpleNamespace(
            sgrid=SimpleNamespace(top_sampling=TopSamplingConfig(mode="zonal"))
        ),
        geographic=SimpleNamespace(
            river_stream_link_id_tif=str(clipped_path),
            river_streams_tif=None,
            correcflow_path=str(folder),
        ),
        domain=SimpleNamespace(surface_topo=SimpleNamespace(support=support)),
    )

    with caplog.at_level("INFO"):
        mask = build._resolve_channel_mask_for_zonal(model)

    assert int(mask.sum()) == 12
    assert any("full-extent channel tree" in r.getMessage() for r in caplog.records)


def test_the_streams_full_raster_is_the_second_choice(tmp_path) -> None:
    links = np.zeros((20, 20), dtype=np.int32)
    links[5, 2:6] = 1
    folder = tmp_path / "correcflow"
    folder.mkdir()
    _write_links(folder / "dem_streams_full.tif", links)
    support = SimpleNamespace(
        xmin=1000.0, xmax=1500.0, ymin=1500.0, ymax=2000.0, nrows=20, ncols=20, crs="EPSG:2154"
    )
    model = SimpleNamespace(
        modflow_config=SimpleNamespace(
            sgrid=SimpleNamespace(top_sampling=TopSamplingConfig(mode="zonal"))
        ),
        geographic=SimpleNamespace(
            river_stream_link_id_tif=None, river_streams_tif=None, correcflow_path=str(folder)
        ),
        domain=SimpleNamespace(surface_topo=SimpleNamespace(support=support)),
    )

    assert int(build._resolve_channel_mask_for_zonal(model).sum()) == 4
