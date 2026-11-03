"""Tests for the :func:`hmp.read` top-level dispatch facade.

The facade routes a variable name to the right backend based on the
canonical :mod:`hydromodpy.results.field_registry`, the ``timeseries``
table and the GeoParquet ``geographic_features`` table of a sealed run.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon

import hydromodpy as hmp
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.errors import FieldNotFoundError
from hydromodpy.results.run import Run
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_stores import open_run_store


def _write_field(store: RunStore) -> None:
    """Write a minimal MF6 run with a 1x2 ``head`` field."""
    sid = store.sim_id
    # Two unit squares side by side: cell centers at x = 0.5 and x = 1.5.
    store.write_mesh(
        sid,
        np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0], [0, 1, 0], [1, 1, 0], [2, 1, 0]], float),
        np.array([[0, 1, 4, 3], [1, 2, 5, 4]], dtype=np.int32),
        np.array([10.0, 0.0]),
    )
    store.write_field(sid, "head", 0, np.array([[1.0, 2.0]]), n_timesteps=2)
    store.write_field(sid, "head", 1, np.array([[3.0, 4.0]]), n_timesteps=2)
    store.write_geographic_metadata(
        sid,
        {
            "dem_res": 1.0,
            "nrow": 1,
            "ncol": 2,
            "crs_proj": "EPSG:2154",
            "catch_area": 0.000002,
        },
    )
    store.write_geographic_raster(
        sid,
        "watershed_dem",
        np.array([[10.0, 11.0]], dtype=float),
        transform=(1.0, 0.0, 0.0, 0.0, -1.0, 1.0),
        crs="EPSG:2154",
    )


def _write_timeseries(store: RunStore) -> None:
    series = pd.Series(
        [1.5, 2.0, 2.5],
        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
        name="discharge",
    )
    store.write_timeseries(store.sim_id, "outlet", "discharge", series)


def _write_geographic_feature(store: RunStore) -> None:
    poly = Polygon([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
    gdf = gpd.GeoDataFrame(
        {"name": ["basin"], "geometry": [poly]},
        crs="EPSG:2154",
    )
    store.write_geographic_feature(store.sim_id, "watershed_polygon", gdf)


@contextmanager
def _sealed(project: Path, *, timeseries: bool = False, feature: bool = False) -> Iterator[Run]:
    """Seal the run, with a series or a feature when asked, index it and yield it."""
    store = open_run_store(project, "run", n_cells=2, n_layers=1, n_timesteps=2)
    _write_field(store)
    if timeseries:
        _write_timeseries(store)
    if feature:
        _write_geographic_feature(store)
    sid = store.sim_id
    seal_completed(store)
    rebuild_index(project)
    with Catalog(project) as catalog:
        yield Run(sid, catalog)


@pytest.fixture
def run(tmp_path: Path) -> Iterator[Run]:
    with _sealed(tmp_path / "workspace") as sealed:
        yield sealed


@pytest.fixture
def run_with_series(tmp_path: Path) -> Iterator[Run]:
    with _sealed(tmp_path / "workspace", timeseries=True) as sealed:
        yield sealed


def test_read_zarr_field_returns_xarray_dataarray(run):
    """``hmp.read(run, "head")`` returns a lazy ``xr.DataArray``."""
    import xarray as xr

    da = hmp.read(run, "head")
    assert isinstance(da, xr.DataArray)
    assert da.dims == ("time", "layer", "cell")
    assert da.shape == (2, 1, 2)


def test_one_period_is_a_data_array_without_the_time_dimension(run):
    """``time`` selects in a field and never changes the type."""
    import xarray as xr

    for time in (0, -2, np.int64(0)):
        da = hmp.read(run, "head", time=time, layer=0)
        assert isinstance(da, xr.DataArray)
        assert da.dims == ("cell",)
        np.testing.assert_array_equal(da.values, run.field("head", time=0, layer=0).ravel())
    with pytest.raises(IndexError, match="no such period"):
        hmp.read(run, "head", time=5)


def test_read_zarr_field_with_layer_selects_layer(run):
    """Lazy ``DataArray`` returned by ``read`` can be sliced along layer."""
    da = hmp.read(run, "head", layer=0)
    assert da.dims == ("time", "cell")
    assert da.shape == (2, 2)


def test_read_zarr_field_with_time_slice(run):
    """Slice the time dimension on the lazy ``DataArray``."""
    da = hmp.read(run, "head", time=slice(0, 1))
    assert da.shape == (1, 1, 2)


def test_read_timeseries_returns_pandas_series(run_with_series):
    """A persisted timeseries variable dispatches to ``pd.Series``."""
    run = run_with_series
    ts = hmp.read(run, "discharge", sel={"station": "outlet"})
    assert isinstance(ts, pd.Series)
    np.testing.assert_allclose(ts.values, [1.5, 2.0, 2.5])


def test_read_timeseries_single_station_infers_station(run_with_series):
    """When a variable has a single station, ``station`` may be omitted."""
    run = run_with_series
    ts = hmp.read(run, "discharge")
    assert isinstance(ts, pd.Series)
    assert len(ts) == 3


def test_read_geographic_feature_returns_geodataframe(tmp_path):
    """A persisted geographic feature dispatches to ``gpd.GeoDataFrame``."""
    with _sealed(tmp_path / "workspace", feature=True) as run:
        gdf = hmp.read(run, "watershed_polygon")
    assert isinstance(gdf, gpd.GeoDataFrame)
    assert len(gdf) == 1


def test_read_unknown_variable_raises_field_not_found(run):
    """An unknown variable raises :class:`FieldNotFoundError`."""
    with pytest.raises(FieldNotFoundError):
        hmp.read(run, "no_such_variable")


def test_read_unknown_variable_is_keyerror_compatible(run):
    """``FieldNotFoundError`` inherits from ``KeyError`` for compat."""
    with pytest.raises(KeyError):
        hmp.read(run, "no_such_variable")


def test_read_requires_run_argument():
    """Passing a non-Run object raises ``TypeError``."""
    with pytest.raises(TypeError, match="Run"):
        hmp.read("not-a-run", "head")


def test_read_bbox_restricts_cells(run):
    """``bbox=`` restricts the returned DataArray to faces within the box."""
    # The cells of the stored mesh are centered at x=0.5 and x=1.5: only cell 0 is in the box.
    da = hmp.read(run, "head", bbox=(0.0, -1.0, 1.0, 1.0))
    assert da.sizes["cell"] == 1


def test_read_attribute_exposed_on_module_top_level():
    """``hmp.read`` must be exported at the top-level facade."""
    assert callable(hmp.read)
    assert "read" in hmp.__all__


def test_facade_read_dispatch_rule(run):
    """One type per nature of variable, with ``time`` or without."""
    import xarray as xr

    for kwargs in ({}, {"time": 0}, {"time": slice(0, 1)}, {"time": 0, "layer": 0}):
        assert isinstance(hmp.read(run, "head", **kwargs), xr.DataArray)
