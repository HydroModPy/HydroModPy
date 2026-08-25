"""Unit tests for the scalable rasterization helpers.

Covers ``hydromodpy.display.scalable``:
- threshold detection (``should_rasterize``)
- datashader availability probe
- 2D xr.DataArray rasterization to a target pixel resolution
- point cloud rasterization (centroids of an unstructured mesh)
- early-return when the mesh is below threshold
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.display import scalable


def test_should_rasterize_threshold_returns_true_above_default() -> None:
    assert scalable.should_rasterize(200_000) is True


def test_should_rasterize_threshold_returns_false_below_default() -> None:
    assert scalable.should_rasterize(50_000) is False


def test_should_rasterize_custom_threshold() -> None:
    assert scalable.should_rasterize(1000, threshold=500) is True
    assert scalable.should_rasterize(100, threshold=500) is False


def test_rasterize_field_mesh_1M_cells_to_1200x800() -> None:
    pytest.importorskip("datashader")
    pytest.importorskip("xarray")
    import xarray as xr

    # Synthesize a 1000 x 1000 = 1M-cell regular grid.
    side = 1000
    rng = np.random.default_rng(seed=42)
    data = rng.random((side, side)).astype("float32")
    da = xr.DataArray(
        data,
        coords={"y": np.linspace(0.0, 100.0, side), "x": np.linspace(0.0, 100.0, side)},
        dims=("y", "x"),
        name="head",
    )
    out = scalable.rasterize_field(da, target_px=(1200, 800))
    assert tuple(out.shape) == (800, 1200)
    assert np.isfinite(out.values).any()


def test_rasterize_field_below_threshold_no_downsample() -> None:
    """A field below the threshold needs no rasterization at the API level."""
    # The helper does not auto-skip; we verify the threshold logic instead.
    n_cells = 10_000  # Below the default 100k threshold.
    assert scalable.should_rasterize(n_cells) is False


def test_rasterize_points_unstructured_centroids() -> None:
    pytest.importorskip("datashader")
    rng = np.random.default_rng(seed=7)
    n = 200_000
    x = rng.uniform(0.0, 1000.0, size=n)
    y = rng.uniform(0.0, 800.0, size=n)
    values = rng.normal(loc=50.0, scale=2.5, size=n)
    raster = scalable.rasterize_points(x, y, values, target_px=(400, 320))
    assert raster.shape == (320, 400)
    finite_mask = np.isfinite(raster)
    assert finite_mask.any()


def test_rasterize_field_rejects_zero_dimensions() -> None:
    import xarray as xr

    da = xr.DataArray(
        np.zeros((4, 4)),
        coords={"y": np.arange(4), "x": np.arange(4)},
        dims=("y", "x"),
    )
    with pytest.raises(ValueError):
        scalable.rasterize_field(da, target_px=(0, 100))


def test_rasterize_field_rejects_unknown_agg() -> None:
    import xarray as xr

    da = xr.DataArray(
        np.zeros((4, 4)),
        coords={"y": np.arange(4), "x": np.arange(4)},
        dims=("y", "x"),
    )
    with pytest.raises(ValueError):
        scalable.rasterize_field(da, target_px=(8, 8), agg="median")


def test_is_datashader_available_consistent_with_import() -> None:
    """The probe should mirror whether the optional extra is installed."""
    available = scalable.is_datashader_available()
    try:
        import datashader  # noqa: F401

        installed = True
    except ImportError:
        installed = False
    assert available is installed
