"""Unit tests for the mesh-agnostic zonal top sampler (Stage A)."""

from __future__ import annotations

import numpy as np
import pytest
from rasterio.transform import from_bounds

from hydromodpy.spatial.mesh.ops.zonal_stats import (
    grouped_reduce,
    rasterize_cell_ids,
    zonal_top,
)


class _QuadMesh:
    """Regular quad grid over a rectangle (planar-mesh stand-in)."""

    def __init__(self, *, xmin, ymin, dx, dy, ncol, nrow):
        xs = xmin + dx * np.arange(ncol + 1)
        ys = ymin + dy * np.arange(nrow + 1)
        verts, vid = [], {}
        for j in range(nrow + 1):
            for i in range(ncol + 1):
                vid[(i, j)] = len(verts)
                verts.append((xs[i], ys[j]))
        conn = []
        for j in range(nrow):
            for i in range(ncol):
                conn.append([vid[(i, j)], vid[(i + 1, j)], vid[(i + 1, j + 1)], vid[(i, j + 1)]])
        self.vertices = np.asarray(verts, dtype=float)
        self.flat_connectivity = np.asarray(conn, dtype=int)


class _RaggedMesh:
    """Two cells of different arity (triangle + pentagon) sharing an edge."""

    def __init__(self):
        # A unit square split by the diagonal is too degenerate for a pentagon,
        # so build an explicit triangle (cell 0) and pentagon (cell 1) side by side.
        self.vertices = np.asarray(
            [
                (0.0, 0.0),
                (10.0, 0.0),
                (0.0, 10.0),  # triangle 0-1-2
                (20.0, 0.0),
                (20.0, 10.0),
                (15.0, 15.0),  # pentagon 1-3-4-5-2
            ],
            dtype=float,
        )
        self.flat_connectivity = (
            np.asarray([0, 1, 2], dtype=int),
            np.asarray([1, 3, 4, 5, 2], dtype=int),
        )


def _grid_transform(xmin, ymin, xmax, ymax, ncols, nrows):
    return from_bounds(xmin, ymin, xmax, ymax, ncols, nrows)


def test_rasterize_cell_ids_assigns_each_pixel_to_one_cell():
    mesh = _QuadMesh(xmin=0.0, ymin=0.0, dx=50.0, dy=100.0, ncol=2, nrow=1)
    transform = _grid_transform(0.0, 0.0, 100.0, 100.0, 10, 10)
    labels = rasterize_cell_ids(mesh, transform=transform, out_shape=(10, 10))
    assert labels.shape == (10, 10)
    # Left half -> cell 0, right half -> cell 1, no pixel left as fill (-1).
    assert set(np.unique(labels).tolist()) == {0, 1}
    assert (labels[:, :5] == 0).all()
    assert (labels[:, 5:] == 1).all()


def test_rasterize_ragged_polygon_arities():
    mesh = _RaggedMesh()
    transform = _grid_transform(0.0, 0.0, 20.0, 15.0, 40, 30)
    labels = rasterize_cell_ids(mesh, transform=transform, out_shape=(30, 40))
    present = set(np.unique(labels).tolist())
    assert 0 in present and 1 in present  # both the triangle and the pentagon burn


def test_grouped_reduce_stats():
    labels = np.array([[0, 0, 1], [0, -1, 1]])
    values = np.array([[1.0, 3.0, 10.0], [5.0, np.nan, 20.0]])
    assert grouped_reduce(labels, values, n_cells=2, stat="min").tolist() == [1.0, 10.0]
    assert grouped_reduce(labels, values, n_cells=2, stat="max").tolist() == [5.0, 20.0]
    assert grouped_reduce(labels, values, n_cells=2, stat="mean").tolist() == [3.0, 15.0]
    med = grouped_reduce(labels, values, n_cells=2, stat="median")
    assert med[0] == pytest.approx(3.0) and med[1] == pytest.approx(15.0)


def test_grouped_reduce_rejects_unknown_stat():
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


def test_zonal_channel_min_lowers_channel_cell():
    mesh = _QuadMesh(xmin=0.0, ymin=0.0, dx=50.0, dy=100.0, ncol=2, nrow=1)
    dem, channel = _notch_dem(n=40)
    transform = _grid_transform(0.0, 0.0, 100.0, 100.0, 40, 40)
    centroid = np.array([25.0, 75.0])  # generator samples (unaffected by the off-centre notch)
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


def test_zonal_min_pixels_fallback_to_centroid():
    mesh = _QuadMesh(xmin=0.0, ymin=0.0, dx=50.0, dy=100.0, ncol=2, nrow=1)
    dem, _ = _notch_dem(n=40)
    transform = _grid_transform(0.0, 0.0, 100.0, 100.0, 40, 40)
    centroid = np.array([25.0, 75.0])
    # min_pixels above the pixels a cell can hold -> every hillslope cell falls back.
    res = zonal_top(
        planar_mesh=mesh,
        dem=dem,
        transform=transform,
        out_shape=(40, 40),
        centroid_top=centroid,
        channel_mask=None,
        min_pixels=10_000,
        spike_guard_tol_m=0.0,
    )
    assert np.array_equal(res.top, centroid)
    assert res.used_zonal.tolist() == [False, False]


def test_zonal_spike_guard_reverts_hillslope():
    mesh = _QuadMesh(xmin=0.0, ymin=0.0, dx=50.0, dy=100.0, ncol=2, nrow=1)
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


def test_zonal_min_thickness_clamps_lowered_top():
    mesh = _QuadMesh(xmin=0.0, ymin=0.0, dx=50.0, dy=100.0, ncol=2, nrow=1)
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


def test_zonal_nodata_pixels_excluded():
    mesh = _QuadMesh(xmin=0.0, ymin=0.0, dx=100.0, dy=100.0, ncol=1, nrow=1)
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
