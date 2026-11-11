"""Tests of run reads."""

from __future__ import annotations

import json
import logging
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

import hydromodpy as hmp
from hydromodpy.catchment.drainage.descent import Descent, descent_from_stored_mesh
from hydromodpy.catchment.drainage.graph import accumulate_on_downhill_graph
from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.core.time.selection import TimeSelectionError
from hydromodpy.core.time.time_method import OBSERVABLE_TIME_METHODS
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.derive import views
from hydromodpy.results.derive.config_flags import config_option_for
from hydromodpy.results.derive.stream.run_extent import _release_rows
from hydromodpy.results.derive.time_alignment import (
    align_observed_simulated,
    first_period_start,
    observed_on_simulation_index,
    time_method_for,
)
from hydromodpy.results.derive.virtual_fields import read_field_range_or_virtual
from hydromodpy.results.errors import FieldNotFoundError
from hydromodpy.results.exporters.export_spec import ExportRequest
from hydromodpy.results.exporters.request import export_run
from hydromodpy.results.field_registry import FIELD_REGISTRY
from hydromodpy.results.readme import _checks_section, render_session_readme
from hydromodpy.results.record.checks import BUDGET_RULE, FROZE_BUDGET_ONLY, CalibratedBy
from hydromodpy.results.record.manifest import InputEntry, read_manifest
from hydromodpy.results.record.request_identity import RESTART_KEY, ZONE_RUN_KEY, request_id
from hydromodpy.results.run import Run
from hydromodpy.results.run.contracts import Mesh, polygon_areas
from hydromodpy.results.run.descent import (
    RunDescent,
    load_descent,
    read_basin,
    read_catchment_fraction,
)
from hydromodpy.results.run.geographic import field_range, field_steps
from hydromodpy.results.run.periods import RunPeriods
from hydromodpy.results.run.timeseries import RunTimeseriesMixin
from hydromodpy.results.session.descriptor import SessionDescriptor, write_session
from hydromodpy.results.session.phase import PhaseDescriptor
from hydromodpy.results.session.summary import session_summary, summary_rows
from hydromodpy.results.session.view import Session
from hydromodpy.results.source_runs import resolve_source_runs, source_run_id
from hydromodpy.results.storage.attempt import close_sealed_attempt
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME
from hydromodpy.results.storage.parquet_io import read_kv_metadata
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.results.trash import list_trash
from hydromodpy.results.validity_rules import RULE_VERSION, label_for
from hydromodpy.results.zarr_store import SimulationZarr
from hydromodpy.results.zarr_store.constants import ZARR_SCHEMA_VERSION
from hydromodpy.solver.modflow_common.descent_store import (
    write_descent_sidecar,
    write_descent_sidecar_to_store,
)
from tests._helpers.descent_cases import grid_descent
from tests._helpers.run_records import make_checks
from tests._helpers.run_stores import claim_run, facts_of, open_run_store
from tests._helpers.sealed_runs import make_project, seal_run
from tests._helpers.session_documents import session_descriptor
from tests._helpers.ugrid_meshes import quad_mesh

# ``views.budget_over`` sums a per-cell budget term over a polygon, the
# catchment by default, each face counted by ``mesh/catchment_fraction``. A run
# that stores the basin of D but no fraction counts the basin whole and says so.
# A run with no catchment (no basin, or only the largest basin of a synthetic
# domain) has no catchment total. Inflow and outflow are split per element. The
# outlet discharge is not one of these totals: it stays the ``catchment`` row of
# the budget, whole cells.
NROW, NCOL = 2, 3


N_CELLS = NROW * NCOL


BASIN = np.array([True, True, False, True, True, False])


FRACTION = np.array([1.0, 0.5, 0.25, 1.0, 0.75, 0.0])


# m3/s per cell, two steps; exact in the compact float precision of the store.
RECHARGE = np.array(
    [
        [0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
        [0.25, 1.0, 2.0, 0.125, 0.5, 4.0],
    ]
)


DRAIN = -np.array(
    [
        [0.0, 1.0, 0.0, 0.0, 2.0, 0.0],
        [0.5, 0.0, 1.0, 0.25, 0.0, 8.0],
    ]
)


STORAGE_SS = np.array(
    [
        [0.5, -0.25, 0.0, 1.0, 0.0, 0.0],
        [-1.0, 0.5, 0.0, 0.0, 2.0, 0.0],
    ]
)


STORAGE_SY = np.array(
    [
        [-0.5, 1.0, 0.0, -2.0, 0.0, 0.0],
        [0.25, 0.0, 0.0, 0.0, -1.0, 0.0],
    ]
)


def _store(
    tmp_path,
    *,
    rule: str = "near_point",
    fraction: np.ndarray | None = FRACTION,
    crs: str | None = "EPSG:2154",
    storage: bool = False,
    outside: dict[str | None, dict[str, np.ndarray]] | None = None,
):
    path = tmp_path / "run.zarr"
    store = SimulationZarr.create(path, n_cells=N_CELLS, n_layers=1)
    vertices, connectivity = quad_mesh(NROW, NCOL, cell_size=10.0)
    terms = [("recharge", RECHARGE), ("drain", DRAIN)]
    if storage:
        terms += [("storage_ss", STORAGE_SS), ("storage_sy", STORAGE_SY)]
    try:
        store.write_mesh(vertices, connectivity, np.array([0.0, -10.0]))
        store.write_time(np.array([86400.0, 2 * 86400.0]))
        for name, values in terms:
            store.write_field_stack(
                name, values[:, None, :], n_timesteps=2, timestep_offset=0, subgroup="budget"
            )
        for group, stacks in (outside or {}).items():
            for name, values in stacks.items():
                store.write_field_stack(name, values, n_timesteps=2, subgroup=group)
        if rule is not None:
            store.write_descent(
                receiver=np.full(N_CELLS, -1, dtype=np.int64),
                surface=np.zeros(N_CELLS),
                base_level=np.zeros(N_CELLS, dtype=bool),
                constant_head=np.zeros(N_CELLS, dtype=bool),
                raised=np.zeros(N_CELLS, dtype=bool),
                channel=np.zeros(N_CELLS, dtype=bool),
                pinned=np.zeros(N_CELLS, dtype=bool),
                attrs={"adjacency": "shared_nodes"},
                basin=BASIN,
                basin_attrs={"descent_outlet": 0, "basin_rule": rule},
                catchment_fraction=fraction,
            )
    finally:
        store.close()
    mesh = Mesh(
        vertices=vertices,
        face_node_connectivity=connectivity,
        z_interfaces=np.array([[0.0] * N_CELLS, [-10.0] * N_CELLS]),
        crs=crs,
    )
    return SimpleNamespace(
        sim_id="sim-total",
        _sim_id="sim-total",
        n_timesteps=2,
        mesh=mesh,
        has_field=lambda name, **_: name in dict(terms),
        _catalog=SimpleNamespace(open_zarr=lambda sim_id: SimulationZarr(path)),
    )


def test_a_boundary_cell_counts_by_its_share_in_the_polygon(tmp_path) -> None:
    run = _store(tmp_path)

    recharge = views.budget_over(run, "recharge")
    seepage = -views.budget_over(run, "drain", name="seepage")

    np.testing.assert_allclose(recharge.to_numpy(), RECHARGE @ FRACTION)
    np.testing.assert_allclose(seepage.to_numpy(), -DRAIN @ FRACTION)
    assert seepage.name == "seepage"
    assert list(recharge.index) == list(pd.to_datetime(["1970-01-02", "1970-01-03"]))


def test_the_fraction_reads_back_as_it_was_written(tmp_path) -> None:
    run = _store(tmp_path)

    fraction = read_catchment_fraction(run)

    np.testing.assert_array_equal(fraction, FRACTION)
    np.testing.assert_array_equal(views.catchment_weights(run), FRACTION)


def test_a_run_without_a_fraction_counts_the_basin_whole(tmp_path, caplog) -> None:
    run = _store(tmp_path, fraction=None)

    with caplog.at_level(logging.INFO):
        recharge = views.budget_over(run, "recharge")

    assert read_catchment_fraction(run) is None
    np.testing.assert_allclose(recharge.to_numpy(), RECHARGE @ BASIN.astype(float))
    assert "count the cells of the basin of D whole" in caplog.text


@pytest.mark.parametrize(
    ("rule", "message"),
    [("largest_basin", "only the largest one of its domain"), (None, "is missing")],
    ids=["synthetic_domain", "no_basin"],
)
def test_a_run_with_no_catchment_has_no_total_over_it(tmp_path, rule, message) -> None:
    run = _store(tmp_path, rule=rule, fraction=None)

    with pytest.raises(ValueError, match=message):
        views.budget_over(run, "recharge")


def test_a_polygon_over_two_cells_counts_their_area_inside(tmp_path) -> None:
    from shapely.geometry import box

    run = _store(tmp_path)
    # Cells 0 and 1 are the squares [0, 10] and [10, 20] of the first row; the
    # box holds all of cell 0 and half of cell 1.
    total = views.budget_over(run, "recharge", box(0.0, 0.0, 15.0, 10.0))

    np.testing.assert_allclose(total.to_numpy(), RECHARGE[:, 0] + 0.5 * RECHARGE[:, 1])


def test_a_polygon_in_another_crs_is_placed_on_the_mesh(tmp_path) -> None:
    from pyproj import Transformer
    from shapely.geometry import box
    from shapely.ops import transform

    run = _store(tmp_path, crs="EPSG:2154")
    to_wgs84 = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True).transform
    polygon = transform(to_wgs84, box(0.0, 0.0, 10.0, 10.0))

    total = views.budget_over(run, "recharge", polygon, crs="EPSG:4326")

    np.testing.assert_allclose(total.to_numpy(), RECHARGE[:, 0], rtol=1e-6)


@pytest.mark.parametrize(
    ("crs", "refused"), [(None, False), ("EPSG:4326", True)], ids=["mesh_frame", "foreign_crs"]
)
def test_a_run_without_a_crs_takes_a_polygon_only_in_mesh_coordinates(tmp_path, crs, refused):
    from shapely.geometry import box

    run = _store(tmp_path, crs=None)
    if refused:
        with pytest.raises(ValueError, match="stores no CRS, so a polygon in EPSG:4326"):
            views.budget_over(run, "recharge", box(0.0, 0.0, 10.0, 10.0), crs=crs)
        return
    total = views.budget_over(run, "recharge", box(0.0, 0.0, 10.0, 10.0), crs=crs)
    np.testing.assert_allclose(total.to_numpy(), RECHARGE[:, 0])


def test_storage_sums_the_members_of_its_family(tmp_path) -> None:
    run = _store(tmp_path, storage=True)

    storage = views.budget_over(run, "storage")
    split = views.budget_over(run, "storage", split=True)

    cells = STORAGE_SS + STORAGE_SY
    np.testing.assert_allclose(storage.to_numpy(), cells @ FRACTION)
    assert storage.name == "storage"
    elements = np.stack([STORAGE_SS, STORAGE_SY])
    np.testing.assert_allclose(split["inflow"], np.maximum(elements, 0).sum(axis=0) @ FRACTION)
    np.testing.assert_allclose(split["outflow"], np.maximum(-elements, 0).sum(axis=0) @ FRACTION)


def test_split_gives_the_positive_inflow_and_outflow(tmp_path) -> None:
    run = _store(tmp_path)

    split = views.budget_over(run, "drain", split=True)

    assert list(split.columns) == ["inflow", "outflow"]
    np.testing.assert_allclose(split["inflow"], [0.0, 0.0])
    np.testing.assert_allclose(split["outflow"], -DRAIN @ FRACTION)
    assert list(split.index) == list(pd.to_datetime(["1970-01-02", "1970-01-03"]))


def test_a_budget_term_is_read_from_budget_when_another_group_holds_its_name(tmp_path) -> None:
    run = _store(tmp_path, outside={None: {"recharge": 10.0 * RECHARGE}})

    total = views.budget_over(run, "recharge")

    np.testing.assert_allclose(total.to_numpy(), RECHARGE @ FRACTION)


def test_a_field_in_m3_per_second_outside_budget_is_summed_too(tmp_path) -> None:
    release = np.abs(DRAIN)
    run = _store(tmp_path, outside={"derived": {"release_flux": release}})

    total = views.budget_over(run, "release_flux")
    split = views.budget_over(run, "release_flux", split=True)

    np.testing.assert_allclose(total.to_numpy(), release @ FRACTION)
    np.testing.assert_allclose(split["outflow"], [0.0, 0.0])


def test_a_field_outside_budget_in_another_unit_is_refused(tmp_path) -> None:
    run = _store(tmp_path, outside={"derived": {"watertable_depth": np.abs(DRAIN)}})

    with pytest.raises(FieldNotFoundError, match="as a budget term or a field in m3/s"):
        views.budget_over(run, "watertable_depth")


