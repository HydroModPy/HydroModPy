"""Tests for the :func:`hmp.read` top-level dispatch facade.

The facade routes a variable name to the right backend based on the
canonical :mod:`hydromodpy.results.field_registry`, the DuckDB
``timeseries`` table and the GeoParquet ``geographic_features`` table.
"""

from __future__ import annotations

import uuid

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon

import hydromodpy as hmp
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.errors import FieldNotFoundError
from hydromodpy.results.run import Run
from tests._helpers.fixtures_catalog import simulation_catalog


def _sim_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def catalog(tmp_path):
    with simulation_catalog(tmp_path / "workspace") as cat:
        yield cat


def _seed_field(catalog: Catalog) -> str:
    """Seed a minimal MF6 simulation with a 1x2 ``head`` field."""
    sid = _sim_id()
    reg = catalog.register_simulation(
        sid,
        project="p",
        solver="modflow6",
        n_cells=2,
        n_layers=1,
        n_timesteps=2,
    )
    assert reg.zarr is not None
    reg.zarr.close()
    catalog.write_field(sid, "head", 0, np.array([[1.0, 2.0]]), n_timesteps=2)
    catalog.write_field(sid, "head", 1, np.array([[3.0, 4.0]]), n_timesteps=2)
    catalog.write_geographic_metadata(
        sid,
        {
            "dem_res": 1.0,
            "nrow": 1,
            "ncol": 2,
            "crs_proj": "EPSG:2154",
            "catch_area": 0.000002,
        },
    )
    catalog.write_geographic_raster(
        sid,
        "watershed_dem",
        np.array([[10.0, 11.0]], dtype=float),
        transform=(1.0, 0.0, 0.0, 0.0, -1.0, 1.0),
        crs="EPSG:2154",
    )
    return sid


def _seed_timeseries(catalog: Catalog, sid: str) -> None:
    series = pd.Series(
        [1.5, 2.0, 2.5],
        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
        name="discharge",
    )
    catalog.write_timeseries(sid, "outlet", "discharge", series)


def _seed_geographic_feature(catalog: Catalog, sid: str) -> None:
    poly = Polygon([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
    gdf = gpd.GeoDataFrame(
        {"name": ["basin"], "geometry": [poly]},
        crs="EPSG:2154",
    )
    catalog.write_geographic_feature(sid, "watershed_polygon", gdf)


def test_read_zarr_field_returns_xarray_dataarray(catalog):
    """``hmp.read(run, "head")`` returns a lazy ``xr.DataArray``."""
    import xarray as xr

    sid = _seed_field(catalog)
    run = Run(sid, catalog)
    da = hmp.read(run, "head")
    assert isinstance(da, xr.DataArray)
    assert da.dims == ("time", "layer", "cell")
    assert da.shape == (2, 1, 2)


def test_read_zarr_field_eager_with_time_int_returns_ndarray(catalog):
    """When ``time`` is an int, dispatch returns the eager numpy slice."""
    sid = _seed_field(catalog)
    run = Run(sid, catalog)
    arr = hmp.read(run, "head", time=0, layer=0)
    assert isinstance(arr, np.ndarray)
    np.testing.assert_array_equal(arr.ravel(), [1.0, 2.0])


def test_read_zarr_field_with_layer_selects_layer(catalog):
    """Lazy ``DataArray`` returned by ``read`` can be sliced along layer."""
    sid = _seed_field(catalog)
    run = Run(sid, catalog)
    da = hmp.read(run, "head", layer=0)
    assert da.dims == ("time", "cell")
    assert da.shape == (2, 2)


def test_read_zarr_field_with_time_slice(catalog):
    """Slice the time dimension on the lazy ``DataArray``."""
    sid = _seed_field(catalog)
    run = Run(sid, catalog)
    da = hmp.read(run, "head", time=slice(0, 1))
    assert da.shape == (1, 1, 2)


def test_read_timeseries_returns_pandas_series(catalog):
    """A persisted timeseries variable dispatches to ``pd.Series``."""
    sid = _seed_field(catalog)
    _seed_timeseries(catalog, sid)
    run = Run(sid, catalog)
    ts = hmp.read(run, "discharge", sel={"station": "outlet"})
    assert isinstance(ts, pd.Series)
    np.testing.assert_allclose(ts.values, [1.5, 2.0, 2.5])


def test_read_timeseries_single_station_infers_station(catalog):
    """When a variable has a single station, ``station`` may be omitted."""
    sid = _seed_field(catalog)
    _seed_timeseries(catalog, sid)
    run = Run(sid, catalog)
    ts = hmp.read(run, "discharge")
    assert isinstance(ts, pd.Series)
    assert len(ts) == 3


def test_read_geographic_feature_returns_geodataframe(catalog):
    """A persisted geographic feature dispatches to ``gpd.GeoDataFrame``."""
    sid = _seed_field(catalog)
    _seed_geographic_feature(catalog, sid)
    run = Run(sid, catalog)
    gdf = hmp.read(run, "watershed_polygon")
    assert isinstance(gdf, gpd.GeoDataFrame)
    assert len(gdf) == 1


def test_read_unknown_variable_raises_field_not_found(catalog):
    """An unknown variable raises :class:`FieldNotFoundError`."""
    sid = _seed_field(catalog)
    run = Run(sid, catalog)
    with pytest.raises(FieldNotFoundError):
        hmp.read(run, "no_such_variable")


def test_read_unknown_variable_is_keyerror_compatible(catalog):
    """``FieldNotFoundError`` inherits from ``KeyError`` for compat."""
    sid = _seed_field(catalog)
    run = Run(sid, catalog)
    with pytest.raises(KeyError):
        hmp.read(run, "no_such_variable")


def test_read_requires_run_argument(catalog):
    """Passing a non-Run object raises ``TypeError``."""
    with pytest.raises(TypeError, match="Run"):
        hmp.read("not-a-run", "head")


def test_read_bbox_restricts_cells(catalog):
    """``bbox=`` restricts the returned DataArray to faces within the box."""
    sid = _seed_field(catalog)
    run = Run(sid, catalog)
    # With ncol=2 cells centred at x=0.5 and x=1.5, only cell 0 has centre <= 0.9
    da = hmp.read(run, "head", bbox=(0.0, -1.0, 1.0, 1.0))
    assert da.sizes["cell"] == 1


def test_read_attribute_exposed_on_module_top_level():
    """``hmp.read`` must be exported at the top-level facade."""
    assert callable(hmp.read)
    assert "read" in hmp.__all__


def test_facade_read_dispatch_rule(catalog):
    """One rule: ``time`` int -> ndarray, otherwise lazy DataArray."""
    import xarray as xr

    sid = _seed_field(catalog)
    run = Run(sid, catalog)

    arr = hmp.read(run, "head", time=0, layer=0)
    assert isinstance(arr, np.ndarray)

    da = hmp.read(run, "head")
    assert isinstance(da, xr.DataArray)
