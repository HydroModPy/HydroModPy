from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Polygon

from hydromodpy.core.io.geoparquet import read_geoparquet, write_geoparquet_atomic
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_stores import open_run_store
from tests._helpers.sealed_runs import seal_run


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return tmp_path / "workspace"


def _write_field(store: RunStore) -> None:
    """Write two periods of head and the DEM grid of a two-cell run."""
    sid = store.sim_id
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


def _write_topography(store: RunStore) -> None:
    sz = store.open_zarr(store.sim_id)
    try:
        sz.write_topography(np.array([10.0, 11.0]), n_cells=2, n_layers=1)
    finally:
        sz.close()


@contextmanager
def _sealed(
    project: Path, *writers: Callable[[RunStore], None], **facts: object
) -> Iterator[tuple[Catalog, str]]:
    """Seal a two-cell, two-period run written by *writers*; yield the catalog and its id."""
    facts.setdefault("n_timesteps", 2)
    store = open_run_store(project, "run", n_cells=2, n_layers=1, **facts)
    sid = store.sim_id
    for write in writers:
        write(store)
    seal_completed(store)
    rebuild_index(project)
    with Catalog(project) as catalog:
        yield catalog, sid


@pytest.fixture
def field_run(project: Path) -> Iterator[tuple[Catalog, str]]:
    """A run with two periods of head, indexed."""
    with _sealed(project, _write_field) as pair:
        yield pair


@pytest.fixture
def surface_run(project: Path) -> Iterator[tuple[Catalog, str]]:
    """A run with two periods of head and a surface, indexed."""
    with _sealed(project, _write_field, _write_topography) as pair:
        yield pair


def test_list_simulations_rejects_unknown_filter_and_order(project):
    seal_run(project, "run", project="p")
    rebuild_index(project)

    with Catalog(project) as catalog:
        with pytest.raises(ValueError, match="Unknown simulation filter"):
            catalog.list_simulations(**{"project;DROP TABLE simulations": "p"})

        with pytest.raises(ValueError, match="order_by"):
            catalog.list_simulations(order_by="created_at;DROP TABLE simulations")


def test_list_simulations_accepts_whitelisted_order_tuple(project):
    sid = seal_run(project, "run", project="p")
    rebuild_index(project)

    with Catalog(project) as catalog:
        rows = catalog.list_simulations(order_by=("created_at", "DESC"))

    assert [str(value) for value in rows["sim_id"]] == [sid]


def test_run_array_batch_is_dask_backed(field_run):
    DaskArray = pytest.importorskip("dask.array").Array
    catalog, sid = field_run

    ds = catalog[sid].array.to_xarray_batch(("head",))

    assert isinstance(ds["head"].data, DaskArray)
    assert ds["head"].shape == (2, 1, 2)


def test_run_array_to_xarray_batch_is_dask_backed(field_run):
    DaskArray = pytest.importorskip("dask.array").Array
    catalog, sid = field_run

    ds = catalog[sid].array.to_xarray_batch(("head",))

    assert isinstance(ds["head"].data, DaskArray)
    assert ds["head"].shape == (2, 1, 2)
    np.testing.assert_allclose(
        ds["head"].compute().values,
        np.array([[[1.0, 2.0]], [[3.0, 4.0]]]),
    )


def test_simulation_zarr_to_xarray_is_dask_backed(field_run):
    DaskArray = pytest.importorskip("dask.array").Array
    catalog, sid = field_run
    sz = catalog.open_zarr(sid)
    try:
        ds = sz.to_xarray()
        assert isinstance(ds["head"].data, DaskArray)
    finally:
        sz.close()


def test_has_field_implies_field_reads_back(surface_run):
    """A field ``has_field`` reports as available must read back as an array.

    The head-derived virtual fields are not persisted by default, so ``field()``
    has to take the same virtual fallback the availability gate assumes.
    """
    from hydromodpy.results.derive.virtual_fields import HEAD_DERIVED_VIRTUAL_FIELDS

    catalog, sid = surface_run
    run = catalog[sid]

    for variable in sorted(HEAD_DERIVED_VIRTUAL_FIELDS):
        assert run.has_field(variable), variable
        values = run.field(variable, time=-1)
        assert np.asarray(values).shape == (2,), variable


def _write_seeping_boussinesq(store: RunStore) -> None:
    sid = store.sim_id
    store.write_mesh(
        sid,
        vertices=np.array([[0.0, 0.0, 10.0], [1.0, 0.0, 10.0], [0.0, 1.0, 10.0]]),
        face_node_connectivity=np.array([[0, 1, 2], [0, 2, 1]], dtype="int32"),
        z_interfaces=np.array([10.0, 0.0], dtype=float),
    )
    store.write_field(sid, "head", 0, np.array([[11.0, 11.0]]), n_timesteps=1)
    store.write_field(
        sid,
        "surface_excess",
        0,
        np.array([0.0, -1.0e-5]),
        n_timesteps=1,
        subgroup="budget",
    )


def test_virtual_seepage_mask_prefers_surface_excess_budget(project):
    with _sealed(project, _write_seeping_boussinesq, solver="boussinesq", n_timesteps=1) as (
        catalog,
        sid,
    ):
        mask = catalog.query_field(sid, "seepage_mask", 0)

    np.testing.assert_array_equal(mask, np.array([0.0, 1.0]))