def test_a_term_the_run_does_not_store_is_refused_by_name(tmp_path) -> None:
    run = _store(tmp_path)

    with pytest.raises(FieldNotFoundError, match="'storage' is not stored per cell"):
        views.budget_over(run, "storage")


# ``Run.field`` reads one step and opens the store for it. Counting the flowing
# cells of a daily run that way opened the store 4 385 times. ``field_range``
# opens it once for a whole range. Each of its rows must be the step read, bit
# for bit, on a compact store and on a store written before (float64, with
# ``derived/release_flux`` stored).
N_STEPS = 7


N_LAYERS = 2


AREAS = np.array([10.0, 20.0, 40.0, 80.0, 20.0])


N_CELLS_2 = AREAS.size


TOP = np.array([130.0, 128.0, 125.0, 121.0, 119.0])


def _row_of_rectangles() -> tuple[np.ndarray, np.ndarray]:
    """Unit-height rectangles whose width is the area."""
    x = np.concatenate([[0.0], np.cumsum(AREAS)])
    vertices = np.array([[xi, 0.0, 0.0] for xi in x] + [[xi, 1.0, 0.0] for xi in x])
    n_x = x.size
    connectivity = np.array([[i, i + 1, n_x + i + 1, n_x + i] for i in range(N_CELLS_2)])
    return vertices, connectivity.astype("int32")


@contextmanager
def _sealed(
    project: Path,
    *,
    precision: str | None = None,
    derived: dict[str, np.ndarray] | None = None,
) -> Iterator[tuple[Catalog, str]]:
    """Seal a two-layer run with its head and a drain, stream and recharge budget.

    ``derived`` holds the stacks a run written before kept under ``derived/``.
    The project is indexed and the catalog and the run id are yielded.
    """
    rng = np.random.default_rng(11)
    claim = claim_run(project, "run")
    store = RunStore.open(
        claim.run_dir,
        facts=facts_of(
            claim, project="p", n_cells=N_CELLS_2, n_layers=N_LAYERS, n_timesteps=N_STEPS
        ),
        persistence=PersistenceConfig()
        if precision is None
        else PersistenceConfig(field_precision=precision),
        workspace=project,
    )
    store.create_zarr(n_cells=N_CELLS_2, n_layers=N_LAYERS)
    sid = store.sim_id
    head = rng.uniform(110.0, 131.0, (N_STEPS, N_LAYERS, N_CELLS_2))
    head[:, 0, 1] = np.nan
    drain = -rng.uniform(0.0, 2e-3, (N_STEPS, N_LAYERS, N_CELLS_2))
    stream = rng.uniform(-3e-3, 1e-3, (N_STEPS, N_LAYERS, N_CELLS_2))
    recharge = rng.uniform(0.0, 1e-4, (N_STEPS, N_LAYERS, N_CELLS_2))
    vertices, connectivity = _row_of_rectangles()
    sz = store.open_zarr(sid)
    try:
        sz.write_mesh(vertices, connectivity, np.array([150.0, 100.0, 50.0]))
        sz.write_topography(TOP)
        sz.write_field_stack("head", head)
        for name, values in (("drain", drain), ("stream", stream), ("recharge", recharge)):
            sz.write_field_stack(name, values, subgroup="budget")
        for name, values in (derived or {}).items():
            sz.write_field_stack(name, values, subgroup="derived")
    finally:
        sz.close()
    seal_completed(store)
    rebuild_index(project)
    with Catalog(project) as catalog:
        yield catalog, sid


def _step_by_step(run: Run, variable: str, steps, layer: int | None = None) -> np.ndarray:
    return np.stack([run.field(variable, time=int(t), layer=layer) for t in steps])


class _CountingCatalog:
    """Count the store openings of a catalog, every other call passed through."""

    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog
        self.openings = 0

    def open_zarr(self, sim_id):
        self.openings += 1
        return self._catalog.open_zarr(sim_id)

    def query_field(self, sim_id, variable, timestep, layer=None):
        from hydromodpy.results.derive.virtual_fields import read_field_or_virtual

        return read_field_or_virtual(self, str(sim_id), variable, timestep, layer=layer)

    def __getattr__(self, name):
        return getattr(self._catalog, name)


@pytest.fixture
def seeded(tmp_path: Path) -> Iterator[tuple[Catalog, str]]:
    """A compact run, sealed and indexed: the catalog of its project and its id."""
    with _sealed(tmp_path / "workspace") as pair:
        yield pair


@pytest.fixture
def catalog(seeded: tuple[Catalog, str]) -> Catalog:
    return seeded[0]


@pytest.fixture
def sid(seeded: tuple[Catalog, str]) -> str:
    return seeded[1]


class TestAStoredField:
    def test_the_range_is_each_step_read_bit_for_bit(self, catalog, sid) -> None:
        run = Run(sid, catalog)

        whole = field_range(run, "head", 0, N_STEPS)

        assert whole.dtype == np.float64
        assert whole.shape == (N_STEPS, N_LAYERS, N_CELLS_2)
        np.testing.assert_array_equal(whole, _step_by_step(run, "head", range(N_STEPS)))
        np.testing.assert_array_equal(
            field_range(run, "head", 2, 5), _step_by_step(run, "head", range(2, 5))
        )

    def test_a_layer_is_picked_as_a_step_read_picks_it(self, catalog, sid) -> None:
        run = Run(sid, catalog)

        lower = field_range(run, "head", 1, 6, layer=1)

        assert lower.shape == (5, N_CELLS_2)
        np.testing.assert_array_equal(lower, _step_by_step(run, "head", range(1, 6), layer=1))

    def test_negative_bounds_count_from_the_end(self, catalog, sid) -> None:
        run = Run(sid, catalog)

        np.testing.assert_array_equal(
            field_range(run, "head", -3, N_STEPS), field_range(run, "head", N_STEPS - 3, N_STEPS)
        )
        np.testing.assert_array_equal(
            read_field_range_or_virtual(catalog, sid, "head", -2, -1)[0],
            catalog.query_field(sid, "head", N_STEPS - 2),
        )

    def test_a_static_field_repeats_once_per_step(self, catalog, sid) -> None:
        run = Run(sid, catalog)

        np.testing.assert_array_equal(
            field_range(run, "topography", 0, 3), _step_by_step(run, "topography", range(3))
        )

    def test_the_range_opens_the_store_once(self, catalog, sid) -> None:
        counting = _CountingCatalog(catalog)
        run = Run(sid, counting)

        field_range(run, "head", 0, N_STEPS)

        assert counting.openings == 1


class TestAFieldRebuiltOnRead:
    @pytest.mark.parametrize("variable", ["release_flux", "budget_flux_per_area"])
    def test_a_range_rebuild_is_each_step_rebuilt(self, catalog, sid, variable) -> None:
        run = Run(sid, catalog)

        whole = field_range(run, variable, 0, N_STEPS)

        assert whole.shape == (N_STEPS, N_CELLS_2)
        np.testing.assert_array_equal(whole, _step_by_step(run, variable, range(N_STEPS)))
        np.testing.assert_array_equal(
            field_range(run, variable, 3, 6), _step_by_step(run, variable, range(3, 6))
        )

    @pytest.mark.parametrize(
        "variable", ["watertable_elevation", "watertable_depth", "seepage_mask", "outflow_drain"]
    )
    def test_any_other_is_rebuilt_step_by_step_on_one_opening(self, catalog, sid, variable) -> None:
        counting = _CountingCatalog(catalog)
        run = Run(sid, counting)

        whole = field_range(run, variable, 0, N_STEPS)

        assert counting.openings == 1
        np.testing.assert_array_equal(
            whole, _step_by_step(Run(sid, catalog), variable, range(N_STEPS))
        )

    def test_the_simulated_network_builds_its_graph_once_for_the_range(
        self, catalog, sid, monkeypatch
    ) -> None:
        from hydromodpy.results.derive import virtual_fields

        calls: list[list[int]] = []

        def stack(run, timesteps):
            calls.append([int(t) for t in timesteps])
            return np.asarray([[t % 2, 1.0, 0.0, t, 1.0] for t in timesteps], dtype=float)

        monkeypatch.setattr(virtual_fields, "simulated_active_network_stack", stack)
        name = virtual_fields.SIMULATED_ACTIVE_NETWORK

        whole = read_field_range_or_virtual(catalog, sid, name, 1, 5)

        assert calls == [[1, 2, 3, 4]]
        np.testing.assert_array_equal(
            whole, np.stack([catalog.query_field(sid, name, t) for t in range(1, 5)])
        )

    def test_a_layer_is_ignored_where_a_step_read_ignores_it(self, catalog, sid) -> None:
        run = Run(sid, catalog)

        np.testing.assert_array_equal(
            field_range(run, "release_flux", 0, 4, layer=1),
            _step_by_step(run, "release_flux", range(4), layer=1),
        )


class TestTheErrors:
    @pytest.mark.parametrize("variable", ["no_such_field", "mass_seepage_running_sum"])
    def test_a_field_nothing_holds_raises_what_a_step_read_raises(
        self, catalog, sid, variable
    ) -> None:
        run = Run(sid, catalog)

        with pytest.raises(FieldNotFoundError) as by_step:
            run.field(variable, time=0)
        with pytest.raises(FieldNotFoundError) as by_range:
            field_range(run, variable, 0, 2)
        with pytest.raises(KeyError) as by_catalog_step:
            catalog.query_field(sid, variable, 0)
        with pytest.raises(KeyError) as by_reader_range:
            read_field_range_or_virtual(catalog, sid, variable, 0, 2)

        assert str(by_range.value) == str(by_step.value)
        assert str(by_reader_range.value) == str(by_catalog_step.value)
        if config_option_for(variable) is not None:
            assert "run the simulation again" in str(by_range.value)

    @pytest.mark.parametrize("variable", ["head", "release_flux", "watertable_elevation"])
    @pytest.mark.parametrize(
        ("start", "stop"), [(0, N_STEPS + 1), (4, 2), (-N_STEPS - 1, 2), (N_STEPS + 1, N_STEPS + 2)]
    )
    def test_a_range_off_the_time_axis_is_refused(
        self, catalog, sid, variable, start, stop
    ) -> None:
        """A slice would hand back fewer rows than asked; the range refuses instead."""

        with pytest.raises(IndexError):
            read_field_range_or_virtual(catalog, sid, variable, start, stop)

    def test_a_stored_step_off_the_time_axis_is_refused_alike(self, catalog, sid) -> None:

        with pytest.raises(IndexError):
            catalog.query_field(sid, "head", N_STEPS)
        with pytest.raises(IndexError):
            field_range(Run(sid, catalog), "head", N_STEPS - 1, N_STEPS + 1)


class TestAStoreWrittenBefore:
    def test_its_stored_release_is_read_not_rebuilt(self, tmp_path: Path) -> None:
        # Deliberately not what the budget rebuilds, so a recomputation is caught.
        stored = np.arange(N_STEPS * N_CELLS_2, dtype="float64").reshape(N_STEPS, N_CELLS_2) / 7.0
        derived = {"release_flux": stored}
        with _sealed(tmp_path / "old", precision="exact", derived=derived) as (catalog, sid):
            run = Run(sid, catalog)

            whole = field_range(run, "release_flux", 0, N_STEPS)

            assert whole.dtype == np.float64
            np.testing.assert_array_equal(whole, stored)
            np.testing.assert_array_equal(whole, _step_by_step(run, "release_flux", range(N_STEPS)))

    def test_its_float64_head_reads_as_each_step(self, tmp_path: Path) -> None:
        with _sealed(tmp_path / "old", precision="exact") as (catalog, sid):
            run = Run(sid, catalog)

            np.testing.assert_array_equal(
                field_range(run, "head", 0, N_STEPS), _step_by_step(run, "head", range(N_STEPS))
            )


class TestTheReleaseRowsOfTheFlowCounts:
    @pytest.mark.parametrize(
        "steps", [[0, 1, 2, 3, 4, 5, 6], [0, 1, 2, 4], [5, 1, 2, 3, 0], [3], [6, 5, 4]]
    )
    def test_they_are_the_step_by_step_read_on_a_compact_store(self, catalog, sid, steps) -> None:
        run = Run(sid, catalog)

        rows = _release_rows(run, np.asarray(steps), N_CELLS_2)

        np.testing.assert_array_equal(rows, _step_by_step(run, "release_flux", steps))

    def test_they_are_the_stored_rows_on_a_store_written_before(self, tmp_path: Path) -> None:
        stored = np.linspace(0.0, 1.0, N_STEPS * N_CELLS_2).reshape(N_STEPS, N_CELLS_2)
        derived = {"release_flux": stored}
        with _sealed(tmp_path / "old", precision="exact", derived=derived) as (catalog, sid):
            run = Run(sid, catalog)
            steps = [0, 1, 2, 5, 6, 3]

            rows = _release_rows(run, np.asarray(steps), N_CELLS_2)

            np.testing.assert_array_equal(rows, stored[steps])
            np.testing.assert_array_equal(rows, _step_by_step(run, "release_flux", steps))

    def test_a_block_of_consecutive_steps_opens_the_store_once(self, catalog, sid) -> None:
        counting = _CountingCatalog(catalog)
        run = Run(sid, counting)

        _release_rows(run, np.arange(N_STEPS), N_CELLS_2)

        assert counting.openings == 1

    def test_a_cell_count_other_than_the_mesh_is_refused(self, catalog, sid) -> None:
        run = Run(sid, catalog)

        with pytest.raises(ValueError, match="not written for the same run"):
            _release_rows(run, np.arange(3), N_CELLS_2 + 1)


