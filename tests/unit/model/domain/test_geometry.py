"""The DEM grid and the catchment are read off a delineation once, by attribute name."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.catchment.preprocess.capped_breach_config import (
    CappedBreachConfig,
    capped_breach_of,
)
from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
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


@pytest.mark.parametrize("name", RASTER_NAMES)
def test_the_raster_holds_the_delineation_s_own_objects(name: str) -> None:
    geographic = _delineation()

    raster = RasterGeometry.from_geographic(geographic)

    assert getattr(raster, name) is getattr(geographic, name)


def test_the_raster_keeps_the_conditioning_so_a_solver_conditions_as_the_delineation() -> None:
    geographic = _delineation()
    raster = RasterGeometry.from_geographic(geographic)

    assert raster.dem_correc_type == "capped_breach"
    assert capped_breach_of(raster) == capped_breach_of(geographic)


def test_a_bare_object_reads_none_and_the_default_conditioning() -> None:
    raster = RasterGeometry.from_geographic(object())

    assert all(getattr(raster, name) is None for name in RASTER_NAMES)
    assert raster.dem_correc_type == GeographicConfig.model_fields["dem_correc_type"].default
    assert raster.channel is None


def test_the_raster_carries_the_channel_rasters_it_is_given() -> None:
    channel = ChannelRasters(
        enabled=True,
        link="/run/flow/dem_stream_link_id_full.tif",
        pointer="/run/flow/direc.tif",
        accumulation="/run/flow/dem_acc_cells.tif",
        clipped=("/run/river_stream_link_id.tif",),
    )

    raster = RasterGeometry.from_geographic(_delineation(), channel=channel)

    assert raster.channel is channel


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


@pytest.mark.parametrize("name", CATCHMENT_NAMES)
def test_the_catchment_reads_each_attribute_under_its_own_name(name: str) -> None:
    geographic = _delineation()

    catchment = CatchmentGeometry.from_geographic(geographic, crs="EPSG:2154")

    assert getattr(catchment, name) == getattr(geographic, name)


def test_the_catchment_carries_the_project_crs_it_is_given() -> None:
    catchment = CatchmentGeometry.from_geographic(_delineation(), crs="EPSG:2154")

    assert catchment.crs == "EPSG:2154"


def test_a_bare_object_gives_a_catchment_of_nones() -> None:
    catchment = CatchmentGeometry.from_geographic(object(), crs=None)

    assert all(getattr(catchment, name) is None for name in (*CATCHMENT_NAMES, "crs"))


FROZEN = (
    (lambda: RasterGeometry.from_geographic(_delineation()), "dem_res"),
    (lambda: CatchmentGeometry.from_geographic(_delineation(), crs=None), "crs"),
    (lambda: ChannelRasters(enabled=True, link=None, pointer=None, accumulation=None), "link"),
)


@pytest.mark.parametrize(("build", "field"), FROZEN, ids=["raster", "catchment", "channel"])
def test_the_geometry_records_are_frozen(build, field: str) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(build(), field, None)