def _write_domain(store: RunStore) -> None:
    gdf = gpd.GeoDataFrame(
        {"name": ["domain"]},
        geometry=[Polygon([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 0.0)])],
        crs="EPSG:2154",
    )
    store.write_geographic_feature(store.sim_id, "domain", gdf)


def test_geographic_feature_uses_parquet_geometry_payload(project):
    with _sealed(project, _write_domain) as (catalog, sid):
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


def _write_outcropping_head(store: RunStore) -> None:
    sid = store.sim_id
    store.write_field(sid, "head", 0, np.array([[9.0, 12.0]]), n_timesteps=2)
    store.write_field(sid, "head", 1, np.array([[11.0, 12.0]]), n_timesteps=2)


def test_catchment_view_reads_an_unpersisted_derived_field(project):
    """A lazy view must take the same virtual fallback as ``Run.field``.

    ``seepage_mask`` is not persisted by default. A view reading the Zarr
    store directly would raise ``FieldNotFoundError`` on every default run,
    while the field is derivable from the stored head.
    """
    from datetime import UTC, datetime

    from hydromodpy.results.derive.views import saturated_fraction

    with _sealed(
        project,
        _write_outcropping_head,
        _write_topography,
        period_start=datetime(2020, 1, 1, tzinfo=UTC),
        period_end=datetime(2020, 1, 2, tzinfo=UTC),
    ) as (catalog, sid):
        run = catalog[sid]
        assert not run.has_field("seepage_mask", subgroup="derived")

        series = saturated_fraction(run)

    # t0: only the second cell outcrops (12 >= 11) -> 50 %; t1: both -> 100 %.
    np.testing.assert_allclose(series.to_numpy(), [50.0, 100.0])


def test_read_returns_data_for_every_available_field(surface_run):
    """``has_field`` and ``hmp.read`` must agree, with or without ``time``.

    The virtual fields are not persisted, so the batch reader has to rebuild
    them: reporting a field as available and then raising on the documented
    default read (``time=None``) is a broken contract.
    """
    import hydromodpy as hmp
    from hydromodpy.results import field_registry

    catalog, sid = surface_run
    run = catalog[sid]

    available = [name for name in field_registry.all_names() if run.has_field(name)]
    assert {"watertable_elevation", "watertable_depth", "seepage_mask"} <= set(available)
    for name in available:
        assert np.asarray(hmp.read(run, name)).size > 0, name
        assert np.asarray(hmp.read(run, name, time=0)).size > 0, name
        assert np.asarray(hmp.read(run, name, time=slice(0, 2))).size > 0, name


def test_list_fields_matches_has_field(surface_run):
    from hydromodpy.results import field_registry

    catalog, sid = surface_run
    run = catalog[sid]

    listed = run.array.list_fields()
    available = [name for name in field_registry.all_names() if run.has_field(name)]
    assert listed == sorted(available)


def test_exportable_fields_include_the_virtual_ones(surface_run):
    """A default run exports its water table, not just the raw head."""
    from hydromodpy.results.exporters.export_spec import ExportKind
    from hydromodpy.results.exporters.vocabulary import list_exportable

    catalog, sid = surface_run

    names = list_exportable(catalog[sid])
    fields = {name for name, kind in names.items() if kind is ExportKind.field}

    assert "head" in fields
    assert {"watertable_elevation", "watertable_depth", "seepage_mask"} <= fields


def test_view_names_the_key_when_the_terms_of_a_field_were_not_kept(surface_run):
    """A view on a field whose budget terms are missing must name the key."""
    from hydromodpy.results.derive.views import drainage_density
    from hydromodpy.results.errors import FieldNotFoundError

    catalog, sid = surface_run
    run = catalog[sid]

    with pytest.raises(FieldNotFoundError, match="keep_per_cell_budget"):
        drainage_density(run)


@pytest.fixture
def open_store(project: Path) -> Iterator[RunStore]:
    """A two-cell run with two periods of head, still open."""
    store = open_run_store(project, "run", n_cells=2, n_layers=1, n_timesteps=2)
    _write_field(store)
    yield store
    store.close()


def _budget_attrs(store: RunStore) -> dict:
    sz = store.open_zarr(store.sim_id)
    try:
        return dict(sz.root["budget"].attrs)
    finally:
        sz.close()


def test_the_budget_group_says_it_kept_every_written_term(open_store):
    from hydromodpy.core.budget.terms import BudgetKeep, kept_budget

    sid = open_store.sim_id
    open_store.write_field_stack(sid, "recharge", np.ones((2, 1, 2)), subgroup="budget")
    sz = open_store.open_zarr(sid)
    try:
        sz.write_budget_policy(BudgetKeep.everything(), ["storage_sy", "recharge", "recharge"])
        assert kept_budget(sz.root) == ("all", ("recharge", "storage_sy"))
    finally:
        sz.close()

    assert _budget_attrs(open_store) == {
        "policy": "all",
        "kept_terms": ["recharge", "storage_sy"],
    }


def test_the_budget_group_says_it_kept_the_planned_terms_produced_or_not(open_store):
    from hydromodpy.core.budget.terms import BudgetKeep

    sz = open_store.open_zarr(open_store.sim_id)
    try:
        assert "budget" not in sz.root
        # Nothing written: the group is created all the same, with its attributes.
        sz.write_budget_policy(BudgetKeep.of_terms({"recharge", "drain"}), [])
        assert list(sz.root["budget"].array_keys()) == []
    finally:
        sz.close()

    assert _budget_attrs(open_store) == {
        "policy": "consumers",
        "kept_terms": ["drain", "recharge"],
    }
