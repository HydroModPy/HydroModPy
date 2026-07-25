from __future__ import annotations

import json
import uuid

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Polygon

from hydromodpy.core.io.geoparquet import read_geoparquet, write_geoparquet_atomic
from hydromodpy.results.catalog import Catalog
from tests._helpers.fixtures_catalog import simulation_catalog


@pytest.fixture
def catalog(tmp_path):
    with simulation_catalog(tmp_path / "workspace") as cat:
        yield cat


def _sim_id() -> str:
    return str(uuid.uuid4())


def _seed_field(catalog: Catalog) -> str:
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
    catalog.register_simulation(_sim_id(), project="p", solver="modflow6")

    with pytest.raises(ValueError, match="Unknown simulation filter"):
        catalog.list_simulations(**{"project;DROP TABLE simulations": "p"})

    with pytest.raises(ValueError, match="order_by"):
        catalog.list_simulations(order_by="created_at;DROP TABLE simulations")


def test_list_simulations_accepts_whitelisted_order_tuple(catalog):
    sid = _sim_id()
    catalog.register_simulation(sid, project="p", solver="modflow6")

    rows = catalog.list_simulations(order_by=("created_at", "DESC"))

    assert [str(value) for value in rows["sim_id"]] == [sid]


def test_register_simulation_rolls_back_name_collision_when_zarr_staging_fails(
    catalog,
    monkeypatch,
):
    import hydromodpy.results.catalog.registration as registration_module

    old = _sim_id()
    new = _sim_id()
    catalog.register_simulation(old, project="p", solver="modflow6", name="baseline")

    def fail_create(*args, **kwargs):
        raise RuntimeError("staging failed")

    monkeypatch.setattr(registration_module.SimulationZarr, "create", fail_create)

    with pytest.raises(RuntimeError, match="staging failed"):
        catalog.register_simulation(
            new,
            project="p",
            solver="modflow6",
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


def test_run_array_to_xarray_batch_is_dask_backed(catalog):
    DaskArray = pytest.importorskip("dask.array").Array
    sid = _seed_field(catalog)

    ds = catalog[sid].array.to_xarray_batch(("head",))

    assert isinstance(ds["head"].data, DaskArray)
    assert ds["head"].shape == (2, 1, 2)
    np.testing.assert_allclose(
        ds["head"].compute().values,
        np.array([[[1.0, 2.0]], [[3.0, 4.0]]]),
    )


def test_simulation_zarr_to_xarray_is_dask_backed(catalog):
    DaskArray = pytest.importorskip("dask.array").Array
    sid = _seed_field(catalog)
    sz = catalog.open_zarr(sid)
    try:
        ds = sz.to_xarray()
        assert isinstance(ds["head"].data, DaskArray)
    finally:
        sz.close()


def test_has_field_implies_field_reads_back(catalog):
    """A field ``has_field`` reports as available must read back as an array.

    The head-derived virtual fields are not persisted by default, so ``field()``
    has to take the same virtual fallback the availability gate assumes.
    """
    from hydromodpy.results.derive.virtual_fields import HEAD_DERIVED_VIRTUAL_FIELDS

    sid = _seed_field(catalog)
    sz = catalog.open_zarr(sid)
    try:
        sz.write_topography(np.array([10.0, 11.0]), n_cells=2, n_layers=1)
    finally:
        sz.close()
    run = catalog[sid]

    for variable in sorted(HEAD_DERIVED_VIRTUAL_FIELDS):
        assert run.has_field(variable), variable
        values = run.field(variable, timestep=-1)
        assert np.asarray(values).shape == (2,), variable


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
    # GeoParquet 1.1 OGC stores the CRS as PROJJSON inside the file metadata.
    # Use pyproj to round-trip back to EPSG so the test stays format-agnostic.
    assert loaded.crs.to_epsg() == 2154


def test_geoparquet_atomic_writer_handles_long_windows_paths(tmp_path):
    long_dir = tmp_path
    for idx in range(6):
        long_dir = long_dir / f"nested_{idx}_{'x' * 40}"
    target = long_dir / "feature.parquet"
    assert len(str(target)) > 260
    gdf = gpd.GeoDataFrame(
        {"name": ["domain"]},
        geometry=[Polygon([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 0.0)])],
        crs="EPSG:2154",
    )

    write_geoparquet_atomic(gdf, target)

    loaded = read_geoparquet(target)
    assert len(loaded) == 1
    assert loaded.crs.to_epsg() == 2154


