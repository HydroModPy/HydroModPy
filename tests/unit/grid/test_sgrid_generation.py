"""Unit tests for hydromodpy.mesh.cartesian_grid.sgrid_generation."""

from __future__ import annotations

from pathlib import Path
import textwrap

import numpy as np
import pytest
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin

from hydromodpy.mesh.cartesian_grid.planar_discretizer import PlanarDiscretizer
from hydromodpy.mesh.cartesian_grid.sgrid_generation import StructuredGridBuilder
from hydromodpy.mesh.cartesian_grid.sgrid_config import SGridConfig


def _write_tif(path: Path, arr: np.ndarray) -> None:
    """Write one-band GTiff for tests."""
    data = np.asarray(arr, dtype=np.float32)
    transform = from_origin(0.0, float(data.shape[0]), 1.0, 1.0)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype=data.dtype,
        crs="EPSG:2154",
        transform=transform,
    ) as dst:
        dst.write(data, 1)


def test_config_raises_for_missing_top_path():
    with pytest.raises(ValueError, match="value cannot be empty"):
        _ = SGridConfig(
            top_path="",
            genmtd_bot="constant_thickness",
            thick=25.0,
            genmtd_lay="constant",
            nlay=2,
        )


def test_config_raises_for_unstructured_not_implemented(tmp_path: Path):
    top_path = tmp_path / "top.tif"
    _write_tif(top_path, np.array([[10, 11], [12, 13]], dtype=float))

    with pytest.raises(ValueError, match="not implemented yet"):
        _ = SGridConfig(
            sgrid_type="unstructured",
            top_path=str(top_path),
            genmtd_bot="constant_altitude",
            zbot=0.0,
            genmtd_lay="constant",
            nlay=2,
        )


def test_config_raises_for_invalid_lay_proportions_sum(tmp_path: Path):
    top_path = tmp_path / "top.tif"
    _write_tif(top_path, np.array([[10, 11], [12, 13]], dtype=float))

    with pytest.raises(ValueError, match="sum to 1.0"):
        _ = SGridConfig(
            top_path=str(top_path),
            genmtd_bot="constant_thickness",
            thick=100.0,
            genmtd_lay="list",
            lay_proportions=[0.2, 0.3],
        )


def test_config_shape_mode_requires_nx_ny(tmp_path: Path):
    top_path = tmp_path / "top.tif"
    _write_tif(top_path, np.array([[10, 11], [12, 13]], dtype=float))

    with pytest.raises(ValueError, match="nx and ny are required"):
        _ = SGridConfig(
            top_path=str(top_path),
            plan_discretization_mode="shape",
            nx=4,
            genmtd_bot="constant_altitude",
            zbot=0.0,
            genmtd_lay="constant",
            nlay=2,
        )


def test_config_raster_native_rejects_nx_ny(tmp_path: Path):
    top_path = tmp_path / "top.tif"
    _write_tif(top_path, np.array([[10, 11], [12, 13]], dtype=float))

    with pytest.raises(ValueError, match="must not be provided"):
        _ = SGridConfig(
            top_path=str(top_path),
            plan_discretization_mode="raster_native",
            nx=4,
            ny=3,
            genmtd_bot="constant_altitude",
            zbot=0.0,
            genmtd_lay="constant",
            nlay=2,
        )


def test_builder_with_top_and_bottom_rasters_filepath(tmp_path: Path):
    top = np.array([[20.0, 21.0], [22.0, 23.0]], dtype=float)
    bot = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=float)
    top_path = tmp_path / "top.tif"
    bot_path = tmp_path / "bot.tif"
    _write_tif(top_path, top)
    _write_tif(bot_path, bot)

    cfg = SGridConfig(
        top_path=str(top_path),
        genmtd_bot="filepath",
        bot_path=str(bot_path),
        genmtd_lay="constant",
        nlay=2,
    )
    sgrid = StructuredGridBuilder().build(cfg)
    assert sgrid.nlay == 2
    assert sgrid.top.shape == top.shape
    assert sgrid.botm.shape == (2, *top.shape)
    assert np.allclose(sgrid.botm[-1], bot)


def test_builder_with_bottom_raster_array(tmp_path: Path):
    top = np.array([[20.0, 21.0], [22.0, 23.0]], dtype=float)
    bot = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=float)
    top_path = tmp_path / "top.tif"
    _write_tif(top_path, top)

    cfg = SGridConfig(
        top_path=str(top_path),
        genmtd_bot="raster",
        bot_raster=bot,
        genmtd_lay="constant",
        nlay=2,
    )
    sgrid = StructuredGridBuilder().build(cfg)
    assert sgrid.nlay == 2
    assert np.allclose(sgrid.botm[-1], bot)


def test_builder_shape_mode_resamples_top_and_bottom_filepath(tmp_path: Path):
    top = np.array([[20.0, 24.0], [22.0, 26.0]], dtype=float)
    bot = np.array([[10.0, 14.0], [12.0, 16.0]], dtype=float)
    top_path = tmp_path / "top.tif"
    bot_path = tmp_path / "bot.tif"
    _write_tif(top_path, top)
    _write_tif(bot_path, bot)

    cfg = SGridConfig(
        top_path=str(top_path),
        plan_discretization_mode="shape",
        nx=4,
        ny=3,
        genmtd_bot="filepath",
        bot_path=str(bot_path),
        genmtd_lay="constant",
        nlay=2,
    )
    sgrid = StructuredGridBuilder().build(cfg)
    assert sgrid.nrow == 3
    assert sgrid.ncol == 4
    assert sgrid.top.shape == (3, 4)
    assert sgrid.botm.shape == (2, 3, 4)
    assert float(np.nanmin(sgrid.top)) >= float(np.min(top)) - 1.0e-6
    assert float(np.nanmax(sgrid.top)) <= float(np.max(top)) + 1.0e-6
    assert float(np.nanmin(sgrid.botm[-1])) >= float(np.min(bot)) - 1.0e-6
    assert float(np.nanmax(sgrid.botm[-1])) <= float(np.max(bot)) + 1.0e-6


