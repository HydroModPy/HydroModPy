"""The DEM grid and the catchment are read off a delineation once, by attribute name."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from hydromodpy.catchment.preprocess.capped_breach_config import CappedBreachConfig
from hydromodpy.model.domain.geometry import CatchmentGeometry, ChannelRasters, RasterGeometry

RASTER_NAMES = (
    "dem_data",
    "dem_box_buff_data",
    "dem_res",
    "xmin",
    "ymax",
    "watershed_buff_dem",
    "watershed_box_buff_dem",
    "crs_proj",
    "terrain_engine",
    "capped_breach",
)


def _delineation() -> SimpleNamespace:
    return SimpleNamespace(
        dem_data=np.arange(6.0).reshape(2, 3),
        dem_box_buff_data=np.arange(12.0).reshape(3, 4),
        dem_res=25.0,
        xmin=1000.0,
        ymax=2000.0,
        watershed_buff_dem="/run/dem_buff.tif",
        watershed_box_buff_dem="/run/dem_box_buff.tif",
        crs_proj="EPSG:2154",
        dem_correc_type="capped_breach",
        terrain_engine="whitebox",
        capped_breach=CappedBreachConfig(),
        catch_def="from_outlet_coord",
        watershed_shp="/run/watershed.shp",
        domain_extent="watershed",
        x_outlet=1100.0,
        y_outlet=1900.0,
        x_outlet_snapped=1110.0,
        y_outlet_snapped=1890.0,
    )


def test_channel_rasters_without_a_folder_keep_the_clipped_fallback() -> None:
    channel = ChannelRasters(
        enabled=False, link=None, pointer=None, accumulation=None, clipped=("/run/s.tif",)
    )

    assert channel.clipped == ("/run/s.tif",)
    assert ChannelRasters(enabled=False, link=None, pointer=None, accumulation=None).clipped == ()


CATCHMENT_NAMES = (
    "catch_def",
    "watershed_shp",
    "domain_extent",
    "x_outlet",
    "y_outlet",
    "x_outlet_snapped",
    "y_outlet_snapped",
)


FROZEN = (
    (lambda: RasterGeometry.from_geographic(_delineation()), "dem_res"),
    (lambda: CatchmentGeometry.from_geographic(_delineation(), crs=None), "crs"),
    (lambda: ChannelRasters(enabled=True, link=None, pointer=None, accumulation=None), "link"),
)