@pytest.mark.parametrize("steps", [[-2, -1], [-1, 0, 1, 2], [6, -1, 4, 5]])
def test_negative_steps_are_read_as_their_step_read(catalog, sid, steps) -> None:
    run = Run(sid, catalog)

    np.testing.assert_array_equal(
        field_steps(run, "release_flux", steps), _step_by_step(run, "release_flux", steps)
    )


def test_a_stand_in_without_a_range_reader_is_read_step_by_step() -> None:
    stack = np.arange(12.0).reshape(4, 3)
    stand_in = SimpleNamespace(field=lambda variable, time=-1, **_: stack[int(time)])

    np.testing.assert_array_equal(
        field_steps(stand_in, "release_flux", [2, 0, 1]), stack[[2, 0, 1]]
    )


# A ``Project`` closes its catalog at the end of its ``with`` block, and every
# ``Run`` taken from it used to fail with ``Connection already closed``. The run
# reopens a reader on the same index instead.
def test_a_run_reopens_a_closed_catalog(tmp_path) -> None:
    root = make_project(tmp_path / "demo")
    sid = seal_run(root, "x")
    rebuild_index(root)
    cat = Catalog(root)
    run = Run(sid, cat)
    group = cat.find(project="demo")
    cat.close()
    assert cat.closed

    assert run.name == "x"
    assert run.status == "completed"
    assert group[0].name == "x"
    assert run._catalog is not cat
    assert run._catalog.closed is False
    run._catalog.close()


def test_two_readers_of_one_index_coexist(tmp_path) -> None:
    root = make_project(tmp_path / "demo")
    sid = seal_run(root, "x")
    rebuild_index(root)
    first = Catalog(root)
    run = Run(sid, first)
    first.close()
    assert run.name == "x"
    reader = Catalog(root)
    assert reader[sid].name == "x"
    reader.close()
    run._catalog.close()


# ``Run.field(bbox=)`` and the xarray reader select the cells whose center lies in
# the box, the centers being the ones of ``run.mesh``. The default GeoTIFF
# resolution is the side of the smallest cell of that mesh. Neither reads the DEM
# grid of the catalog, which a mesh is not obliged to follow.
LAMBERT_X0, LAMBERT_Y0, CELL = 385_050.0, 6_814_050.0, 75.0


@contextmanager
def _sealed_2(
    project: Path,
    vertices: np.ndarray,
    faces: np.ndarray,
    values: np.ndarray,
    *,
    structured_shape: tuple[int, int] | None = None,
    dem_shape: tuple[int, int] | None = None,
) -> Iterator[tuple[Catalog, str]]:
    """Seal a one-period run on the given mesh, with an optional DEM grid of its own.

    Yields the catalog of the project, indexed with the run, and the id of the run.
    """
    name = f"run{len(list(project.glob('runs/*')))}" if project.exists() else "run0"
    store = open_run_store(
        project,
        name,
        n_cells=len(faces),
        n_layers=1,
        n_timesteps=1,
        crs_epsg=2154,
        crs_wkt="EPSG:2154",
        period_start=datetime(2000, 1, 1, tzinfo=UTC),
        period_end=datetime(2000, 2, 1, tzinfo=UTC),
        time_unit="month",
    )
    sid = store.sim_id
    zarr_store = store.open_zarr(sid)
    try:
        zarr_store.write_mesh(
            vertices, faces, np.array([10.0, 0.0]), structured_shape=structured_shape
        )
    finally:
        zarr_store.close()
    store.write_time(sid, np.array(["2000-02-01"], dtype="datetime64[s]").astype("int64"))
    store.write_crs(sid, crs_wkt="EPSG:2154", epsg_code=2154)
    store.write_field(sid, "head", 0, values.reshape(1, -1), n_timesteps=1)
    if dem_shape is not None:
        nrow, ncol = dem_shape
        store.write_geographic_metadata(
            sid,
            {"dem_res": 50.0, "nrow": nrow, "ncol": ncol, "crs_proj": "EPSG:2154"},
        )
        store.write_geographic_raster(
            sid,
            "watershed_dem",
            np.full((nrow, ncol), 100.0),
            transform=(50.0, 0.0, 0.0, 0.0, -50.0, 500.0),
            crs="EPSG:2154",
            nodata=-9999.0,
        )
    seal_completed(store)
    rebuild_index(project)
    with Catalog(project) as catalog:
        yield catalog, sid


def _lambert_grid(nrow: int, ncol: int) -> tuple[np.ndarray, np.ndarray]:
    """A grid of 75 m cells in Lambert-93, row 0 at the north, as the regular engine writes it."""
    ys = LAMBERT_Y0 + CELL * (nrow - np.arange(nrow + 1))
    xs = LAMBERT_X0 + CELL * np.arange(ncol + 1)
    vertices = np.array([[x, y, 0.0] for y in ys for x in xs])
    node = np.arange((nrow + 1) * (ncol + 1)).reshape(nrow + 1, ncol + 1)
    faces = np.array(
        [
            [node[i, j], node[i, j + 1], node[i + 1, j + 1], node[i + 1, j]]
            for i in range(nrow)
            for j in range(ncol)
        ],
        dtype=np.int32,
    )
    return vertices, faces


def _irregular_mesh() -> tuple[np.ndarray, np.ndarray]:
    """Six cells of 3, 4 and 5 corners, padded with -1, none on a pixel lattice."""
    vertices = np.array(
        [
            [0.0, 0.0, 0.0],
            [40.0, 0.0, 0.0],
            [90.0, 10.0, 0.0],
            [140.0, 0.0, 0.0],
            [0.0, 60.0, 0.0],
            [50.0, 70.0, 0.0],
            [100.0, 55.0, 0.0],
            [150.0, 65.0, 0.0],
            [20.0, 120.0, 0.0],
            [80.0, 125.0, 0.0],
            [140.0, 120.0, 0.0],
        ]
    )
    faces = np.array(
        [
            [0, 1, 5, 4, -1],
            [1, 2, 6, 5, -1],
            [2, 3, 7, 6, -1],
            [4, 5, 9, 8, -1],
            [5, 6, 9, -1, -1],
            [6, 7, 10, 9, -1],
        ],
        dtype=np.int32,
    )
    return vertices, faces


def test_bbox_selects_the_cells_of_an_irregular_mesh(project) -> None:
    vertices, faces = _irregular_mesh()
    values = np.arange(1.0, 7.0)
    # The DEM grid has as many pixels as the mesh has cells, 2 x 3 = 6, at other places.
    with _sealed_2(project, vertices, faces, values, dem_shape=(2, 3)) as (catalog, sid):
        run = Run(sid, catalog)

        box = (0.0, 0.0, 100.0, 70.0)
        centers = run.mesh.cell_centers()
        inside = (
            (centers[:, 0] >= box[0])
            & (centers[:, 0] <= box[2])
            & (centers[:, 1] >= box[1])
            & (centers[:, 1] <= box[3])
        )
        assert 0 < inside.sum() < len(values)

        masked = run.field("head", time=0, bbox=box)
        np.testing.assert_array_equal(np.isfinite(masked[0]), inside)
        np.testing.assert_array_equal(masked[0][inside], values[inside])

        dataset = run.array.to_xarray_batch(("head",), bbox=box)
        assert dataset.sizes["cell"] == inside.sum()
        np.testing.assert_array_equal(dataset["head"].values.reshape(-1), values[inside])


def test_bbox_on_a_grid_of_pixels_keeps_the_pixel_rule(project) -> None:
    nrow, ncol = 4, 5
    vertices, faces = _lambert_grid(nrow, ncol)
    values = np.arange(nrow * ncol, dtype=float)
    with _sealed_2(project, vertices, faces, values, structured_shape=(nrow, ncol)) as (
        catalog,
        sid,
    ):
        run = Run(sid, catalog)

        # The rule of the DEM lattice: pixel (i, j) is centered at (xmin + (j + .5) cs, ymax - (i + .5) cs).
        cols, rows = np.meshgrid(np.arange(ncol), np.arange(nrow))
        xs = LAMBERT_X0 + (cols.ravel() + 0.5) * CELL
        ys = LAMBERT_Y0 + nrow * CELL - (rows.ravel() + 0.5) * CELL
        box = (LAMBERT_X0 + CELL, LAMBERT_Y0 + CELL, LAMBERT_X0 + 3.6 * CELL, LAMBERT_Y0 + 3 * CELL)
        expected = (xs >= box[0]) & (xs <= box[2]) & (ys >= box[1]) & (ys <= box[3])

        masked = run.field("head", time=0, bbox=box)
        np.testing.assert_array_equal(np.isfinite(masked[0]), expected)
        assert run.mesh.structured_shape == (nrow, ncol)


def test_a_bbox_that_is_not_a_box_is_refused(project) -> None:
    vertices, faces = _irregular_mesh()
    with _sealed_2(project, vertices, faces, np.arange(6.0)) as (catalog, sid):
        with pytest.raises(ValueError, match="xmin<xmax"):
            Run(sid, catalog).field("head", time=0, bbox=(10.0, 0.0, 0.0, 10.0))


def test_stored_face_centres_win_over_the_corner_mean() -> None:
    vertices, faces = _irregular_mesh()
    mean = Mesh(vertices, faces, np.array([1.0, 0.0])).cell_centers()
    stored_x, stored_y = mean[:, 0] + 1.0, mean[:, 1] - 2.0
    stored = Mesh(
        vertices, faces, np.array([1.0, 0.0]), face_x=stored_x, face_y=stored_y
    ).cell_centers()
    np.testing.assert_array_equal(stored, np.column_stack((stored_x, stored_y)))
    # The mean of a padded row ignores the padding.
    np.testing.assert_allclose(mean[4], vertices[[5, 6, 9], :2].mean(axis=0))


def test_areas_keep_their_precision_far_from_the_origin() -> None:
    vertices, faces = _lambert_grid(3, 3)
    np.testing.assert_array_equal(polygon_areas(vertices, faces), np.full(9, CELL * CELL))
    _, irregular = _irregular_mesh()
    areas = polygon_areas(_irregular_mesh()[0], irregular)
    triangle = 0.5 * abs((100 - 50) * (125 - 70) - (80 - 50) * (55 - 70))  # cell 4: corners 5, 6, 9
    assert areas[4] == pytest.approx(triangle)
    assert np.isnan(polygon_areas(vertices, np.array([[0, 1, -1, -1]]))[0])


def test_a_face_table_padded_with_nan_gives_the_areas_of_its_integer_twin() -> None:
    vertices, faces = _lambert_grid(2, 2)
    padded = faces.astype(float)
    padded[0, 3] = np.nan

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        areas = polygon_areas(vertices, padded)

    twin = faces.copy()
    twin[0, 3] = -1
    np.testing.assert_array_equal(areas, polygon_areas(vertices, twin))


def test_the_default_geotiff_resolution_is_the_smallest_cell(project) -> None:
    import rasterio

    vertices, faces = _irregular_mesh()
    areas = polygon_areas(vertices, faces)
    with _sealed_2(project, vertices, faces, np.arange(6.0)) as (catalog, sid):
        written = export_run(catalog, sid, ExportRequest(variables="head", time="2000-01-15"))

        with rasterio.open(written[0]) as src:
            # The exporter fits whole pixels of at most that side over the extent.
            side = np.sqrt(np.nanmin(areas))
            assert src.width == int(np.ceil(np.ptp(vertices[:, 0]) / side))
            assert src.height == int(np.ceil(np.ptp(vertices[:, 1]) / side))


def test_a_grid_of_75_m_cells_exports_at_75_m(project) -> None:
    import rasterio

    vertices, faces = _lambert_grid(4, 5)
    with _sealed_2(project, vertices, faces, np.arange(20.0), structured_shape=(4, 5)) as (
        catalog,
        sid,
    ):
        written = export_run(catalog, sid, ExportRequest(variables="head", time="2000-01-15"))

        with rasterio.open(written[0]) as src:
            assert src.res == (CELL, CELL)
            assert (src.height, src.width) == (4, 5)