def test_compute_bottom_surface_raises_on_shape_mismatch():
    top = np.ones((2, 2), dtype=float)
    bot = np.ones((3, 2), dtype=float)
    with pytest.raises(ValueError, match="shape mismatch"):
        _ = StructuredGridBuilder._compute_bottom_surface(
            top=top,
            nodata=-9999,
            genmtd_bot="raster",
            bot_raster=bot,
        )


def test_planar_discretizer_select_resampling():
    assert (
        PlanarDiscretizer.select_resampling(src_shape=(10, 10), dst_shape=(20, 20))
        == Resampling.bilinear
    )
    assert (
        PlanarDiscretizer.select_resampling(src_shape=(20, 20), dst_shape=(10, 10))
        == Resampling.average
    )


def test_compute_layer_proportions_and_build_botm():
    allp, nlay = StructuredGridBuilder._compute_layer_proportions(
        genmtd_lay="decay",
        nlay=3,
        lay_decay=2.0,
    )
    assert nlay == 3
    assert np.all(np.diff(allp) > 0)
    assert allp[-1] == pytest.approx(1.0)

    top = np.array([[10.0, 10.0], [10.0, 10.0]], dtype=float)
    bot = np.array([[4.0, 5.0], [6.0, 7.0]], dtype=float)
    botm = StructuredGridBuilder._build_botm(top=top, bot=bot, nodata=-9999, allp=allp)

    assert botm.shape == (3, 2, 2)
    assert np.allclose(botm[-1], bot)


def test_config_from_toml_builds_valid_grid(tmp_path: Path):
    top_path = tmp_path / "top.tif"
    _write_tif(top_path, np.array([[100.0, 101.0], [102.0, 103.0]], dtype=float))

    config_path = tmp_path / "sgrid.toml"
    config_path.write_text(
        textwrap.dedent(
            f"""
            [sgrid]
            sgrid_type = "structured"
            lenuni = "m"
            genmtd_top = "filepath"
            top_path = "{top_path.name}"
            crs = "EPSG:2154"
            genmtd_bot = "constant_altitude"
            zbot = 0.0
            genmtd_lay = "constant"
            nlay = 2
            nodata = -9999
            """
        ),
        encoding="utf-8",
    )

    cfg = SGridConfig.from_toml(config_path)
    sgrid = StructuredGridBuilder().build(cfg)
    assert sgrid.nlay == 2
    assert sgrid.nrow == 2
    assert sgrid.ncol == 2


def test_config_from_toml_shape_mode_builds_resampled_grid(tmp_path: Path):
    top_path = tmp_path / "top.tif"
    _write_tif(top_path, np.array([[100.0, 101.0], [102.0, 103.0]], dtype=float))

    config_path = tmp_path / "sgrid_shape.toml"
    config_path.write_text(
        textwrap.dedent(
            f"""
            [sgrid]
            sgrid_type = "structured"
            lenuni = "m"
            genmtd_top = "filepath"
            top_path = "{top_path.name}"
            plan_discretization_mode = "shape"
            nx = 5
            ny = 4
            genmtd_bot = "constant_altitude"
            zbot = 0.0
            genmtd_lay = "constant"
            nlay = 2
            nodata = -9999
            """
        ),
        encoding="utf-8",
    )

    cfg = SGridConfig.from_toml(config_path)
    sgrid = StructuredGridBuilder().build(cfg)
    assert sgrid.nlay == 2
    assert sgrid.nrow == 4
    assert sgrid.ncol == 5


def test_config_from_mapping_builds_valid_grid_from_nested_mapping(tmp_path: Path):
    top_path = tmp_path / "top.tif"
    _write_tif(top_path, np.array([[100.0, 101.0], [102.0, 103.0]], dtype=float))

    config_data = {
        "sgrid": {
            "sgrid_type": "structured",
            "lenuni": "m",
            "genmtd_top": "filepath",
            "top_path": str(top_path),
            "crs": "EPSG:2154",
            "genmtd_bot": "constant_altitude",
            "zbot": 0.0,
            "genmtd_lay": "constant",
            "nlay": 2,
            "nodata": -9999,
        }
    }

    cfg = SGridConfig.from_mapping(config_data)
    sgrid = StructuredGridBuilder().build(cfg)
    assert sgrid.nlay == 2
    assert sgrid.nrow == 2
    assert sgrid.ncol == 2


def test_structured_grid_builder_builds_without_internal_cache(tmp_path: Path):
    top_path = tmp_path / "top.tif"
    _write_tif(top_path, np.array([[50.0, 51.0], [52.0, 53.0]], dtype=float))

    cfg = SGridConfig(
        top_path=str(top_path),
        genmtd_bot="constant_altitude",
        zbot=0.0,
        genmtd_lay="constant",
        nlay=2,
        nodata=-9999,
    )
    builder = StructuredGridBuilder()

    sgrid1 = builder.build(cfg)
    sgrid2 = builder.build(cfg)

    assert sgrid1 is not sgrid2
    assert np.allclose(sgrid1.top, sgrid2.top)
    assert np.allclose(sgrid1.botm, sgrid2.botm)
