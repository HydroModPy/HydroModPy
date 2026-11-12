"""The DEM pixels of each cell, their statistics, and the zonal top of a cell mesh.

Elevations and lengths are in meters. A pixel label is a cell id, -1 outside every cell.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from rasterio.transform import from_bounds

from hydromodpy.mesh.cells.zonal_stats import (
    grouped_reduce,
    rasterize_cell_ids,
    zonal_top,
)
from hydromodpy.mesh.planar.hydro_mesh import HydroMesh
from tests._helpers.mesh_cases import regular_mesh


def _quad_mesh(*, xmin, ymin, dx, dy, ncol, nrow) -> HydroMesh:
    """Regular quad grid over a rectangle, row 0 north."""
    return regular_mesh(nrow, ncol, dx=dx, dy=dy, xmin=xmin, ymin=ymin).mesh


def _grid_transform(xmin, ymin, xmax, ymax, ncols, nrows):
    return from_bounds(xmin, ymin, xmax, ymax, ncols, nrows)


def test_rasterize_cell_ids():
    mesh = _quad_mesh(xmin=0.0, ymin=0.0, dx=50.0, dy=100.0, ncol=2, nrow=1)
    transform = _grid_transform(0.0, 0.0, 100.0, 100.0, 10, 10)
    labels = rasterize_cell_ids(mesh, transform=transform, out_shape=(10, 10))
    assert labels.shape == (10, 10)
    # Left half -> cell 0, right half -> cell 1, no pixel left as fill (-1).
    assert set(np.unique(labels).tolist()) == {0, 1}
    assert (labels[:, :5] == 0).all()
    assert (labels[:, 5:] == 1).all()


LABELS = np.array([[0, 0, 1], [0, -1, 1]])
VALUES = np.array([[1.0, 3.0, 10.0], [5.0, np.nan, 20.0]])
STATS = [
    pytest.param("min", [1.0, 10.0], id="min"),
    pytest.param("max", [5.0, 20.0], id="max"),
    pytest.param("mean", [3.0, 15.0], id="mean"),
    pytest.param("median", [3.0, 15.0], id="median"),
]


@pytest.mark.parametrize(("stat", "expected"), STATS)
def test_grouped_reduce(stat, expected):
    # Pixel labelled -1 and NaN values are left out.
    reduced = grouped_reduce(LABELS, VALUES, n_cells=2, stat=stat)

    np.testing.assert_allclose(reduced, expected)


def test_unknown_stat():
    labels = np.zeros((2, 2), dtype=int)
    values = np.ones((2, 2))
    with pytest.raises(ValueError, match="Unsupported zonal stat"):
        grouped_reduce(labels, values, n_cells=1, stat="p99")


def _notch_dem(n=40):
    """z = x plane with an incised channel notch in the left cell (x in [10,15])."""
    xs = (np.arange(n) + 0.5) * (100.0 / n)
    dem = np.tile(xs, (n, 1))
    channel = np.zeros((n, n), dtype=bool)
    notch = (xs >= 10.0) & (xs <= 15.0)
    dem[:, notch] = 5.0  # thalweg
    channel[:, notch] = True
    return dem, channel


def test_channel_min():
    mesh = _quad_mesh(xmin=0.0, ymin=0.0, dx=50.0, dy=100.0, ncol=2, nrow=1)
    dem, channel = _notch_dem(n=40)
    transform = _grid_transform(0.0, 0.0, 100.0, 100.0, 40, 40)
    centroid = np.array([25.0, 75.0])  # generator samples (unaffected by the off-center notch)
    res = zonal_top(
        planar_mesh=mesh,
        dem=dem,
        transform=transform,
        out_shape=(40, 40),
        centroid_top=centroid,
        channel_mask=channel,
        hillslope_stat="median",
        channel_stat="min",
        min_pixels=3,
        spike_guard_tol_m=0.0,
    )
    assert res.is_channel.tolist() == [True, False]
    assert res.top[0] == pytest.approx(5.0)  # channel cell -> thalweg min
    assert res.top[1] == pytest.approx(75.0, abs=1.0)  # hillslope median ~ centroid
    assert res.info["n_lowered"] == 1.0


def test_spike_guard():
    mesh = _quad_mesh(xmin=0.0, ymin=0.0, dx=50.0, dy=100.0, ncol=2, nrow=1)
    dem, _ = _notch_dem(n=40)  # hillslope median of cell 0 ~ 25 over [0,50]
    transform = _grid_transform(0.0, 0.0, 100.0, 100.0, 40, 40)
    centroid = np.array([25.0, 75.0])
    # A far-off centroid for cell 1 (median ~75) triggers the guard there.
    off_centroid = np.array([25.0, 60.0])
    res = zonal_top(
        planar_mesh=mesh,
        dem=dem,
        transform=transform,
        out_shape=(40, 40),
        centroid_top=off_centroid,
        channel_mask=None,
        hillslope_stat="median",
        min_pixels=3,
        spike_guard_tol_m=2.0,
    )
    assert res.top[1] == pytest.approx(60.0)  # reverted to centroid
    assert res.info["n_spike_reverted"] == 1.0
    _ = centroid  # cell 0 median ~25 == its centroid, no guard


def test_min_thickness():
    mesh = _quad_mesh(xmin=0.0, ymin=0.0, dx=50.0, dy=100.0, ncol=2, nrow=1)
    dem, channel = _notch_dem(n=40)  # channel cell 0 min = 5.0
    transform = _grid_transform(0.0, 0.0, 100.0, 100.0, 40, 40)
    centroid = np.array([25.0, 75.0])
    bottom = np.array([4.9, 0.0])  # cell 0 bottom just below the thalweg
    res = zonal_top(
        planar_mesh=mesh,
        dem=dem,
        transform=transform,
        out_shape=(40, 40),
        centroid_top=centroid,
        channel_mask=channel,
        channel_stat="min",
        spike_guard_tol_m=0.0,
        bottom=bottom,
        min_thickness_m=0.5,
    )
    # min top would be 5.0 but bottom+thickness = 5.4 wins.
    assert res.top[0] == pytest.approx(5.4)
    assert res.info["n_thickness_clamped"] == 1.0


def test_nodata_excluded():
    mesh = _quad_mesh(xmin=0.0, ymin=0.0, dx=100.0, dy=100.0, ncol=1, nrow=1)
    n = 20
    dem = np.full((n, n), 10.0)
    dem[0, 0] = -9999.0  # a nodata sentinel that would corrupt min if counted
    transform = _grid_transform(0.0, 0.0, 100.0, 100.0, n, n)
    res = zonal_top(
        planar_mesh=mesh,
        dem=dem,
        transform=transform,
        out_shape=(n, n),
        centroid_top=np.array([10.0]),
        channel_mask=None,
        hillslope_stat="min",
        nodata=-9999.0,
        spike_guard_tol_m=0.0,
    )
    assert res.top[0] == pytest.approx(10.0)  # nodata not dragged into the min


def test_low_percentiles():
    labels = np.zeros((1, 11), dtype=int)
    values = np.arange(11.0).reshape(1, 11)

    assert grouped_reduce(labels, values, n_cells=1, stat="p10").tolist() == [1.0]
    assert grouped_reduce(labels, values, n_cells=1, stat="p25").tolist() == [2.5]


def test_short_cell_burns_no_pixel():
    transform = _grid_transform(0.0, 0.0, 10.0, 10.0, 10, 10)
    line_cell = np.asarray([0, 1])
    stand_in = SimpleNamespace(
        vertices=np.asarray([(0.0, 0.0), (10.0, 0.0), (0.0, 10.0)]),
        flat_connectivity=(line_cell, np.asarray([0, 1, 2])),
    )
    only_lines = SimpleNamespace(vertices=stand_in.vertices, flat_connectivity=(line_cell,))

    labels = rasterize_cell_ids(stand_in, transform=transform, out_shape=(10, 10))

    assert set(np.unique(labels).tolist()) == {-1, 1}
    assert (rasterize_cell_ids(only_lines, transform=transform, out_shape=(10, 10)) == -1).all()


def test_zonal_top_needs_a_mesh():
    with pytest.raises(ValueError, match="needs a planar_mesh or the pixel labels"):
        zonal_top(
            planar_mesh=None,
            dem=np.zeros((4, 4)),
            transform=_grid_transform(0.0, 0.0, 4.0, 4.0, 4, 4),
            out_shape=(4, 4),
            centroid_top=np.zeros(1),
            channel_mask=None,
        )