def test_a_default_that_would_give_too_many_pixels_asks_for_a_resolution(project) -> None:
    # A 1 m cell in a 200 km wide domain: 4e10 pixels.
    vertices = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [1.0, 1.0, 0.0],
            [0.0, 1.0, 0.0],
            [200_000.0, 0.0, 0.0],
            [200_000.0, 200_000.0, 0.0],
            [0.0, 200_000.0, 0.0],
        ]
    )
    faces = np.array([[0, 1, 2, 3], [1, 4, 5, 2], [3, 2, 5, 6]], dtype=np.int32)
    with _sealed_2(project, vertices, faces, np.arange(3.0)) as (catalog, sid):
        with pytest.raises(ValueError, match=r"resolution=") as raised:
            export_run(catalog, sid, ExportRequest(variables="head", time="2000-01-15"))
        assert "smallest cell" in str(raised.value)

        written = export_run(
            catalog, sid, ExportRequest(variables="head", time="2000-01-15", resolution=20_000.0)
        )
        assert written[0].exists()


# The display and export steps open a :class:`Run` on the store of the run in
# flight. Its rows (series, observations, budget), its periods and its status
# come from the run directory, with ``Catalog.__init__`` patched to raise. Once
# sealed, a table written after the seal carries the licence of the seal, the
# annotations of the run land in ``annotations.json``, and the run is deleted
# by a move to the trash.
STAMPS = pd.to_datetime(["2000-02-01", "2000-03-01", "2000-04-01"])


@pytest.fixture
def no_index(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args, **_kwargs):
        raise AssertionError("a run step opened the index")

    monkeypatch.setattr(Catalog, "__init__", refuse)


def _monthly_store(project: Path) -> RunStore:
    store = open_run_store(
        project,
        "monthly",
        n_timesteps=3,
        period_start=datetime(2000, 1, 1, tzinfo=UTC),
        period_end=datetime(2000, 4, 1, tzinfo=UTC),
        time_unit="month",
    )
    sid = store.sim_id
    store.write_time(sid, STAMPS.values.astype("datetime64[s]").astype("int64"))
    store.write_timeseries(sid, "J0014010", "discharge", pd.Series([1.0, 2.0, 3.0], index=STAMPS))
    store.write_timeseries(
        sid, "J0014010", "discharge", pd.Series([1.5, 2.5], index=STAMPS[:2]), source="observed"
    )
    store.write_budgets(
        sid,
        [
            {"timestep": t, "zone_id": "catchment", "component": "drain", "flux_out": 1.0 + t}
            for t in range(3)
        ],
    )
    return store


def test_a_running_run_reads_its_rows_from_its_directory(tmp_path: Path, no_index) -> None:
    with _monthly_store(tmp_path / "p") as store:
        run = Run(store.sim_id, store)

        assert run.status == "running"
        assert run.n_timesteps == 3
        assert run.stations("discharge") == ["J0014010"]
        assert run.timeseries("discharge").tolist() == [1.0, 2.0, 3.0]
        assert run.timeseries("discharge", period=("2000-02-15", "2000-04-30")).tolist() == [
            2.0,
            3.0,
        ]
        assert run.observed("discharge")["value"].tolist() == [1.5, 2.5]
        assert run.budget(component="drain")["flux_out"].tolist() == [1.0, 2.0, 3.0]
        assert run.has_table("budgets") and not run.has_table("mass_balance")
        assert list(run.periods.edges) == list(
            pd.to_datetime(["2000-01-01", "2000-02-01", "2000-03-01", "2000-04-01"])
        )
        assert run.periods.step_at("2000-02-15") == 1


WINDOWS = [
    (("2000-02-01", "2000-03-01"), [2.0], [1.5]),
    (("2000-02-15", "2000-02-20"), [2.0], [1.5]),
    (("2000-01-01", "2000-02-01"), [1.0], []),
    (("2000-01-01", "2000-01-01"), [1.0], []),
    (("2000-03-01", "2000-03-01"), [2.0], [1.5]),
    ("2000", [1.0, 2.0, 3.0], [1.5, 2.5]),
]


@pytest.mark.parametrize(("window", "simulated", "observed"), WINDOWS)
def test_a_window_over_a_series_reads_the_same_in_every_reader(
    tmp_path: Path, window: object, simulated: list[float], observed: list[float]
) -> None:
    store = _monthly_store(tmp_path / "p")
    kept = store.query_timeseries(store.sim_id, "J0014010", "discharge", window)
    assert kept.tolist() == simulated
    run_dir = store.run_dir
    seal_completed(store)
    run = hmp.open(run_dir)
    rebuild_index(tmp_path / "p")

    assert hmp.read(run, "discharge", sel={"period": window}).tolist() == simulated
    assert run.timeseries("discharge", period=window).tolist() == simulated
    with Catalog(tmp_path / "p") as catalog:
        read = catalog.query_timeseries(run.sim_id, "J0014010", "discharge", period=window)
        assert read.tolist() == simulated
    if observed:
        assert run.timeseries("discharge", period=window, source="observed").tolist() == observed
        assert run.observed("discharge", period=window)["value"].tolist() == observed
    else:
        with pytest.raises(ValueError, match="No observations"):
            run.observed("discharge", period=window)


def test_a_table_written_after_the_seal_keeps_the_licence_of_the_seal(tmp_path: Path) -> None:
    store = _monthly_store(tmp_path / "p")
    store.record_input(
        store.sim_id,
        InputEntry(
            variable="discharge:J0014010",
            provider="hubeau",
            path="data/hubeau/discharge.csv",
            license="etalab-2.0",
        ),
    )
    run_dir = store.run_dir
    seal_completed(store)
    close_sealed_attempt(run_dir)
    sealed_licence = read_manifest(run_dir)["run"]["license"]

    with RunStore.open(run_dir) as reopened:
        reopened.write_view(
            reopened.sim_id,
            "observation_points",
            [{"station_id": "p1", "x": 0.0, "y": 0.0, "cell_id": 0, "layer": 0}],
        )
        footer = read_kv_metadata(reopened.table_path_for(reopened.sim_id, "observation_points"))

    assert sealed_licence not in (None, "", "LicenseRef-undetermined")
    assert footer["license"] == sealed_licence


def test_tags_notes_and_delete_are_written_in_the_run_directory(tmp_path: Path) -> None:
    project = tmp_path / "p"
    store = _monthly_store(project)
    run_dir, sid = store.run_dir, store.sim_id
    seal_completed(store)
    close_sealed_attempt(run_dir)

    with RunStore.open(run_dir) as sealed:
        run = Run(sid, sealed)
        run.tag("keep", "+pinned", "-keep")
        run.note("best fit")

        payload = json.loads((run_dir / "annotations.json").read_text(encoding="utf-8"))
        assert payload["sim_id"] == sid
        assert payload["tags"] == ["pinned"]
        assert [note["note"] for note in payload["notes"]] == ["best fit"]
        assert run.tags == ["pinned"]

    with RunStore.open(run_dir) as sealed:
        run = Run(sid, sealed)
        run.tag("-pinned")
        run.delete()

    assert not run_dir.exists()
    assert [entry.rel_dir for entry in list_trash(project)] == ["runs/monthly"]


def test_a_long_vector_layer_name_lists_back_whole(tmp_path: Path, no_index) -> None:
    """The listing reads the name from the file name: it is not cut to 32 characters."""
    import geopandas as gpd
    from shapely.geometry import LineString

    name = "hydrographic_network_reference_permanent"
    layer = gpd.GeoDataFrame(geometry=[LineString([(0.0, 0.0), (1.0, 0.0)])], crs="EPSG:2154")
    with open_run_store(tmp_path / "p", "layers") as store:
        store.write_geographic_feature(store.sim_id, name, layer)

        assert store.list_geographic_features(store.sim_id) == [name]
        assert len(Run(store.sim_id, store).hydrographic_network("reference_permanent")) == 1


# ``run.periods.edges`` rebuilds the edges from the catalog ``period_start`` and
# the end stamps of ``Run.time_index``; ``run.periods.step_at`` and
# ``run.periods.steps_for`` read a date through ``core.time.selection``.
class _NoZarrCatalog:
    """A catalog without a solver ``/time`` axis: the stamps come from the bounds."""


class _TimeAxisCatalog:
    """A catalog whose store carries the solver ``/time`` axis."""

    def __init__(self, stamps: pd.DatetimeIndex) -> None:
        self._stamps = stamps

    @contextmanager
    def open_zarr(self, sim_id: str):
        class _Store:
            def read_time(inner) -> np.ndarray:
                return self._stamps.to_numpy()

        yield _Store()


class _Run(RunTimeseriesMixin):
    def __init__(self, row: dict, catalog: object | None = None) -> None:
        self._sim_id = "sim"
        self._row = row
        self._catalog = catalog if catalog is not None else _NoZarrCatalog()
        self.periods = RunPeriods(self)

    def _load_row(self) -> dict:
        return self._row


def _monthly() -> _Run:
    return _Run(
        {
            "n_timesteps": 36,
            "period_start": "2000-01-01 00:00:00",
            "period_end": "2003-01-01 00:00:00",
            "time_unit": "month",
            "flow_regime": "transient",
        }
    )


def _steady_window() -> _Run:
    # What a steady calibration phase registers: one period over the window.
    return _Run(
        {
            "n_timesteps": 1,
            "period_start": "2000-01-01 00:00:00",
            "period_end": "2003-01-01 00:00:00",
            "time_unit": "day",
            "flow_regime": "steady",
        }
    )


def test_period_edges_open_at_the_stored_start() -> None:
    edges = _monthly().periods.edges
    assert list(edges) == list(pd.date_range("2000-01-01", "2003-01-01", freq="MS"))


def test_period_edges_follow_the_solver_time_axis() -> None:
    stamps = pd.date_range("2000-01-02", periods=3, freq="D")
    run = _Run(
        {"n_timesteps": 3, "period_start": "2000-01-01", "period_end": "2000-01-04"},
        _TimeAxisCatalog(stamps),
    )
    assert list(run.periods.edges) == list(pd.date_range("2000-01-01", periods=4, freq="D"))
    assert run.periods.step_at("2000-01-02 12:00") == 1


def test_step_at_resolves_a_date_inside_on_and_past_the_edges() -> None:
    run = _monthly()
    assert run.periods.step_at("2002-10-15") == 33
    assert run.periods.step_at("2002-10-01") == 32
    assert run.periods.step_at("2003-01-01") == 35
    assert run.periods.step_at("last") == 35
    assert run.periods.step_at(-2) == 34
    with pytest.raises(TimeSelectionError, match="2000-01-01 to 2003-01-01"):
        run.periods.step_at("2003-02-01")
    with pytest.raises(TimeSelectionError, match="outside the record"):
        run.periods.step_at("1999-12-31")


def test_a_steady_window_resolves_every_date_of_its_record_to_zero() -> None:
    run = _steady_window()
    assert len(run.periods.edges) == 2
    for date in ("2000-01-01", "2001-08-15", "2002-12-31", "2003-01-01", "first", "last"):
        assert run.periods.step_at(date) == 0
    assert run.periods.steps_for(period=("2000-06-01", "2002-06-01")) == (0,)


def test_a_run_without_dates_names_its_one_period_only() -> None:
    run = _Run({"n_timesteps": 1, "period_start": None, "flow_regime": "steady"})
    assert run.periods.edges is None
    assert run.periods.step_at("last") == 0
    assert run.periods.step_at(0) == 0
    assert run.periods.steps_for() == (0,)
    with pytest.raises(TimeSelectionError, match='this run has no dates; write "last"'):
        run.periods.step_at("2002-10-15")


def test_a_run_without_dates_or_count_holds_one_period() -> None:
    run = _Run({"period_start": float("nan")})
    assert run.periods.edges is None
    assert run.periods.step_at("first") == 0


def test_steps_for_times_a_period_or_everything() -> None:
    run = _monthly()
    assert run.periods.steps_for(time=["2002-10-15", "first"]) == (33, 0)
    assert run.periods.steps_for(time="2002-10-15") == (33,)
    assert run.periods.steps_for(period=("2002-10-15", "last")) == (33, 34, 35)
    assert run.periods.steps_for() == tuple(range(36))
    with pytest.raises(ValueError, match="not both"):
        run.periods.steps_for(time="first", period=("first", "last"))


# A run stamps each stress period at its END. A discharge stands for the whole
# period ``[start, stamp)``, so its observations are averaged there. A MODFLOW
# head or a lake stage is the state AT the stamp instant: averaging over the
# period that ends there compares it with a value half a period earlier, the
# very bias the period rule removed for discharge. The field registry already
# says which is which in its CF ``cell_methods``.
#
# The chronicle below is worth its day number, counted from 2000-01-01 = 0, so
# every window mean is the middle of the days it holds.
DAYS_2000 = pd.date_range("2000-01-01", "2000-12-31", freq="D")


