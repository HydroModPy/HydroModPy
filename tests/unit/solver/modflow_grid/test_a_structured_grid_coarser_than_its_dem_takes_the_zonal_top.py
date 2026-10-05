"""Zonal top on a structured grid coarser than its DEM (phase 5).

A 12 x 12 DEM of 25 m pixels is resampled to a 4 x 4 grid of 75 m cells, so every
cell holds a 3 x 3 block of pixels. With ``top_sampling.mode = "zonal"`` a channel
cell takes the minimum of its block and a hillslope cell the median; ``centroid``
and ``keep_native`` keep today's values.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest

from hydromodpy.solver.modflow_grid import build_spatial_discretization
from hydromodpy.spatial import RasterSupport, Surface
from hydromodpy.spatial.domain import Domain, DomainConfig
from hydromodpy.spatial.mesh.cartesian_grid.sgrid_config import (
    PlanarGridConfig,
    SolverSGridConfig,
    TopSamplingConfig,
    VerticalGridConfig,
)
from hydromodpy.spatial.mesh.ops.zonal_stats import regular_grid_cell_ids

_PIXEL = 25.0
_N = 12
_BLOCK = 3
_NODATA = -9999.0


def _surface(values: np.ndarray, name: str) -> Surface:
    n = values.shape[0]
    support = RasterSupport(
        crs="EPSG:2154",
        dx=_PIXEL,
        dy=_PIXEL,
        xmin=0.0,
        xmax=_PIXEL * n,
        ymin=0.0,
        ymax=_PIXEL * n,
        nrows=n,
        ncols=n,
        nodata=_NODATA,
    )
    return Surface(name=name, values=values, support=support)


def _hill_dem() -> np.ndarray:
    """A plane sloping east, plus a flat spike-free relief inside every block."""
    rng = np.random.default_rng(3)
    base = 100.0 + 0.02 * np.arange(_N)[None, :] * _PIXEL
    return base + rng.uniform(0.0, 0.5, size=(_N, _N))


def _domain(dem: np.ndarray, bottom: float = 0.0) -> Domain:
    domain = Domain(config=DomainConfig(), surface_topo=_surface(dem, "surface_topo"))
    domain.substratum = _surface(np.full(dem.shape, bottom), "substratum")
    return domain


def _sgrid(top_sampling: TopSamplingConfig, *, planar: PlanarGridConfig | None = None):
    return SolverSGridConfig(
        planar=planar
        or PlanarGridConfig(mode="resample_to_shape", nx=_N // _BLOCK, ny=_N // _BLOCK),
        vertical=VerticalGridConfig(nlay=1, nodata=_NODATA),
        top_sampling=top_sampling,
    )


def _blocks(array: np.ndarray) -> np.ndarray:
    """(4, 4, 9) pixels of every 75 m cell."""
    n = _N // _BLOCK
    return array.reshape(n, _BLOCK, n, _BLOCK).transpose(0, 2, 1, 3).reshape(n, n, -1)


def _channel_mask() -> np.ndarray:
    """One channel pixel in cell (1, 2) and a full column of them in cell (3, 0)."""
    mask = np.zeros((_N, _N), dtype=bool)
    mask[4, 7] = True
    mask[9:12, 1] = True
    return mask


def _top(ctx) -> np.ndarray:
    n = _N // _BLOCK
    return np.asarray(ctx.solver_mesh.top, dtype=float).reshape(n, n)


def test_a_channel_cell_takes_the_minimum_of_its_pixels_and_a_hillslope_cell_the_median():
    dem = _hill_dem()
    dem[4, 7] -= 4.0  # incised thalweg pixel, inside cell (1, 2)
    dem[9:12, 1] -= 3.0
    mask = _channel_mask()
    ctx = build_spatial_discretization(
        domain=_domain(dem),
        sgrid_config=_sgrid(TopSamplingConfig(mode="zonal", spike_guard_tol_m=0.0)),
        channel_mask=mask,
    )
    top = _top(ctx)
    pixels = _blocks(dem)
    channel = _blocks(mask).any(axis=-1)
    assert channel.sum() == 2
    for row in range(top.shape[0]):
        for col in range(top.shape[1]):
            if channel[row, col]:
                expected = pixels[row, col][_blocks(mask)[row, col]].min()
            else:
                expected = np.median(pixels[row, col])
            assert top[row, col] == pytest.approx(expected)


def test_a_channel_cell_lies_below_the_plain_resample_of_the_dem():
    dem = _hill_dem()
    dem[4, 7] -= 4.0
    mask = _channel_mask()
    plain = build_spatial_discretization(
        domain=_domain(dem),
        sgrid_config=_sgrid(TopSamplingConfig(mode="centroid")),
        channel_mask=mask,
    )
    zonal = build_spatial_discretization(
        domain=_domain(dem),
        sgrid_config=_sgrid(TopSamplingConfig(mode="zonal", spike_guard_tol_m=0.0)),
        channel_mask=mask,
    )
    assert _top(zonal)[1, 2] < _top(plain)[1, 2] - 1.0


def test_centroid_keeps_the_resampled_top_byte_for_byte():
    dem = _hill_dem()
    centroid = build_spatial_discretization(
        domain=_domain(dem),
        sgrid_config=_sgrid(TopSamplingConfig(mode="centroid")),
        channel_mask=_channel_mask(),
    )
    n = _N // _BLOCK
    resampled = _surface(dem, "surface_topo").resample_to_shape(
        n, n, resampling=PlanarGridConfig().resampling, nodata=_NODATA
    )
    assert np.array_equal(
        centroid.solver_mesh.top, np.asarray(resampled.as_array(), dtype=float).reshape(-1)
    )


def test_keep_native_is_unchanged_by_the_zonal_mode():
    dem = _hill_dem()
    keep = PlanarGridConfig(mode="keep_native")
    plain = build_spatial_discretization(
        domain=_domain(dem), sgrid_config=_sgrid(TopSamplingConfig(), planar=keep)
    )
    zonal = build_spatial_discretization(
        domain=_domain(dem),
        sgrid_config=_sgrid(TopSamplingConfig(mode="zonal"), planar=keep),
        channel_mask=_channel_mask(),
    )
    assert np.array_equal(plain.solver_mesh.top, zonal.solver_mesh.top)
    assert np.array_equal(plain.solver_mesh.top, dem.reshape(-1))


def test_a_grid_of_the_dem_pixels_gives_the_pixel_values_in_zonal_mode():
    dem = _hill_dem()
    dem[4, 7] -= 4.0
    same_shape = PlanarGridConfig(mode="resample_to_shape", nx=_N, ny=_N)
    ctx = build_spatial_discretization(
        domain=_domain(dem),
        sgrid_config=_sgrid(TopSamplingConfig(mode="zonal"), planar=same_shape),
        channel_mask=_channel_mask(),
    )
    assert np.asarray(ctx.solver_mesh.top).reshape(_N, _N) == pytest.approx(dem)


def test_the_minimum_thickness_clamp_holds_under_a_lowered_channel():
    dem = _hill_dem()
    dem[4, 7] = 50.0  # thalweg far below the rest of its block
    bottom = 49.95  # only 5 cm under the thalweg pixel
    ctx = build_spatial_discretization(
        domain=_domain(dem, bottom=bottom),
        sgrid_config=_sgrid(TopSamplingConfig(mode="zonal", min_thickness_m=0.1)),
        channel_mask=_channel_mask(),
    )
    assert _top(ctx)[1, 2] == pytest.approx(bottom + 0.1)


def test_a_cell_without_data_stays_inactive_in_zonal_mode():
    dem = _hill_dem()
    dem[:_BLOCK, :_BLOCK] = _NODATA
    plain = build_spatial_discretization(
        domain=_domain(dem), sgrid_config=_sgrid(TopSamplingConfig())
    )
    zonal = build_spatial_discretization(
        domain=_domain(dem),
        sgrid_config=_sgrid(TopSamplingConfig(mode="zonal")),
        channel_mask=_channel_mask(),
    )
    assert np.array_equal(plain.solver_mesh.inactive_mask, zonal.solver_mesh.inactive_mask)
    assert zonal.solver_mesh.inactive_mask[0, 0]


def test_the_cell_ids_follow_the_row_major_order_of_the_grid():
    from rasterio.transform import from_bounds

    size = _PIXEL * _N
    transform = from_bounds(0.0, 0.0, size, size, _N, _N)
    labels = regular_grid_cell_ids(
        dem_transform=transform,
        dem_shape=(_N, _N),
        grid_bounds=(0.0, size, 0.0, size),
        grid_shape=(4, 4),
    )
    assert labels[0, 0] == 0  # north-west pixel, first cell
    assert labels[0, _N - 1] == 3
    assert labels[_N - 1, 0] == 12
    assert labels[4, 7] == 1 * 4 + 2
    assert np.all(np.bincount(labels.reshape(-1)) == _BLOCK * _BLOCK)


def test_dead_cells_are_not_counted_as_zonal_or_clamped(caplog):
    dem = _hill_dem()
    dem[:_BLOCK, :_BLOCK] = _NODATA  # cell (0, 0) is dead
    with caplog.at_level(logging.INFO):
        build_spatial_discretization(
            domain=_domain(dem),
            sgrid_config=_sgrid(TopSamplingConfig(mode="zonal")),
            channel_mask=_channel_mask(),
        )
    line = next(r.getMessage() for r in caplog.records if "Zonal top sampling:" in r.getMessage())
    assert "15/15 cells zonal" in line
    assert "0 thickness-clamped" in line


def test_zonal_top_leaves_inactive_cells_on_the_fallback():
    from rasterio.transform import from_bounds

    from hydromodpy.spatial.mesh.ops.zonal_stats import zonal_top

    size = _PIXEL * _N
    labels = regular_grid_cell_ids(
        dem_transform=from_bounds(0.0, 0.0, size, size, _N, _N),
        dem_shape=(_N, _N),
        grid_bounds=(0.0, size, 0.0, size),
        grid_shape=(4, 4),
    )
    dem = np.full((_N, _N), 10.0)
    centroid = np.full(16, 11.0)
    active = np.ones(16, dtype=bool)
    active[5] = False
    result = zonal_top(
        labels=labels,
        active=active,
        dem=dem,
        transform=None,
        out_shape=(_N, _N),
        centroid_top=centroid,
        bottom=np.full(16, 10.5),
        spike_guard_tol_m=0.0,
    )
    assert result.top[5] == 11.0
    assert result.top[4] == pytest.approx(10.6)  # live cell, clamped to bottom + 0.1
    assert result.info["n_cells"] == 15.0
    assert result.info["n_thickness_clamped"] == 15.0


@pytest.mark.parametrize("n_cells", [_N, 2 * _N])
def test_a_grid_not_coarser_than_two_pixels_keeps_the_resample_and_says_why(n_cells, caplog):
    dem = _hill_dem()
    dem[4, 7] -= 4.0
    planar = PlanarGridConfig(mode="resample_to_shape", nx=n_cells, ny=n_cells)
    with caplog.at_level(logging.INFO):
        zonal = build_spatial_discretization(
            domain=_domain(dem),
            sgrid_config=_sgrid(TopSamplingConfig(mode="zonal", min_pixels=1), planar=planar),
            channel_mask=_channel_mask(),
        )
    plain = build_spatial_discretization(
        domain=_domain(dem), sgrid_config=_sgrid(TopSamplingConfig(), planar=planar)
    )
    assert np.array_equal(plain.solver_mesh.top, zonal.solver_mesh.top)
    assert any("Zonal top sampling skipped" in r.getMessage() for r in caplog.records)
