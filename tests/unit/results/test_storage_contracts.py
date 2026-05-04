from __future__ import annotations

import json
import uuid

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Polygon

from hydromodpy.results.catalog import SimulationCatalog


@pytest.fixture
def catalog(tmp_path):
    cat = SimulationCatalog(tmp_path / "workspace")
    yield cat
    cat.close()


def _sim_id() -> str:
    return str(uuid.uuid4())


def _seed_field(catalog: SimulationCatalog) -> str:
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


def test_list_simulations_rejects_unknown_filter_and_order(catalog):
    catalog.register_simulation(_sim_id(), project="p", solver="s")

    with pytest.raises(ValueError, match="Unknown simulation filter"):
        catalog.list_simulations(**{"project;DROP TABLE simulations": "p"})

    with pytest.raises(ValueError, match="order_by"):
        catalog.list_simulations(order_by="created_at;DROP TABLE simulations")


def test_list_simulations_accepts_whitelisted_order_tuple(catalog):
    sid = _sim_id()
    catalog.register_simulation(sid, project="p", solver="s")

    rows = catalog.list_simulations(order_by=("created_at", "DESC"))

    assert [str(value) for value in rows["sim_id"]] == [sid]


def test_register_simulation_rolls_back_name_collision_when_zarr_staging_fails(
    catalog,
    monkeypatch,
):
    import hydromodpy.results.catalog.registration as registration_module

    old = _sim_id()
    new = _sim_id()
    catalog.register_simulation(old, project="p", solver="s", name="baseline")

    def fail_create(*args, **kwargs):
        raise RuntimeError("staging failed")

    monkeypatch.setattr(registration_module.SimulationZarr, "create", fail_create)

    with pytest.raises(RuntimeError, match="staging failed"):
        catalog.register_simulation(
            new,
            project="p",
            solver="s",
            name="baseline",
            n_cells=1,
            n_layers=1,
        )

    rows = catalog.list_simulations(project="p")
    assert [str(value) for value in rows["sim_id"]] == [old]
    assert rows.iloc[0]["name"] == "baseline"


def test_run_array_batch_is_dask_backed(catalog):
    DaskArray = pytest.importorskip("dask.array").Array
    sid = _seed_field(catalog)

    ds = catalog[sid].array.to_xarray_batch(("head",))

    assert isinstance(ds["head"].data, DaskArray)
    assert ds["head"].shape == (2, 1, 2)


def test_run_fields_is_dask_backed(catalog):
    DaskArray = pytest.importorskip("dask.array").Array
    sid = _seed_field(catalog)

    stack = catalog[sid].fields("head")

    assert isinstance(stack.data, DaskArray)
    assert stack.data.shape == (2, 1, 2)
    np.testing.assert_allclose(stack.data.compute(), np.array([[[1.0, 2.0]], [[3.0, 4.0]]]))


def test_simulation_zarr_to_xarray_is_dask_backed(catalog):
    DaskArray = pytest.importorskip("dask.array").Array
    sid = _seed_field(catalog)
    sz = catalog.open_zarr(sid)
    try:
        ds = sz.to_xarray()
        assert isinstance(ds["head"].data, DaskArray)
    finally:
        sz.close()


def test_virtual_seepage_mask_prefers_surface_excess_budget(catalog):
    sid = _sim_id()
    reg = catalog.register_simulation(
        sid,
        project="p",
        solver="boussinesq",
        n_cells=2,
        n_layers=1,
        n_timesteps=1,
    )
    assert reg.zarr is not None
    reg.zarr.close()
    catalog.write_mesh(
        sid,
        vertices=np.array([[0.0, 0.0, 10.0], [1.0, 0.0, 10.0], [0.0, 1.0, 10.0]]),
        face_node_connectivity=np.array([[0, 1, 2], [0, 2, 1]], dtype="int32"),
        z_interfaces=np.array([10.0, 0.0], dtype=float),
    )
    catalog.write_field(sid, "head", 0, np.array([[11.0, 11.0]]), n_timesteps=1)
    catalog.write_field(
        sid,
        "surface_excess",
        0,
        np.array([0.0, 1.0e-5]),
        n_timesteps=1,
        subgroup="budget",
    )

    mask = catalog.query_field(sid, "seepage_mask", 0)

    np.testing.assert_array_equal(mask, np.array([0.0, 1.0]))


def test_register_observation_points_stores_simulation_crs(catalog):
    sid = _sim_id()
    reg = catalog.register_simulation(
        sid,
        project="p",
        solver="modflow6",
        n_cells=1,
        n_layers=1,
        crs="EPSG:2154",
    )
    assert reg.zarr is not None
    reg.zarr.close()
    catalog.write_mesh(
        sid,
        vertices=np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]),
        face_node_connectivity=np.array([[0, 1, 2]], dtype="int32"),
        z_interfaces=np.array([0.0, -1.0]),
    )

    catalog.register_observation_points(sid, {"S1": (0.2, 0.2)})

    row = catalog.connection.execute(
        "SELECT crs_wkt, crs_epsg FROM observation_points WHERE sim_id = ?",
        [sid],
    ).fetchone()
    assert row == ("EPSG:2154", 2154)


def test_geographic_feature_uses_parquet_geometry_payload(catalog):
    sid = _sim_id()
    catalog.register_simulation(sid, project="p", solver="modflow6")
    gdf = gpd.GeoDataFrame(
        {"name": ["domain"]},
        geometry=[Polygon([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 0.0)])],
        crs="EPSG:2154",
    )

    catalog.write_geographic_feature(sid, "domain", gdf)

    row = catalog.connection.execute(
        "SELECT geoparquet_path, properties FROM geographic_features WHERE sim_id = ?",
        [sid],
    ).fetchone()
    assert row is not None
    assert (catalog.workspace_path / row[0]).is_file()
    props = json.loads(row[1])
    assert props["geometry_encoding"] == "WKB"
    assert "geojson" not in props

    loaded = catalog.read_geographic_feature(sid, "domain")
    assert len(loaded) == 1
    assert str(loaded.crs) == "EPSG:2154"