DAY_NUMBER = pd.Series(np.arange(len(DAYS_2000), dtype=float), index=DAYS_2000)


# January, February and March of a monthly run, stamped at their ends.
MONTH_ENDS = pd.DatetimeIndex(["2000-02-01", "2000-03-01", "2000-04-01"])


def test_a_monthly_head_on_a_daily_chronicle_takes_the_window_centred_on_its_stamp() -> None:
    # The stamp 2000-03-01 sits 29 days after 02-01 and 31 days before 04-01.
    # Its window reaches halfway to each: [02-15 12:00, 03-16 12:00), the days
    # 16 February to 16 March, day numbers 46 to 75, mean 60.5.
    aligned = observed_on_simulation_index(DAY_NUMBER, MONTH_ENDS, method="point")

    assert aligned.iloc[1] == pytest.approx((46 + 75) / 2)


def test_a_monthly_discharge_on_a_daily_chronicle_takes_the_month_its_stamp_closes() -> None:
    # The stamp 2000-03-01 closes February, [02-01, 03-01): day numbers 31 to
    # 59, mean 45. The head above read 60.5 on the same record: half a month
    # apart, which is what averaging a state over its period would cost.
    aligned = observed_on_simulation_index(DAY_NUMBER, MONTH_ENDS, method="mean")

    assert aligned.iloc[1] == pytest.approx((31 + 59) / 2)


def test_a_lake_stage_at_the_run_frequency_takes_the_reading_at_its_stamp() -> None:
    # Monthly readings taken on the first of each month, as a run stamps.
    readings = pd.Series(
        [1.0, 2.0, 3.0, 4.0, 5.0], index=pd.date_range("2000-01-01", periods=5, freq="MS")
    )

    stage = observed_on_simulation_index(readings, MONTH_ENDS, method=time_method_for("stage"))
    as_a_flux = observed_on_simulation_index(readings, MONTH_ENDS, method="mean")

    # The stage at 03-01 is the reading of 03-01. The period mean would hand it
    # the reading of 02-01, a month early.
    assert stage.tolist() == [2.0, 3.0, 4.0]
    assert as_a_flux.tolist() == [1.0, 2.0, 3.0]


def test_a_state_reads_the_nearest_sample_within_one_run_step_and_no_further() -> None:
    readings = pd.Series([10.0, 20.0], index=pd.DatetimeIndex(["2000-01-01", "2000-01-05"]))
    stamps = pd.date_range("2000-01-01", periods=3, freq="D")

    aligned = observed_on_simulation_index(readings, stamps, method="point")

    # 01-02 is one day from 01-01, within one run step; 01-03 is two days from
    # both readings, beyond it.
    assert aligned.iloc[:2].tolist() == [10.0, 10.0]
    assert np.isnan(aligned.iloc[2])


def test_a_tie_between_two_readings_goes_to_the_earlier_one() -> None:
    # A daily state stamped at midnight between two noon readings.
    readings = pd.Series(
        [1.0, 2.0], index=pd.DatetimeIndex(["2000-01-01 12:00", "2000-01-02 12:00"])
    )

    aligned = observed_on_simulation_index(
        readings, pd.DatetimeIndex(["2000-01-02", "2000-01-03"]), method="point"
    )

    assert aligned.tolist() == [1.0, 2.0]


def test_a_state_on_millisecond_parquet_stamps_is_read_without_a_merge() -> None:
    # The nearest-sample branch used pandas.merge_asof, which refused to join
    # millisecond stamps with nanosecond ones.
    readings = pd.Series([1.0, 2.0, 3.0], index=pd.date_range("2000-01-01", periods=3, freq="D"))
    simulated = pd.Series(
        [1.5, 2.5, 3.5], index=pd.date_range("2000-01-01", periods=3, freq="D").as_unit("ms")
    )

    paired = align_observed_simulated(readings, simulated, method="point")

    assert paired["obs"].tolist() == [1.0, 2.0, 3.0]


def test_one_steady_discharge_period_with_its_start_takes_its_own_window() -> None:
    index = pd.date_range("1999-01-01", "2001-12-31", freq="D")
    record = pd.Series(index.year.astype("float64"), index=index)

    aligned = observed_on_simulation_index(
        record, pd.DatetimeIndex(["2001-01-01"]), method="mean", start="2000-01-01"
    )

    assert aligned.tolist() == [2000.0]


def test_one_steady_discharge_period_without_a_start_takes_the_whole_chronicle() -> None:
    # 365 days of 1999, 366 of 2000, 365 of 2001. The last day before the stamp,
    # 2000.0, would be one day scored as a steady stage.
    index = pd.date_range("1999-01-01", "2001-12-31", freq="D")
    record = pd.Series(index.year.astype("float64"), index=index)

    aligned = observed_on_simulation_index(record, pd.DatetimeIndex(["2001-01-01"]), method="mean")

    assert aligned.tolist() == [pytest.approx((1999 * 365 + 2000 * 366 + 2001 * 365) / 1096)]


def test_the_start_of_a_series_is_the_grid_bound_just_before_its_first_stamp() -> None:
    bounds = pd.date_range("2000-01-01", periods=4, freq="MS")

    assert first_period_start(pd.DatetimeIndex(["2000-02-01"]), bounds) == bounds[0]
    assert first_period_start(pd.DatetimeIndex(["2000-04-01"]), bounds) == bounds[2]
    assert first_period_start(pd.DatetimeIndex(["2000-01-01"]), bounds) is None
    assert first_period_start(pd.DatetimeIndex(["2000-02-01"]), None) is None


@pytest.mark.parametrize("name", sorted(FIELD_REGISTRY))
def test_every_registry_field_aligns_by_its_cell_methods(name: str) -> None:
    cell_methods = FIELD_REGISTRY[name].cell_methods
    if "time: point" in cell_methods:
        expected = "point"
    elif "time:" in cell_methods:
        expected = "mean"
    else:
        # No time entry: a static field, whose value holds at every instant.
        expected = "point"

    assert time_method_for(name) == expected


def test_the_registry_states_and_fluxes_are_the_ones_expected() -> None:
    states = {"head", "watertable_elevation", "watertable_depth", "concentration"}
    fluxes = {"drain", "surface_excess", "recharge", "release_flux", "outflow_drain"}

    assert {time_method_for(name) for name in states} == {"point"}
    assert {time_method_for(name) for name in fluxes} == {"mean"}


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("discharge", "mean"),
        ("outlet_discharge", "mean"),
        ("discharge_obs", "mean"),
        ("lake_level", "point"),
        ("stage", "point"),
        ("volume", "point"),
        ("surface_area", "point"),
        ("groundwater_level", "point"),
        ("an_unknown_name", "mean"),
        (None, "mean"),
    ],
)
def test_the_calibration_variables_have_an_explicit_method(name, expected: str) -> None:
    assert time_method_for(name) == expected


def test_the_core_table_never_contradicts_the_registry() -> None:
    # ``core.time`` reads the core table because it may not read the
    # registry; a name in both has to answer the same.
    shared = sorted(set(OBSERVABLE_TIME_METHODS) & set(FIELD_REGISTRY))

    assert shared
    assert {name: OBSERVABLE_TIME_METHODS[name] for name in shared} == {
        name: time_method_for(name) for name in shared
    }


def test_an_unknown_method_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown time method"):
        observed_on_simulation_index(DAY_NUMBER, MONTH_ENDS, method="median")


# Seven static arrays, never rounded, plus the build report on the receiver array
# and, when the build kept one, the basin of D with its outlet.
# The layout is additive: ``zarr_schema_version`` stays where it was, and a run
# sealed before D was stored gets one rebuilt from its stored top, announced once.
NROW_2 = NCOL_2 = 4


N_CELLS_3 = NROW_2 * NCOL_2


TOP_2 = np.array(
    [
        [9.0, 8.0, 7.0, 8.0],
        [8.0, 5.0, 4.0, 7.0],
        [7.0, 4.0, 1.0, 6.0],
        [6.0, 5.0, 4.0, 5.0],
    ]
)


PIT = 10


def _built_descent() -> Descent:
    """D as a build makes it, with a constant head in the pit: no rebuild from the top can."""
    base_level = np.zeros(N_CELLS_3, dtype=bool)
    base_level[PIT] = True
    return grid_descent(TOP_2, base_level=base_level)


def _attrs(descent: Descent) -> dict[str, object]:
    return {
        "adjacency": "shared_nodes",
        "epsilon": 1.0e-4,
        "n_raised": descent.n_raised,
        "max_raise_m": descent.max_raise_m,
        "n_lake_flooded": descent.n_lake_flooded,
        "max_lake_flood_m": descent.max_lake_flood_m,
        "n_pinned_raised": descent.n_pinned_raised,
        "max_pinned_raise_m": descent.max_pinned_raise_m,
    }


def _write(store: SimulationZarr, descent: Descent) -> None:
    store.write_descent(
        receiver=descent.receiver,
        surface=descent.surface,
        base_level=descent.base_level,
        constant_head=descent.constant_head,
        raised=descent.raised,
        channel=descent.channel,
        pinned=descent.pinned,
        attrs=_attrs(descent),
    )


def _write_mesh(store: SimulationZarr) -> tuple[np.ndarray, np.ndarray]:
    vertices, connectivity = quad_mesh(NROW_2, NCOL_2)
    store.write_mesh(vertices, connectivity, np.array([10.0, 0.0]), topography=TOP_2.ravel())
    return vertices, connectivity


@pytest.fixture
def store(tmp_path: Path):
    handle = SimulationZarr.create(tmp_path / "run.zarr", n_cells=N_CELLS_3, n_layers=1)
    yield handle
    handle.close()


def _run_over(store: SimulationZarr, vertices: np.ndarray, connectivity: np.ndarray):
    """A run whose catalog hands out ``store`` and whose mesh is the one written."""
    handle = SimpleNamespace(root=store.root, close=lambda: None)
    return SimpleNamespace(
        sim_id="sim-descent",
        _sim_id="sim-descent",
        _catalog=SimpleNamespace(open_zarr=lambda sim_id: handle),
        mesh=Mesh(
            vertices=vertices,
            face_node_connectivity=connectivity,
            z_interfaces=np.array([10.0, 0.0]),
            topography=TOP_2.ravel(),
        ),
    )


def test_the_seven_arrays_are_written_under_mesh_with_the_report_on_the_receiver(store) -> None:
    descent = _built_descent()
    _write_mesh(store)

    _write(store, descent)

    mesh = store.root["mesh"]
    expected = {
        "descent_receiver": np.int64,
        "descent_surface": np.float64,
        "descent_base_level": np.bool_,
        "descent_constant_head": np.bool_,
        "descent_raised": np.bool_,
        "descent_channel": np.bool_,
        "descent_pinned": np.bool_,
    }
    for name, dtype in expected.items():
        assert mesh[name].dtype == dtype, name
        assert mesh[name].shape == (N_CELLS_3,), name
    attrs = dict(mesh["descent_receiver"].attrs)
    assert attrs["adjacency"] == "shared_nodes"
    assert attrs["n_raised"] == descent.n_raised
    assert attrs["max_raise_m"] == pytest.approx(descent.max_raise_m)


def test_the_filled_surface_is_never_rounded_in_a_compact_store(store) -> None:
    descent = _built_descent()
    _write_mesh(store)

    _write(store, descent)

    np.testing.assert_array_equal(store.root["mesh"]["descent_surface"][:], descent.surface)


def test_storing_the_descent_moves_neither_the_schema_version_nor_the_mesh(store) -> None:
    vertices, _ = _write_mesh(store)
    before = dict(store.root.attrs)["zarr_schema_version"]

    _write(store, _built_descent())

    assert dict(store.root.attrs)["zarr_schema_version"] == before == ZARR_SCHEMA_VERSION
    np.testing.assert_array_equal(store.root["mesh"]["vertices"][:], vertices)
    np.testing.assert_array_equal(store.root["mesh"]["topography"][:], TOP_2.ravel())


def test_a_descent_whose_arrays_disagree_on_the_cell_count_is_refused(store) -> None:
    descent = _built_descent()
    _write_mesh(store)

    with pytest.raises(ValueError, match="share one size"):
        store.write_descent(
            receiver=descent.receiver[:-1],
            surface=descent.surface,
            base_level=descent.base_level,
            constant_head=descent.constant_head,
            raised=descent.raised,
            channel=descent.channel,
            pinned=descent.pinned,
            attrs={},
        )