def test_catchment_view_reads_an_unpersisted_derived_field(catalog):
    """A lazy view must take the same virtual fallback as ``Run.field``.

    ``seepage_mask`` is not persisted by default. A view reading the Zarr
    store directly would raise ``FieldNotFoundError`` on every default run,
    while the field is derivable from the stored head.
    """
    from hydromodpy.results.derive.views import saturated_fraction

    sid = _sim_id()
    reg = catalog.register_simulation(
        sid,
        project="p",
        solver="modflow6",
        n_cells=2,
        n_layers=1,
        n_timesteps=2,
        period_start="2020-01-01",
        period_end="2020-01-02",
    )
    assert reg.zarr is not None
    reg.zarr.close()
    catalog.write_field(sid, "head", 0, np.array([[9.0, 12.0]]), n_timesteps=2)
    catalog.write_field(sid, "head", 1, np.array([[11.0, 12.0]]), n_timesteps=2)
    sz = catalog.open_zarr(sid)
    try:
        sz.write_topography(np.array([10.0, 11.0]), n_cells=2, n_layers=1)
    finally:
        sz.close()
    run = catalog[sid]
    assert not run.has_field("seepage_mask", subgroup="derived")

    series = saturated_fraction(run)

    # t0: only the second cell outcrops (12 >= 11) -> 50 %; t1: both -> 100 %.
    np.testing.assert_allclose(series.to_numpy(), [50.0, 100.0])


def _seed_head_and_topography(catalog: Catalog) -> str:
    """Register a two-cell, two-timestep run with a head and a surface."""
    sid = _seed_field(catalog)
    sz = catalog.open_zarr(sid)
    try:
        sz.write_topography(np.array([10.0, 11.0]), n_cells=2, n_layers=1)
    finally:
        sz.close()
    return sid


def test_read_returns_data_for_every_available_field(catalog):
    """``has_field`` and ``hmp.read`` must agree, with or without ``time``.

    The virtual fields are not persisted, so the batch reader has to rebuild
    them: reporting a field as available and then raising on the documented
    default read (``time=None``) is a broken contract.
    """
    import hydromodpy as hmp
    from hydromodpy.results import field_registry

    sid = _seed_head_and_topography(catalog)
    run = catalog[sid]

    available = [name for name in field_registry.all_names() if run.has_field(name)]
    assert {"watertable_elevation", "watertable_depth", "seepage_mask"} <= set(available)
    for name in available:
        assert np.asarray(hmp.read(run, name)).size > 0, name
        assert np.asarray(hmp.read(run, name, time=0)).size > 0, name
        assert np.asarray(hmp.read(run, name, time=slice(0, 2))).size > 0, name


def test_list_fields_matches_has_field(catalog):
    from hydromodpy.results import field_registry

    sid = _seed_head_and_topography(catalog)
    run = catalog[sid]

    listed = run.array.list_fields()
    available = [name for name in field_registry.all_names() if run.has_field(name)]
    assert listed == sorted(available)


def test_exportable_fields_include_the_virtual_ones(catalog):
    """A default run exports its water table, not just the raw head."""
    from hydromodpy.cli.commands.data.export import _exportable_fields

    sid = _seed_head_and_topography(catalog)

    fields = _exportable_fields(catalog, sid)

    assert "head" in fields
    assert {"watertable_elevation", "watertable_depth", "seepage_mask"} <= set(fields)


def test_view_names_the_flag_when_a_derived_field_was_never_computed(catalog):
    """A view on a missing derived field must say which flag to switch on."""
    from hydromodpy.results.derive.views import drainage_density
    from hydromodpy.results.errors import FieldNotFoundError

    sid = _seed_head_and_topography(catalog)
    run = catalog[sid]

    with pytest.raises(FieldNotFoundError, match="results.derived. accumulation_flux = true"):
        drainage_density(run)


def test_drop_group_removes_the_arrays_and_reports_the_freed_bytes(catalog):
    """The store must be able to shed an intermediate group before it is sealed."""
    sid = _seed_field(catalog)
    catalog.write_field(sid, "drain", 0, np.array([-1.0, -2.0]), n_timesteps=2, subgroup="budget")
    catalog.write_field(sid, "drain", 1, np.array([-3.0, -4.0]), n_timesteps=2, subgroup="budget")

    sz = catalog.open_zarr(sid)
    try:
        assert "budget" in sz.root
        freed = sz.drop_group("budget")
        assert freed > 0
        assert "budget" not in sz.root
        assert not (sz.path / "budget").exists()
        assert sz.drop_group("budget") == 0
    finally:
        sz.close()
