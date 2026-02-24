"""Unit tests for hydromodpy.mesh.cartesian_grid.sgrid_generation."""

from __future__ import annotations

from pathlib import Path
import textwrap

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from hydromodpy.mesh.cartesian_grid.sgrid_generation import SGrid_Generation


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


def test_run_raises_for_missing_top_path():
    grid = SGrid_Generation()
    grid.genmtd_bot = "constant_thickness"
    grid.thick = 25.0
    grid.genmtd_lay = "constant"
    grid.nlay = 2

    with pytest.raises(ValueError, match="top_path is required"):
        _ = grid.run()


def test_run_raises_for_unstructured_not_implemented():
    grid = SGrid_Generation()
    grid.sgrid_type = "unstructured"

    with pytest.raises(NotImplementedError, match="Unstructured spatial grid"):
        _ = grid.run()


def test_run_raises_for_invalid_lay_proportions_sum(tmp_path: Path):
    top_path = tmp_path / "top.tif"
    _write_tif(top_path, np.array([[10, 11], [12, 13]], dtype=float))

    grid = SGrid_Generation()
    grid.top_path = str(top_path)
    grid.genmtd_bot = "constant_thickness"
    grid.thick = 100.0
    grid.genmtd_lay = "list"
    grid.lay_proportions = [0.2, 0.3]

    with pytest.raises(ValueError, match="sum to 1.0"):
        _ = grid.run()


def test_run_with_top_and_bottom_rasters_filepath(tmp_path: Path):
    top = np.array([[20.0, 21.0], [22.0, 23.0]], dtype=float)
    bot = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=float)
    top_path = tmp_path / "top.tif"
    bot_path = tmp_path / "bot.tif"
    _write_tif(top_path, top)
    _write_tif(bot_path, bot)

    grid = SGrid_Generation()
    grid.top_path = str(top_path)
    grid.genmtd_bot = "filepath"
    grid.bot_path = str(bot_path)
    grid.genmtd_lay = "constant"
    grid.nlay = 2

    sgrid = grid.run()
    assert sgrid.nlay == 2
    assert sgrid.top.shape == top.shape
    assert sgrid.botm.shape == (2, *top.shape)
    assert np.allclose(sgrid.botm[-1], bot)


def test_compute_bottom_surface_raises_on_shape_mismatch():
    top = np.ones((2, 2), dtype=float)
    bot = np.ones((3, 2), dtype=float)
    with pytest.raises(ValueError, match="shape mismatch"):
        _ = SGrid_Generation._compute_bottom_surface(
            top=top,
            nodata=-9999,
            genmtd_bot="raster",
            bot_raster=bot,
        )


def test_compute_layer_proportions_and_build_botm():
    allp, nlay = SGrid_Generation._compute_layer_proportions(
        genmtd_lay="decay",
        nlay=3,
        lay_decay=2.0,
    )
    assert nlay == 3
    assert np.all(np.diff(allp) > 0)
    assert allp[-1] == pytest.approx(1.0)

    top = np.array([[10.0, 10.0], [10.0, 10.0]], dtype=float)
    bot = np.array([[4.0, 5.0], [6.0, 7.0]], dtype=float)
    botm = SGrid_Generation._build_botm(top=top, bot=bot, nodata=-9999, allp=allp)

    assert botm.shape == (3, 2, 2)
    assert np.allclose(botm[-1], bot)


def test_from_toml_builds_valid_grid(tmp_path: Path):
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

    sgrid = SGrid_Generation.from_toml(config_path).run()
    assert sgrid.nlay == 2
    assert sgrid.nrow == 2
    assert sgrid.ncol == 2