def test_a_stored_descent_reads_back_and_routes_like_the_one_written(store) -> None:
    descent = _built_descent()
    vertices, connectivity = _write_mesh(store)
    _write(store, descent)

    view = load_descent(_run_over(store, vertices, connectivity))

    assert not view.rebuilt
    assert view.adjacency == "shared_nodes"
    assert view.diagonal_neighbors
    assert view.epsilon == pytest.approx(1.0e-4)
    assert view.report["n_raised"] == descent.n_raised
    np.testing.assert_array_equal(view.receiver, descent.receiver)
    np.testing.assert_array_equal(view.surface, descent.surface)
    np.testing.assert_array_equal(view.base_level, descent.base_level)
    np.testing.assert_array_equal(view.constant_head, descent.constant_head)
    np.testing.assert_array_equal(view.raised, descent.raised)
    assert view.constant_head[PIT] and view.receiver[PIT] == -1
    flux = np.arange(1.0, N_CELLS_3 + 1.0)
    np.testing.assert_array_equal(
        accumulate_on_downhill_graph(view.graph, flux),
        accumulate_on_downhill_graph(descent.metric.graph, flux),
    )


def test_the_arrays_of_the_view_are_read_only(store) -> None:
    vertices, connectivity = _write_mesh(store)
    _write(store, _built_descent())

    view = load_descent(_run_over(store, vertices, connectivity))

    for name in (
        "receiver",
        "surface",
        "base_level",
        "constant_head",
        "raised",
        "channel",
        "pinned",
    ):
        assert not getattr(view, name).flags.writeable, name


def test_a_run_sealed_before_the_descent_rebuilds_it_from_its_top(store) -> None:
    vertices, connectivity = _write_mesh(store)

    view = load_descent(_run_over(store, vertices, connectivity))

    rebuilt = descent_from_stored_mesh(TOP_2.ravel(), connectivity, vertices)
    assert view.rebuilt
    assert not view.channel.any()
    assert not view.pinned.any()
    np.testing.assert_array_equal(view.receiver, rebuilt.receiver)
    np.testing.assert_array_equal(view.surface, rebuilt.surface)


def test_an_old_run_says_once_that_it_rebuilt_its_descent(store, caplog) -> None:
    vertices, connectivity = _write_mesh(store)
    holder = RunDescent.of_run(_run_over(store, vertices, connectivity))

    with caplog.at_level(logging.INFO):
        for name in ("receiver", "surface", "graph"):
            assert getattr(holder, name) is not None

    lines = [r for r in caplog.records if "predates the stored descent" in r.getMessage()]
    assert len(lines) == 1
    assert lines[0].levelno == logging.INFO


def test_a_stored_descent_is_loaded_lazily_and_once(store) -> None:
    descent = _built_descent()
    vertices, connectivity = _write_mesh(store)
    _write(store, descent)
    opened: list[str] = []
    run = _run_over(store, vertices, connectivity)
    handle = run._catalog.open_zarr("x")
    run._catalog.open_zarr = lambda sim_id: opened.append(sim_id) or handle
    holder = RunDescent.of_run(run)
    assert opened == []

    for name in ("receiver", "graph"):
        assert getattr(holder, name) is not None

    assert opened == ["sim-descent"]


def test_an_attribute_the_view_does_not_have_is_an_attribute_error() -> None:
    holder = RunDescent(lambda: pytest.fail("loading must not happen for an unknown name"))

    with pytest.raises(AttributeError):
        getattr(holder, "nothing_of_the_kind")  # noqa: B009


BASIN_CELLS = [5, 6, 9, 10]


BASIN_OUTLET = PIT


def _basin_mask() -> np.ndarray:
    mask = np.zeros(N_CELLS_3, dtype=bool)
    mask[BASIN_CELLS] = True
    return mask


def _basin_attrs(**changes: object) -> dict[str, object]:
    attrs: dict[str, object] = {
        "descent_outlet": BASIN_OUTLET,
        "basin_rule": "within_polygon",
        "basin_area_m2": 4.0,
        "basin_seeded_at_outlet": True,
        "basin_version": 1,
    }
    return {**attrs, **changes}


def _write_with_basin(store: SimulationZarr, mask: np.ndarray, attrs: dict[str, object]) -> None:
    descent = _built_descent()
    store.write_descent(
        receiver=descent.receiver,
        surface=descent.surface,
        base_level=descent.base_level,
        constant_head=descent.constant_head,
        raised=descent.raised,
        channel=descent.channel,
        pinned=descent.pinned,
        attrs=_attrs(descent),
        basin=mask,
        basin_attrs=attrs,
    )


def test_the_basin_is_a_bool_array_per_face_with_its_outlet_on_it(store) -> None:
    _write_mesh(store)

    _write_with_basin(store, _basin_mask(), _basin_attrs())

    array = store.root["mesh"]["descent_basin"]
    assert array.dtype == np.bool_
    assert array.shape == (N_CELLS_3,)
    assert np.flatnonzero(array[:]).tolist() == BASIN_CELLS
    attrs = dict(array.attrs)
    assert attrs["descent_outlet"] == BASIN_OUTLET
    assert attrs["basin_rule"] == "within_polygon"
    assert attrs["basin_area_m2"] == pytest.approx(4.0)
    assert attrs["basin_seeded_at_outlet"] is True
    assert attrs["basin_version"] == 1


def test_a_stored_basin_reads_back_read_only_with_its_attributes(store) -> None:
    vertices, connectivity = _write_mesh(store)
    _write_with_basin(store, _basin_mask(), _basin_attrs())

    view = load_descent(_run_over(store, vertices, connectivity))

    assert not view.rebuilt
    np.testing.assert_array_equal(view.basin, _basin_mask())
    assert not view.basin.flags.writeable
    assert view.basin_attrs == _basin_attrs()


def test_the_basin_is_read_alone_without_loading_or_rebuilding_d(store, monkeypatch) -> None:
    vertices, connectivity = _write_mesh(store)
    _write_with_basin(store, _basin_mask(), _basin_attrs())
    from hydromodpy.results.run import descent as module

    def refuse(*args, **kwargs):
        raise AssertionError("D must be neither loaded nor rebuilt to read the basin")

    for name in ("load_descent", "_rebuild", "_read_stored"):
        monkeypatch.setattr(module, name, refuse)

    basin = read_basin(_run_over(store, vertices, connectivity))

    np.testing.assert_array_equal(basin.mask, _basin_mask())
    assert not basin.mask.flags.writeable
    assert basin.attrs["descent_outlet"] == BASIN_OUTLET


def test_the_holder_reads_the_basin_alone_and_a_run_without_one_is_not_rebuilt(
    store, monkeypatch
) -> None:
    vertices, connectivity = _write_mesh(store)
    run = _run_over(store, vertices, connectivity)
    from hydromodpy.results.run import descent as module

    def refuse(*args, **kwargs):
        raise AssertionError("D must be neither loaded nor rebuilt to read the basin")

    for name in ("load_descent", "_rebuild", "_read_stored"):
        monkeypatch.setattr(module, name, refuse)
    holder = RunDescent.of_run(run)

    assert holder.stored_basin() is None

    _write_with_basin(store, _basin_mask(), _basin_attrs())
    holder = RunDescent.of_run(run)
    basin = holder.stored_basin()
    np.testing.assert_array_equal(basin.mask, _basin_mask())
    assert basin.attrs["descent_outlet"] == BASIN_OUTLET


def test_a_descent_stored_before_the_basin_reads_back_without_one(store) -> None:
    vertices, connectivity = _write_mesh(store)
    _write(store, _built_descent())
    run = _run_over(store, vertices, connectivity)

    view = load_descent(run)

    assert not view.rebuilt
    assert view.basin is None
    assert view.basin_attrs == {}
    assert read_basin(run) is None


def test_a_rebuilt_descent_has_no_basin(store) -> None:
    vertices, connectivity = _write_mesh(store)

    view = load_descent(_run_over(store, vertices, connectivity))

    assert view.rebuilt
    assert view.basin is None


@pytest.mark.parametrize(
    ("mask", "attrs", "message"),
    [
        (_basin_mask()[:-1], _basin_attrs(), "one value per cell"),
        (_basin_mask(), {}, "descent_outlet"),
        (_basin_mask(), _basin_attrs(descent_outlet=0), "not a cell of the basin"),
        (_basin_mask(), _basin_attrs(descent_outlet=N_CELLS_3), "not a cell of the basin"),
    ],
    ids=["wrong size", "no outlet", "outlet off the basin", "outlet off the mesh"],
)
def test_a_basin_that_does_not_fit_d_is_refused(store, mask, attrs, message) -> None:
    _write_mesh(store)

    with pytest.raises(ValueError, match=message):
        _write_with_basin(store, mask, attrs)

    assert "descent_basin" not in store.root["mesh"]


def test_attributes_without_a_basin_are_refused(store) -> None:
    descent = _built_descent()

    with pytest.raises(ValueError, match="without a basin"):
        store.write_descent(
            receiver=descent.receiver,
            surface=descent.surface,
            base_level=descent.base_level,
            constant_head=descent.constant_head,
            raised=descent.raised,
            channel=descent.channel,
            pinned=descent.pinned,
            attrs={},
            basin_attrs=_basin_attrs(),
        )


def test_storing_the_basin_moves_neither_the_schema_version_nor_the_other_arrays(store) -> None:
    _write_mesh(store)
    before = dict(store.root.attrs)["zarr_schema_version"]

    _write_with_basin(store, _basin_mask(), _basin_attrs())

    assert dict(store.root.attrs)["zarr_schema_version"] == before == ZARR_SCHEMA_VERSION
    np.testing.assert_array_equal(
        store.root["mesh"]["descent_receiver"][:], _built_descent().receiver
    )


# ``catchment_mean`` weighs each face by its area inside the delineated catchment.
# ``saturated_fraction`` and ``recharge_forcing`` do not say catchment, so they keep
# the active cells of the model domain, the cells with a finite model top, whatever
# the basin is. The drainage density and the metrics of an active cell field carry
# the catchment: their cells are the active faces of the basin of D, whole, and
# every share is taken over them. ``catchment_cell_count`` is their number.
NROW, NCOL = 2, 3


# Cell 5 has no model top: it is outside the active domain.
TOPOGRAPHY = np.array([10.0, 11.0, 12.0, 10.5, 11.5, np.nan])


ACTIVE = np.isfinite(TOPOGRAPHY)


# Columns 10, 10 and 30 m wide, 10 m high: faces of 100, 100 and 300 m2.
AREAS_2 = np.array([100.0, 100.0, 300.0, 100.0, 100.0, 300.0])


DEPTH = np.array(
    [
        [1.0, 2.0, 4.0, 3.0, 5.0, 9.0],
        [2.0, 2.0, 6.0, 1.0, 3.0, 9.0],
    ]
)


SEEPAGE = np.array([[1, 0, 0, 1, 1, 1], [0, 0, 1, 1, 0, 0]], dtype=float)


RECHARGE_2 = np.array([[1.0, 2.0, 3.0, 4.0, 5.0, 6.0], [2.0, 2.0, 2.0, 2.0, 8.0, 6.0]])


STAMPS_2 = pd.to_datetime(["1970-01-02", "1970-01-03"])


def _mesh() -> tuple[np.ndarray, np.ndarray]:
    vertices, connectivity = quad_mesh(NROW, NCOL, cell_size=10.0)
    vertices[:, 0] = np.where(vertices[:, 0] == 30.0, 50.0, vertices[:, 0])
    return vertices, connectivity


def _run(tmp_path, *, fraction: np.ndarray | None = FRACTION, rule: str | None = "near_point"):
    path = tmp_path / "run.zarr"
    store = SimulationZarr.create(path, n_cells=N_CELLS, n_layers=1)
    vertices, connectivity = _mesh()
    try:
        store.write_mesh(
            vertices, connectivity, np.array([0.0, -10.0]), topography=TOPOGRAPHY, grid_type="disv"
        )
        store.write_time(np.array([86400.0, 2 * 86400.0]))
        store.write_field_stack(
            "watertable_depth", DEPTH[:, None, :], n_timesteps=2, subgroup="derived"
        )
        store.write_field_stack(
            "recharge", RECHARGE_2[:, None, :], n_timesteps=2, timestep_offset=0, subgroup="budget"
        )
        if rule is not None:
            store.write_descent(
                receiver=np.full(N_CELLS, -1, dtype=np.int64),
                surface=np.zeros(N_CELLS),
                base_level=np.zeros(N_CELLS, dtype=bool),
                constant_head=np.zeros(N_CELLS, dtype=bool),
                raised=np.zeros(N_CELLS, dtype=bool),
                channel=np.zeros(N_CELLS, dtype=bool),
                pinned=np.zeros(N_CELLS, dtype=bool),
                attrs={"adjacency": "shared_nodes"},
                basin=BASIN,
                basin_attrs={"descent_outlet": 0, "basin_rule": rule},
                catchment_fraction=fraction,
            )
    finally:
        store.close()
    return SimpleNamespace(
        sim_id="sim-view",
        _sim_id="sim-view",
        n_timesteps=2,
        mesh=Mesh(
            vertices=vertices, face_node_connectivity=connectivity, z_interfaces=np.zeros((2, 6))
        ),
        _catalog=SimpleNamespace(open_zarr=lambda sim_id: SimulationZarr(path)),
    )


