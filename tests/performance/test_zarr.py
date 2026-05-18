"""Zarr v3 cold-open and slice-read baseline benchmarks.

Self-contained fixtures: xarray dataset (10 timesteps, 100x100 grid)
serialized through ``xarray.to_zarr`` with consolidated metadata.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr

pytestmark = pytest.mark.performance


def _build_dataset(n_time: int, n_y: int, n_x: int) -> xr.Dataset:
    """Return a synthetic xarray Dataset with one variable ``data``."""
    rng = np.random.default_rng(seed=42)
    arr = rng.random((n_time, n_y, n_x), dtype=np.float64)
    return xr.Dataset(
        {"data": (("time", "y", "x"), arr)},
        coords={
            "time": np.arange(n_time, dtype=np.int64),
            "y": np.arange(n_y, dtype=np.int64),
            "x": np.arange(n_x, dtype=np.int64),
        },
    )


@pytest.fixture(scope="function")
def zarr_path(tmp_path: Path) -> Path:
    """Write a consolidated Zarr v3 store with a 10x100x100 array."""
    ds = _build_dataset(n_time=10, n_y=100, n_x=100)
    store_path = tmp_path / "test.zarr"
    ds.to_zarr(store_path, mode="w", consolidated=True, zarr_format=3)
    return store_path


@pytest.mark.benchmark(group="zarr")
def test_zarr_open_consolidated(benchmark, zarr_path: Path) -> None:
    """Cold open a consolidated Zarr v3 store via xarray."""

    def _open() -> None:
        ds = xr.open_zarr(zarr_path, consolidated=True)
        ds.close()

    benchmark(_open)


@pytest.mark.benchmark(group="zarr")
def test_zarr_read_slice(benchmark, zarr_path: Path) -> None:
    """Materialize one timestep slice of the full 100x100 grid."""
    ds = xr.open_zarr(zarr_path, consolidated=True)
    try:

        def _slice() -> np.ndarray:
            return ds["data"].isel(time=0).load().values

        benchmark(_slice)
    finally:
        ds.close()
