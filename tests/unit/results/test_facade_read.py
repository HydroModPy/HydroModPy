"""Tests for :meth:`Run.read`, the dispatch of a variable name to its reader.

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
import xarray as xr
from shapely.geometry import Polygon

import hydromodpy as hmp
from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.errors import FieldNotFoundError
from hydromodpy.results.run.view import Run
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


def test_one_period_is_a_data_array(run):
    # ``time`` selects in a field and never changes the type.
    for time in (0, -2, np.int64(0)):
        da = run.read("head", time=time, layer=0)
        assert isinstance(da, xr.DataArray)
        assert da.dims == ("cell",)
        np.testing.assert_array_equal(da.values, run.field("head", time=0, layer=0).ravel())
    with pytest.raises(IndexError, match="no such period"):
        run.read("head", time=5)


READS = [
    pytest.param({"layer": 0}, ("time", "cell"), (2, 2), id="one layer"),
    pytest.param({"time": slice(0, 1)}, None, (1, 1, 2), id="time slice"),
]


@pytest.mark.parametrize(("kwargs", "dims", "shape"), READS)
def test_read_field_slices(run, kwargs, dims, shape):
    da = run.read("head", **kwargs)

    assert da.shape == shape
    if dims:
        assert da.dims == dims


def test_read_timeseries(run_with_series):
    run = run_with_series
    ts = run.read("discharge", sel={"station": "outlet"})
    assert isinstance(ts, pd.Series)
    np.testing.assert_allclose(ts.values, [1.5, 2.0, 2.5])


def test_read_without_a_station(tmp_path):
    """A run writes a gauge series beside the catchment one, and a plain read keeps its answer."""
    index = pd.date_range("2020-01-02", periods=2, freq="D")
    with open_run_store(tmp_path / "demo", "two", n_cells=4, n_timesteps=2) as store:
        store.write_timeseries(store.sim_id, "catchment", "discharge", pd.Series([1.0, 2.0], index))
        store.write_timeseries(store.sim_id, "J001", "discharge", pd.Series([0.1, 0.2], index))
        run = Run(store.sim_id, store)

        assert run.read("discharge").tolist() == [1.0, 2.0]
        assert run.read("discharge", sel={"station": "J001"}).tolist() == [0.1, 0.2]


def test_read_geographic_feature(tmp_path):
    with _sealed(tmp_path / "workspace", feature=True) as run:
        gdf = run.read("watershed_polygon")
    assert isinstance(gdf, gpd.GeoDataFrame)
    assert len(gdf) == 1


def test_unknown_variable(run):
    with pytest.raises(FieldNotFoundError) as raised:
        run.read("no_such_variable")
    assert isinstance(raised.value, KeyError)


def test_read_needs_a_run():
    from hydromodpy.results.derive.reading import read_variable

    with pytest.raises(TypeError, match="Run"):
        read_variable("not-a-run", "head")


def test_read_bbox(run):
    # The cells of the stored mesh are centered at x=0.5 and x=1.5: only cell 0 is in the box.
    da = run.read("head", bbox=(0.0, -1.0, 1.0, 1.0))
    assert da.sizes["cell"] == 1


def test_read_top_level(run):
    """``Run.read`` reads; ``hmp.read`` stays for the frozen runs and reads through it."""
    assert callable(Run.read)
    assert "read" in hmp.__all__
    assert hmp.read(run, "head", time=0).equals(run.read("head", time=0))
    with pytest.raises(TypeError):
        hmp.read("not a run", "head")