def _weighted_mean(stack: np.ndarray, weights: np.ndarray) -> np.ndarray:
    finite = np.isfinite(stack)
    return (np.where(finite, stack, 0.0) @ weights) / (finite @ weights)


def test_the_catchment_mean_weighs_each_face_by_its_area_in_the_catchment(tmp_path) -> None:
    run = _run(tmp_path)

    mean = views.catchment_mean(run, "watertable_depth")

    np.testing.assert_allclose(mean.to_numpy(), _weighted_mean(DEPTH, FRACTION * AREAS_2))
    assert list(mean.index) == list(STAMPS_2)
    assert mean.name == "watertable_depth"


def test_the_catchment_mean_is_no_longer_the_mean_of_the_active_domain(tmp_path) -> None:
    run = _run(tmp_path)

    mean = views.catchment_mean(run, "watertable_depth", name="depth")

    over_the_domain = DEPTH[:, ACTIVE].mean(axis=1)
    assert not np.allclose(mean.to_numpy(), over_the_domain)
    assert mean.name == "depth"


def test_a_face_without_a_value_leaves_the_sum_and_the_weights(tmp_path, monkeypatch) -> None:
    run = _run(tmp_path)
    holes = DEPTH.copy()
    holes[0, 1] = np.nan
    monkeypatch.setattr(views, "_stack_field", lambda sim, variable: holes)

    mean = views.catchment_mean(run, "watertable_depth")

    np.testing.assert_allclose(mean.to_numpy(), _weighted_mean(holes, FRACTION * AREAS_2))
    assert np.isfinite(mean.to_numpy()).all()


def test_a_run_without_a_fraction_counts_the_basin_whole_2(tmp_path) -> None:
    run = _run(tmp_path, fraction=None)

    mean = views.catchment_mean(run, "watertable_depth")

    np.testing.assert_allclose(mean.to_numpy(), _weighted_mean(DEPTH, BASIN * AREAS_2))


@pytest.mark.parametrize("rule", ["largest_basin", None], ids=["synthetic_domain", "no_basin"])
def test_a_run_with_no_catchment_has_no_catchment_mean(tmp_path, rule) -> None:
    run = _run(tmp_path, rule=rule, fraction=None)

    with pytest.raises(ValueError, match="stores no catchment"):
        views.catchment_mean(run, "watertable_depth")


def test_the_saturated_fraction_counts_the_cells_of_the_active_domain(
    tmp_path, monkeypatch
) -> None:
    run = _run(tmp_path)
    monkeypatch.setattr(views, "_stack_field", lambda sim, variable: SEEPAGE)

    series = views.saturated_fraction(run)

    # Cell 5 has no top, so five cells count: three then two are saturated.
    np.testing.assert_allclose(series.to_numpy(), [60.0, 40.0])
    over_the_basin = 100.0 * (SEEPAGE[:, BASIN] > 0).mean(axis=1)
    assert not np.allclose(series.to_numpy(), over_the_basin)
    assert list(series.index) == list(STAMPS_2)


def test_the_drainage_density_counts_the_cells_of_the_basin(tmp_path, monkeypatch) -> None:
    run = _run(tmp_path)
    monkeypatch.setattr(views, "_stack_field", lambda sim, variable: SEEPAGE)

    series = views.drainage_density(run)

    # The basin holds cells 0, 1, 3 and 4: three then one are above the threshold.
    np.testing.assert_allclose(series.to_numpy(), [75.0, 25.0])
    over_the_domain = 100.0 * (SEEPAGE[:, ACTIVE] > 0).mean(axis=1)
    assert not np.allclose(series.to_numpy(), over_the_domain)
    assert list(series.index) == list(STAMPS_2)


def test_the_drainage_density_and_the_metrics_read_the_same_cells(tmp_path, monkeypatch) -> None:
    run = _run(tmp_path)
    monkeypatch.setattr(views, "_stack_field", lambda sim, variable: SEEPAGE)

    series = views.drainage_density(run)
    metrics = views.cell_field_active_metrics(run)

    assert metrics["catchment_cell_count"] == 4
    assert metrics["drainage_density_mean_pct"] == pytest.approx(series.mean())
    assert metrics["drainage_density_max_pct"] == pytest.approx(series.max())
    assert metrics["drainage_density_last_pct"] == pytest.approx(series.iloc[-1])


def test_a_run_with_no_catchment_reads_the_active_domain_for_its_drainage_density(
    tmp_path, monkeypatch, caplog
) -> None:
    run = _run(tmp_path, rule=None, fraction=None)
    monkeypatch.setattr(views, "_stack_field", lambda sim, variable: SEEPAGE)

    with caplog.at_level(logging.INFO):
        series = views.drainage_density(run)

    np.testing.assert_allclose(series.to_numpy(), [60.0, 40.0])
    assert "stores no catchment" in caplog.text


def test_the_recharge_forcing_is_the_mean_over_the_active_domain(tmp_path) -> None:
    run = _run(tmp_path)

    series = views.recharge_forcing(run)

    np.testing.assert_allclose(series.to_numpy(), RECHARGE_2[:, ACTIVE].mean(axis=1))
    assert not np.allclose(series.to_numpy(), RECHARGE_2[:, BASIN].mean(axis=1))


def test_the_support_of_each_view_is_in_its_docstring() -> None:
    for view in (views.saturated_fraction, views.recharge_forcing):
        assert "model domain" in (view.__doc__ or ""), view.__name__
        assert "not the catchment" in (view.__doc__ or ""), view.__name__
    assert "basin of D" in (views.drainage_density.__doc__ or "")
    assert "inside the delineated catchment" in (views.catchment_mean.__doc__ or "")


# An active cell is a depth above 1.5 m: cells 1 to 4 then cells 0, 1, 2 and 4.
THRESHOLD = 1.5


def _overlap(run, monkeypatch, network: np.ndarray) -> dict:
    run.hydrographic_network = lambda role: SimpleNamespace()
    monkeypatch.setattr(views, "_network_cells", lambda *args, **kwargs: network)
    monkeypatch.setattr(views, "_network_geometries", lambda *args, **kwargs: [])
    return views.cell_field_network_overlap_metrics(
        run, variable="watertable_depth", threshold=THRESHOLD, mode="last"
    )


def test_the_catchment_cell_count_is_the_active_faces_of_the_basin(tmp_path) -> None:
    run = _run(tmp_path)

    metrics = views.cell_field_active_metrics(run, variable="watertable_depth", threshold=THRESHOLD)

    assert metrics["catchment_cell_count"] == int((BASIN & ACTIVE).sum()) == 4
    assert metrics["catchment_cell_count"] != int(ACTIVE.sum())


def test_every_share_of_the_active_metrics_is_taken_over_the_basin(tmp_path) -> None:
    run = _run(tmp_path)

    metrics = views.cell_field_active_metrics(run, variable="watertable_depth", threshold=THRESHOLD)

    # Cells 0, 1, 3, 4 hold the depths 1 2 3 5 then 2 2 1 3: three are active at each step.
    assert metrics["active_cell_count_mean"] == pytest.approx(3.0)
    assert metrics["drainage_density_mean_pct"] == pytest.approx(75.0)
    assert metrics["always_active_ratio"] == pytest.approx(0.5)
    assert metrics["persistent_ratio"] == pytest.approx(1.0)


def test_the_overlap_metrics_read_the_cells_of_the_basin(tmp_path, monkeypatch) -> None:
    run = _run(tmp_path)
    network = np.array([False, True, True, True, False, True])

    metrics = _overlap(run, monkeypatch, network)

    # On the basin the active cells are 0, 1, 4 and the network cells 1, 3.
    assert metrics["catchment_cell_count"] == 4
    assert metrics["active_cell_count"] == 3
    assert metrics["network_cell_count"] == 2
    assert metrics["overlap_cell_count"] == 1
    assert metrics["active_precision_ratio"] == pytest.approx(1.0 / 3.0)
    assert metrics["network_coverage_ratio"] == pytest.approx(0.5)


def test_the_active_mask_keeps_the_active_domain(tmp_path) -> None:
    run = _run(tmp_path)

    mask = views.cell_field_active_mask(
        run, variable="watertable_depth", threshold=THRESHOLD, mode="last"
    )

    np.testing.assert_array_equal(np.isfinite(mask), ACTIVE)


def test_a_run_with_no_catchment_counts_its_active_domain_and_says_so(tmp_path, caplog) -> None:
    run = _run(tmp_path, rule=None, fraction=None)

    with caplog.at_level(logging.INFO):
        metrics = views.cell_field_active_metrics(
            run, variable="watertable_depth", threshold=THRESHOLD
        )

    assert metrics["catchment_cell_count"] == int(ACTIVE.sum())
    assert "stores no catchment" in caplog.text


def test_a_synthetic_domain_counts_its_active_domain(tmp_path) -> None:
    run = _run(tmp_path, rule="largest_basin", fraction=None)

    metrics = views.cell_field_active_metrics(run, variable="watertable_depth", threshold=THRESHOLD)

    assert metrics["catchment_cell_count"] == int(ACTIVE.sum())


# An eighth array beside the seven of D: int64 cell ids, possibly none, additive.
# A store written before it (D without it) reads as having no dam foot and is not
# rebuilt, and a foot outside the mesh is refused.
TOP_3 = np.array([[5.0, 4.0, 3.0], [4.0, 1.0, 2.0], [6.0, 5.0, 4.0]])


N_CELLS_4 = TOP_3.size


@pytest.fixture
def store_2(tmp_path: Path):
    handle = SimulationZarr.create(tmp_path / "run.zarr", n_cells=N_CELLS_4, n_layers=1)
    vertices, connectivity = quad_mesh(3, 3)
    handle.write_mesh(vertices, connectivity, np.array([10.0, 0.0]), topography=TOP_3.ravel())
    yield handle
    handle.close()


def _write_2(store_2: SimulationZarr, dam_foot) -> None:
    descent = grid_descent(TOP_3)
    kwargs = {} if dam_foot is None else {"dam_foot": dam_foot}
    store_2.write_descent(
        receiver=descent.receiver,
        surface=descent.surface,
        base_level=descent.base_level,
        constant_head=descent.constant_head,
        raised=descent.raised,
        channel=descent.channel,
        pinned=descent.pinned,
        attrs={"adjacency": "shared_nodes", "epsilon": 1.0e-4},
        **kwargs,
    )


def _run_over_2(store_2: SimulationZarr):
    vertices, connectivity = quad_mesh(3, 3)
    handle = SimpleNamespace(root=store_2.root, close=lambda: None)
    return SimpleNamespace(
        sim_id="sim-dam",
        _sim_id="sim-dam",
        _catalog=SimpleNamespace(open_zarr=lambda sim_id: handle),
        mesh=Mesh(
            vertices=vertices,
            face_node_connectivity=connectivity,
            z_interfaces=np.array([10.0, 0.0]),
            topography=TOP_3.ravel(),
        ),
    )


def test_the_feet_are_stored_as_sorted_int64_cell_ids(store_2) -> None:
    _write_2(store_2, [7, 2, 7])

    array = store_2.root["mesh"]["descent_dam_foot"]
    assert array.dtype == np.int64
    assert array[:].tolist() == [2, 7]


def test_a_run_without_a_lake_stores_an_empty_array(store_2) -> None:
    _write_2(store_2, None)

    assert store_2.root["mesh"]["descent_dam_foot"].shape == (0,)
    assert not load_descent(_run_over_2(store_2)).dam_foot.size


def test_the_view_reads_the_feet_back_read_only(store_2) -> None:
    _write_2(store_2, [2, 7])

    view = load_descent(_run_over_2(store_2))

    assert not view.rebuilt
    assert view.dam_foot.tolist() == [2, 7]
    assert not view.dam_foot.flags.writeable


def test_a_store_written_before_the_feet_has_none_and_is_not_rebuilt(store_2) -> None:
    _write_2(store_2, None)
    del store_2.root["mesh"]["descent_dam_foot"]

    view = load_descent(_run_over_2(store_2))

    assert not view.rebuilt
    assert view.dam_foot.size == 0


def test_a_foot_outside_the_mesh_is_refused(store_2) -> None:
    with pytest.raises(ValueError, match="not a cell of the mesh"):
        _write_2(store_2, [N_CELLS_4])


def test_storing_the_feet_does_not_move_the_schema_version(store_2) -> None:
    before = dict(store_2.root.attrs)["zarr_schema_version"]

    _write_2(store_2, [2])

    assert dict(store_2.root.attrs)["zarr_schema_version"] == before == ZARR_SCHEMA_VERSION


def test_the_extractor_copies_the_feet_of_the_sidecar(store_2, tmp_path) -> None:
    write_descent_sidecar(grid_descent(TOP_3), tmp_path, "model", dam_foot_cells={"lake": 5})

    written = write_descent_sidecar_to_store(store_2, tmp_path, sim_id="s", n_cells=N_CELLS_4)

    assert written
    assert load_descent(_run_over_2(store_2)).dam_foot.tolist() == [5]


def _forbid_loading_d(monkeypatch) -> None:
    from hydromodpy.results.run import descent as module

    def refuse(*args, **kwargs):
        raise AssertionError("D must be neither loaded nor rebuilt to read the dam foot")

    monkeypatch.setattr(module, "load_descent", refuse)
    monkeypatch.setattr(module, "_rebuild", refuse)
    monkeypatch.setattr(module, "_read_stored", refuse)


def test_the_redraw_reads_the_stored_feet_without_loading_d(store_2, monkeypatch) -> None:
    _write_2(store_2, [2, 7])
    _forbid_loading_d(monkeypatch)

    feet = RunDescent.of_run(_run_over_2(store_2)).dam_foot

    assert feet.tolist() == [2, 7]
    assert not feet.flags.writeable


def test_an_old_store_has_no_feet_and_the_redraw_does_not_rebuild_d(
    store_2, monkeypatch, caplog
) -> None:
    # No descent_* array at all: a run sealed before D was stored.
    _forbid_loading_d(monkeypatch)

    with caplog.at_level("INFO"):
        feet = RunDescent.of_run(_run_over_2(store_2)).dam_foot

    assert feet.size == 0
    assert "predates the stored descent" not in caplog.text


# A configuration without a ``[mesh]`` section ran on the default engine of its
# release; the frozen ``config.toml`` then has no ``mesh`` key, but the seal
# (``geometry.mesh_engine``) says which engine built the mesh. The index reads
# the seal, so ``hmp catalog ls`` and every listing show it.
def test_a_config_without_a_mesh_section_lists_the_engine_of_its_seal(tmp_path: Path) -> None:
    root = make_project(tmp_path / "demo")
    seal_run(root, "plain", mesh_engine="regular", config_text="[flow]\nK = 1e-5\n")
    seal_run(root, "cells", mesh_engine="voronoi", config_text='[mesh]\nengine = "voronoi"\n')

    rebuild_index(root)

    with Catalog(root) as catalog:
        listed = catalog.list_simulations()
        filtered = catalog.list_simulations(mesh_engine="regular")
    engines = dict(zip(listed["name"], listed["mesh_engine"], strict=True))
    assert engines == {"plain": "regular", "cells": "voronoi"}
    assert list(filtered["name"]) == ["plain"]


# A session states one of three stop states. Its README and its HTML report say
# it in words, with the phases that froze the best of a budget-only search. The
# README of the promoted run says it beside the session that promoted it. The
# stop state does not enter the label: ``failed`` stays the label of a fiction
# (a fatal validity, a solver that did not converge). A run promoted by a
# budget-only search, whose session closes ``completed``, stays ``calibrated``,
# and one promoted by a search stopped before its rule, whose session closes
# ``partial``, stays ``exploratory``, so the rules keep their version.
def _descriptor(**extra) -> SessionDescriptor:
    return session_descriptor(
        "J0014010-calage",
        session_id="sess0001",
        method="random_search + grid",
        cost_name="nse_log",
        status="completed",
        started_at=datetime(2026, 10, 25, tzinfo=UTC),
        **extra,
    )


def test_the_session_readme_says_why_each_search_stopped() -> None:
    descriptor = _descriptor(
        stop_state="plan_exhausted",
        stopping_rule="every grid point",
        stop_note=f"phase coarse {FROZE_BUDGET_ONLY}",
    )
    phases = [
        PhaseDescriptor(
            phase_id="p1",
            name="coarse",
            index=0,
            status="completed",
            stop_state="budget_spent",
            stopping_rule=BUDGET_RULE,
            stop_note=FROZE_BUDGET_ONLY,
        ),
        PhaseDescriptor(
            phase_id="p2",
            name="storage",
            index=1,
            status="completed",
            stop_state="plan_exhausted",
            stopping_rule="every grid point",
        ),
    ]

    text = render_session_readme(descriptor, [], None, phases=phases)

    assert "- search stopped: exhausted its plan (every grid point solved), converged" in text
    assert f"- phase coarse {FROZE_BUDGET_ONLY}" in text
    assert (
        "| coarse | completed | 0 | none | none | spent its budget, a budget-only search with "
        f"no rule of its own; {FROZE_BUDGET_ONLY} |"
    ) in text
    assert (
        "| storage | completed | 0 | none | none | exhausted its plan (every grid point solved) |"
        in (text)
    )


def test_an_older_session_says_its_stop_was_not_recorded() -> None:
    text = render_session_readme(_descriptor(), [], None)

    assert "- search stopped: not recorded" in text


def test_the_run_readme_says_why_the_search_that_promoted_it_stopped() -> None:
    checks = make_checks(
        calibrated_by=CalibratedBy(
            session_id="sess0001",
            phase="storage",
            trial=7,
            session_status="completed",
            stop_state="budget_spent",
            stopping_rule=BUDGET_RULE,
        )
    )

    lines = _checks_section(checks)

    assert (
        "- its search spent its budget, a budget-only search with no rule of its own, not converged"
    ) in lines


def test_the_html_report_says_why_the_search_stopped(tmp_path: Path) -> None:
    directory = tmp_path / "sessions" / "J0014010-calage"
    directory.mkdir(parents=True)
    write_session(
        directory, _descriptor(stop_state="budget_spent", stopping_rule="xatol", stop_note=None)
    )

    summary = dict(summary_rows(session_summary(Session(directory))))

    assert summary["search stopped"] == (
        "spent its budget before its rule (xatol) was met, not converged"
    )


def test_a_budget_only_search_promotes_a_calibrated_run_and_never_a_failed_one() -> None:
    def label(status: str) -> str:
        checks = make_checks(
            calibrated_by=CalibratedBy(
                session_id="sess0001",
                trial=7,
                session_status=status,
                stop_state="budget_spent",
                stopping_rule=BUDGET_RULE,
                cost=0.25,
            ),
            score_window=None,
            n_samples=None,
        )
        return label_for(
            checks, hydromodpy_version="2.0.0a5", issues=(), flow_regime="steady"
        ).label

    assert label("completed") == "calibrated"
    assert label("partial") == "exploratory"
    assert RULE_VERSION == "3"


# ``[flow] restart_from`` and the ``run`` of a ``[[mesh.refinement_zone]]`` name an
# earlier run, and a bare name is its latest version. The frozen ``config.toml``
# writes the sim_id instead. The request id tells such a run by the state the new run
# reads from it, so the original and its frozen copy ask alike, and two runs that
# read two versions of one source run ask alike when the versions left the same state.
ZONE = {"where": "watertable_depth", "below": 0.5, "cell_size": 25.0}


@pytest.fixture
def project_2(tmp_path: Path) -> Path:
    return make_project(tmp_path / "demo")


def _sealed_3(project_2: Path, name: str) -> str:
    sim_id = seal_run(project_2, name, site=None)
    (project_2 / "runs" / name / FIELDS_STORE_NAME).mkdir()
    return sim_id


def _config(project_2: Path, *, zone_run: str | None = None, restart: Any = None) -> dict:
    config: dict[str, Any] = {"workspace": {"project_root": str(project_2)}, "flow": {}}
    if zone_run is not None:
        config["mesh"] = {"engine": "voronoi", "refinement_zone": [{**ZONE, "run": zone_run}]}
    if restart is not None:
        config["flow"]["restart_from"] = restart
    return config


ZONE_KEY = ZONE_RUN_KEY.format(index=0)


def _hash(project_2: Path, *, state: str | None = None, **kwargs: Any) -> str:
    """Return the request id of the configuration, the earlier run it reads told by *state*.

    The name of the earlier run, its version and its ``sim_id`` count for nothing: the
    digest of the state the run reads from it stands in their place.
    """
    states: dict[str, str] = {}
    if state is not None:
        key = ZONE_KEY if kwargs.get("zone_run") is not None else RESTART_KEY
        states[key] = state
    return request_id(_config(project_2, **kwargs), {}, edition="2.1", source_states=states or None)


def test_a_reference_resolves_to_the_sim_id_of_a_sealed_run(project_2: Path) -> None:
    first = _sealed_3(project_2, "spinup")
    second = _sealed_3(project_2, "spinup.v2")

    assert source_run_id(project_2, "spinup") == second, "a bare name is the latest version"
    assert source_run_id(project_2, "spinup.v2") == second
    assert source_run_id(project_2, "runs/spinup") == first
    assert source_run_id(project_2, f"runs/spinup/{FIELDS_STORE_NAME}") == first
    assert source_run_id(project_2, str(project_2 / "runs" / "spinup")) == first
    assert source_run_id(project_2, first) == first
    assert source_run_id(project_2, first[:10]) == first


def test_a_reference_that_names_no_sealed_run_has_no_sim_id(project_2: Path) -> None:
    sealed = _sealed_3(project_2, "spinup")
    (project_2 / "runs" / "open").mkdir()

    assert source_run_id(project_2, "nowhere") is None
    assert source_run_id(project_2, "open") is None
    assert source_run_id(project_2, "") is None
    assert source_run_id(project_2, sealed[:4]) is None, "a prefix needs eight characters"
    assert source_run_id(project_2, "0" * 32) is None


def test_a_prefix_that_matches_two_runs_names_none(project_2: Path) -> None:
    seal_run(project_2, "first", site=None, sim_id="ab" * 16)
    seal_run(project_2, "second", site=None, sim_id="ab" * 8 + "cd" * 8)

    assert source_run_id(project_2, "ab" * 4) is None
    assert source_run_id(project_2, "ab" * 8 + "cd") == "ab" * 8 + "cd" * 8


def test_the_references_of_a_payload_are_written_as_sim_ids(project_2: Path) -> None:
    sim_id = _sealed_3(project_2, "spinup")
    payload = _config(project_2, zone_run="spinup", restart="spinup")

    resolve_source_runs(payload, project_2)

    assert payload["mesh"]["refinement_zone"][0]["run"] == sim_id
    assert payload["flow"]["restart_from"] == sim_id


def test_a_reference_to_nothing_is_left_as_written(project_2: Path) -> None:
    payload = _config(project_2, zone_run="nowhere", restart="elsewhere")

    resolve_source_runs(payload, project_2)

    assert payload["mesh"]["refinement_zone"][0]["run"] == "nowhere"
    assert payload["flow"]["restart_from"] == "elsewhere"


def test_a_zone_is_told_by_the_state_it_reads_and_not_by_the_name_of_its_run(
    project_2: Path,
) -> None:
    sim_id = _sealed_3(project_2, "coarse")

    same = _hash(project_2, zone_run="coarse", state="d1")
    assert same == _hash(project_2, zone_run=sim_id, state="d1")
    assert same == _hash(project_2, zone_run="coarse.v2", state="d1")
    assert same != _hash(project_2, zone_run="coarse", state="d2")


def test_a_later_version_of_the_source_changes_the_id_only_when_its_state_moves(
    project_2: Path,
) -> None:
    _sealed_3(project_2, "coarse")
    before = _hash(project_2, zone_run="coarse", state="d1")

    _sealed_3(project_2, "coarse.v2")

    assert _hash(project_2, zone_run="coarse", state="d1") == before
    assert _hash(project_2, zone_run="coarse", state="d2") != before


def test_a_hotstart_is_told_alike_in_every_form_that_names_one_state(project_2: Path) -> None:
    from hydromodpy.core.state.result_dirs import run_dir_rel

    sim_id = _sealed_3(project_2, "spinup")
    store = f"{run_dir_rel('spinup')}/{FIELDS_STORE_NAME}"
    table = {"sim_id": sim_id, "path": store}
    forms = ["spinup", sim_id, store, str(project_2 / store), table]

    assert len({_hash(project_2, restart=form, state="d1") for form in forms}) == 1
    assert _hash(project_2, restart="spinup", state="d1") != _hash(project_2, restart=None)


def test_a_hotstart_moves_the_id_with_its_state(project_2: Path) -> None:
    _sealed_3(project_2, "spinup")

    assert _hash(project_2, restart="spinup", state="d1") != _hash(
        project_2, restart="spinup", state="d2"
    )


def test_a_configuration_without_a_project_root_is_told_as_written() -> None:
    def told(run: str) -> str:
        document = {"mesh": {"engine": "voronoi", "refinement_zone": [{**ZONE, "run": run}]}}
        return request_id(document, {}, edition="2.1")

    assert told("coarse") == told("coarse")
    assert told("coarse") != told("other")
