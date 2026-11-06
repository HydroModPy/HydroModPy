"""Every derived field is rebuilt on read, not stored.

A new run keeps the per-cell budget terms and every reader rebuilds the fields
from them, over a whole range or for one step, the step being one row of the
range. ``fixtures/derived_at_d5f485f88`` holds what the code before the
rebuild, which computed and stored them, derived on synthetic stores: the
rebuilt fields equal it bit for bit. A run written before still holds some
fields under ``derived/``, and the stored array is what every reader returns,
so such a store reads exactly as it did.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.budget.flux import release_flux_stack
from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.derive import virtual_fields
from hydromodpy.results.derive.views import _stack_field
from hydromodpy.results.derive.virtual_fields import (
    VIRTUAL_FIELD_ROWS,
    available_virtual_fields,
    derive_field_stack,
    read_field_or_virtual,
    read_field_range_or_virtual,
)
from hydromodpy.results.errors import FieldNotFoundError
from hydromodpy.results.run import Run
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_stores import claim_run, facts_of
from tests.regression.golden_utils import store_field_signature
from tests.unit.results import _derived_reference_stores as reference

N_STEPS = 5
AREAS = np.array([10.0, 20.0, 40.0, 80.0])
N_CELLS = AREAS.size


def _row_of_rectangles() -> tuple[np.ndarray, np.ndarray]:
    """Unit-height rectangles whose width is the area: the mesh gives AREAS back."""
    x = np.concatenate([[0.0], np.cumsum(AREAS)])
    vertices = np.array([[xi, 0.0, 0.0] for xi in x] + [[xi, 1.0, 0.0] for xi in x])
    n_x = x.size
    connectivity = np.array([[i, i + 1, n_x + i + 1, n_x + i] for i in range(N_CELLS)])
    return vertices, connectivity.astype("int32")


def _budget() -> dict[str, np.ndarray]:
    rng = np.random.default_rng(7)
    drain = -rng.uniform(0.0, 2e-3, (N_STEPS, 1, N_CELLS))
    drain[:, :, 0] = 0.0
    stream = rng.uniform(-3e-3, 1e-3, (N_STEPS, 1, N_CELLS))
    recharge = rng.uniform(0.0, 1e-4, (N_STEPS, 1, N_CELLS))
    return {"drain": drain, "stream": stream, "recharge": recharge}


def _open(project: Path, name: str, *, precision: str | None = None) -> RunStore:
    """Claim ``runs/<name>`` and open its store with an empty field store."""
    claim = claim_run(project, name)
    store = RunStore.open(
        claim.run_dir,
        facts=facts_of(claim, project="p", n_cells=N_CELLS, n_layers=1, n_timesteps=N_STEPS),
        persistence=PersistenceConfig()
        if precision is None
        else PersistenceConfig(field_precision=precision),
        workspace=project,
    )
    store.create_zarr(n_cells=N_CELLS, n_layers=1)
    return store


@contextmanager
def _seeded(
    project: Path,
    budget: dict[str, np.ndarray],
    *,
    mesh: bool = True,
    derived: dict[str, np.ndarray] | None = None,
    precision: str | None = None,
) -> Iterator[tuple[Catalog, str]]:
    """Seal a one-layer run with its head and *budget*, index it, and yield the catalog and id.

    ``derived`` holds the stacks a run written before kept under ``derived/``.
    """
    store = _open(project, "run", precision=precision)
    sid = store.sim_id
    vertices, connectivity = _row_of_rectangles()
    sz = store.open_zarr(sid)
    try:
        if mesh:
            sz.write_mesh(vertices, connectivity, np.array([150.0, 50.0]))
        sz.write_field_stack("head", np.full((N_STEPS, 1, N_CELLS), 120.0))
        for name, values in budget.items():
            sz.write_field_stack(name, values, subgroup="budget")
        for name, values in (derived or {}).items():
            sz.write_field_stack(name, values, subgroup="derived")
    finally:
        sz.close()
    seal_completed(store)
    rebuild_index(project)
    with Catalog(project) as catalog:
        yield catalog, sid


def _stored_budget(catalog: Catalog, sid: str) -> dict[str, np.ndarray]:
    sz = catalog.open_zarr(sid)
    try:
        group = sz.root["budget"]
        return {name: np.asarray(group[name][:], dtype="float64") for name in group.array_keys()}
    finally:
        sz.close()


def test_a_run_stores_no_release_flux_and_the_field_is_served(project) -> None:
    with _seeded(project, _budget()) as (catalog, sid):
        sz = catalog.open_zarr(sid)
        try:
            derived = sz.root.get("derived")
            assert derived is None or "release_flux" not in derived
            assert "release_flux" in available_virtual_fields(sz.root)
        finally:
            sz.close()
        run = Run(sid, catalog)
        assert run.has_field("release_flux")
        assert "release_flux" in run.array.list_fields()


def test_a_release_step_is_the_union_of_every_path_out(project) -> None:
    with _seeded(project, _budget()) as (catalog, sid):
        stored = _stored_budget(catalog, sid)
        expected = np.maximum(-stored["drain"][:, 0], 0.0) + np.maximum(
            -stored["stream"][:, 0], 0.0
        )

        run = Run(sid, catalog)
        rows = np.stack([run.field("release_flux", time=t) for t in range(N_STEPS)])

    np.testing.assert_allclose(rows, expected, rtol=1e-12, atol=0.0)


def test_every_reader_rebuilds_the_same_values_as_the_derivation_computes(project) -> None:
    with _seeded(project, _budget()) as (catalog, sid):
        sz = catalog.open_zarr(sid)
        try:
            reference = release_flux_stack(
                sz.root["budget"], n_cells=N_CELLS, start=0, stop=N_STEPS
            )
            whole = derive_field_stack(sz, sid, "release_flux", range(N_STEPS))
            picked = derive_field_stack(sz, sid, "release_flux", [3, 1])
        finally:
            sz.close()
        run = Run(sid, catalog)
        per_step = np.stack([run.field("release_flux", time=t) for t in range(N_STEPS)])
        stacked = _stack_field(run, "release_flux")

    np.testing.assert_array_equal(whole, reference)
    np.testing.assert_array_equal(per_step, reference)
    np.testing.assert_array_equal(picked, reference[[3, 1]])
    np.testing.assert_array_equal(stacked, reference)


def test_a_run_whose_budget_has_no_path_out_serves_no_release_flux(project) -> None:
    with _seeded(project, {"recharge": _budget()["recharge"]}) as (catalog, sid):
        run = Run(sid, catalog)

        assert not run.has_field("release_flux")
        with pytest.raises(FieldNotFoundError):
            run.field("release_flux", time=0)


def test_the_unit_budget_flux_is_the_drain_over_the_cell_area(project) -> None:
    with _seeded(project, _budget()) as (catalog, sid):
        drain = _stored_budget(catalog, sid)["drain"][:, 0]

        run = Run(sid, catalog)

        assert run.has_field("budget_flux_per_area")
        for step in range(N_STEPS):
            np.testing.assert_allclose(
                run.field("budget_flux_per_area", time=step), drain[step] / AREAS, rtol=1e-12
            )
        sz = catalog.open_zarr(sid)
        try:
            stack = derive_field_stack(sz, sid, "budget_flux_per_area", range(N_STEPS))
        finally:
            sz.close()
    np.testing.assert_allclose(stack, drain / AREAS, rtol=1e-12)


def test_the_unit_budget_flux_needs_the_mesh_geometry(project) -> None:
    with _seeded(project, {"drain": _budget()["drain"]}, mesh=False) as (catalog, sid):
        run = Run(sid, catalog)

        assert not run.has_field("budget_flux_per_area")
        assert run.has_field("release_flux")


def test_a_store_written_before_reads_its_stored_arrays(project) -> None:
    """Old runs are float64 with the two fields stored; the stored array wins."""
    budget = _budget()
    # Deliberately not what the budget rebuilds, so a recomputation is caught.
    stored_release = np.arange(N_STEPS * N_CELLS, dtype="float64").reshape(N_STEPS, N_CELLS)
    stored_unit = stored_release / 7.0 + 0.1
    derived = {"release_flux": stored_release, "budget_flux_per_area": stored_unit}
    with _seeded(project, budget, derived=derived, precision="exact") as (catalog, sid):
        sz = catalog.open_zarr(sid)
        try:
            assert sz.root["derived"]["release_flux"].dtype == np.float64
            assert sz.root["head"].dtype == np.float64
            np.testing.assert_array_equal(sz.root["budget"]["drain"][:], budget["drain"])
        finally:
            sz.close()

        run = Run(sid, catalog)
        for step in range(N_STEPS):
            np.testing.assert_array_equal(
                run.field("release_flux", time=step), stored_release[step]
            )
            np.testing.assert_array_equal(
                run.field("budget_flux_per_area", time=step), stored_unit[step]
            )
        np.testing.assert_array_equal(_stack_field(run, "release_flux"), stored_release)
        np.testing.assert_array_equal(
            run.array.to_xarray_batch(("release_flux",))["release_flux"].values, stored_release
        )


# -- Every field, against what the code before the rebuild derived ------------

NO_ROUTE_FIELDS = ("drain_accumulation_flux", "release_accumulation_flux")


@pytest.fixture
def built(tmp_path: Path) -> Iterator[Callable[[str], RunStore]]:
    """Build a reference store by its kind; every store built is closed at the end."""
    opened: list[RunStore] = []

    def build(kind: str) -> RunStore:
        store = reference.build_store(kind, tmp_path / "exact")
        opened.append(store)
        return store

    yield build
    for store in opened:
        store.close()


@pytest.fixture
def exact_store(project: Path) -> Iterator[RunStore]:
    """An empty one-layer run in the precision of the reference stores, left unsealed."""
    store = _open(project, "run", precision="exact")
    yield store
    store.close()


@pytest.fixture(autouse=True)
def _fresh_descent_cache():
    from hydromodpy.results.derive import accumulation

    accumulation._graphs.clear()
    yield
    accumulation._graphs.clear()


RENAMED_IN_THE_FIXTURES = {
    "accumulation_flux": "drain_accumulation_flux",
    "mass_accumulated": "mass_seepage_running_sum",
}
"""The fixtures keep the names the fields had when the base derived them."""


def _field_of(key: str) -> str:
    """Return the field a fixture array holds."""
    field = key.split("__", 1)[1]
    return RENAMED_IN_THE_FIXTURES.get(field, field)


def _reference_cases() -> list[tuple[str, str]]:
    """Return (store, array name) for each stack the base code derived and a reader rebuilds.

    ``virtual__outflow_drain`` is the base per-step read, which took the drain
    term alone; it is checked apart. The base wrote an unrouted local flux for
    a store with no descent, which a reader never serves.
    """
    cases = []
    for kind in reference.STORE_KINDS:
        with np.load(reference.fixture_path(kind)) as archive:
            for key in archive.files:
                if key.startswith("route__") or key == "virtual__outflow_drain":
                    continue
                if kind == "no_route" and _field_of(key) in NO_ROUTE_FIELDS:
                    continue
                cases.append((kind, key))
    return cases


def _reference(kind: str, key: str) -> np.ndarray:
    """Return what the base derived, without the step its sign guess read as an outflow.

    Step 4 of the drain is all positive. The base took that for an outflow when it read
    the drain alone, which only the solute chain does on these stores. A positive flux
    enters the aquifer, so no solute leaves at that step.
    """
    with np.load(reference.fixture_path(kind)) as archive:
        if key == "base__mass_seepage":
            return _without_guess(archive[key])
        if key == "base__mass_accumulated":
            return np.cumsum(_without_guess(archive["base__mass_seepage"]), axis=0)
        return archive[key]


def _without_guess(mass_seepage: np.ndarray) -> np.ndarray:
    stack = np.array(mass_seepage)
    stack[4] = stack[4] * 0.0
    return stack


@pytest.mark.parametrize(("kind", "key"), _reference_cases())
def test_a_range_equals_what_the_base_derived_bit_for_bit(built, kind, key) -> None:
    store = built(kind)
    sid = store.sim_id
    field = _field_of(key)

    rebuilt = read_field_range_or_virtual(store, sid, field, 0, reference.N_STEPS)

    np.testing.assert_array_equal(rebuilt, _reference(kind, key))


@pytest.mark.parametrize(("kind", "key"), _reference_cases())
def test_a_step_read_alone_equals_the_row_of_the_range(built, kind, key) -> None:
    store = built(kind)
    sid = store.sim_id
    field = _field_of(key)
    expected = _reference(kind, key)

    for step in range(reference.N_STEPS):
        np.testing.assert_array_equal(
            read_field_or_virtual(store, sid, field, step), expected[step]
        )
    np.testing.assert_array_equal(read_field_or_virtual(store, sid, field, -1), expected[-1])


@pytest.mark.parametrize(("kind", "key"), _reference_cases())
def test_a_sub_range_is_the_rows_of_the_whole_range(built, kind, key) -> None:
    store = built(kind)
    sid = store.sim_id
    field = _field_of(key)

    part = read_field_range_or_virtual(store, sid, field, 2, 5)

    np.testing.assert_array_equal(part, _reference(kind, key)[2:5])


@pytest.mark.parametrize(("kind", "key"), _reference_cases())
def test_passes_of_one_step_join_into_the_whole_range(
    built, monkeypatch: pytest.MonkeyPatch, kind, key
) -> None:
    """The running sum of mass_seepage_running_sum carries over from one pass to the next."""
    store = built(kind)
    sid = store.sim_id
    field = _field_of(key)
    monkeypatch.setattr(virtual_fields, "ROWS_PER_PASS_ELEMENTS", reference.N_CELLS)

    rebuilt = read_field_range_or_virtual(store, sid, field, 0, reference.N_STEPS)

    np.testing.assert_array_equal(rebuilt, _reference(kind, key))


def test_every_field_has_a_range_path_and_a_step_that_is_a_row_of_it() -> None:
    assert set(VIRTUAL_FIELD_ROWS) <= set(virtual_fields.VIRTUAL_FIELDS)
    assert set(VIRTUAL_FIELD_ROWS) == {
        "watertable_elevation",
        "watertable_depth",
        "seepage_mask",
        "outflow_drain",
        "release_flux",
        "budget_flux_per_area",
        "drain_accumulation_flux",
        "release_accumulation_flux",
        "concentration_seepage",
        "mass_seepage",
        "mass_seepage_running_sum",
    }


def test_the_outflow_drain_adds_the_mover_the_base_step_read_left_out(built) -> None:
    store = built("mf6")
    sid = store.sim_id

    rebuilt = read_field_range_or_virtual(store, sid, "outflow_drain", 0, reference.N_STEPS)

    np.testing.assert_array_equal(rebuilt, _reference("mf6", "base__outflow_drain"))
    drain_alone = _reference("mf6", "virtual__outflow_drain")
    # Step 4 holds only positive drain values, which the base read alone as an
    # outflow through its sign guess, so that step is left out.
    steps = [0, 1, 2, 3, 5]
    assert np.all(rebuilt[steps] >= drain_alone[steps])
    assert np.any(rebuilt[steps] > drain_alone[steps])


def test_a_store_with_no_mover_reads_the_drain_as_the_base_step_read_did(built) -> None:
    store = built("boussinesq")
    sid = store.sim_id

    rebuilt = read_field_range_or_virtual(store, sid, "outflow_drain", 0, reference.N_STEPS)

    np.testing.assert_array_equal(rebuilt, _reference("boussinesq", "virtual__outflow_drain"))


def test_the_solute_chain_keeps_nan_outside_the_seepage_and_where_the_concentration_is(
    built,
) -> None:
    store = built("transport")
    sid = store.sim_id
    seepage = _reference("transport", "base__seepage_mask")

    conc = read_field_range_or_virtual(store, sid, "concentration_seepage", 0, reference.N_STEPS)
    mass = read_field_range_or_virtual(store, sid, "mass_seepage", 0, reference.N_STEPS)
    total = read_field_range_or_virtual(
        store, sid, "mass_seepage_running_sum", 0, reference.N_STEPS
    )

    assert np.all(np.isnan(conc[seepage == 0]))
    assert np.all(np.isnan(mass[seepage == 0]))
    assert np.isnan(conc[:, 2]).all()
    # A NaN stays NaN from its step on, so a cell that seeps only sometimes is NaN afterwards.
    first_nan = np.isnan(total).argmax(axis=0)
    for cell in np.flatnonzero(np.isnan(total).any(axis=0)):
        assert np.isnan(total[first_nan[cell] :, cell]).all()


# -- A store that can route nothing ------------------------------------------


def test_a_store_with_no_descent_and_no_topology_does_not_list_the_accumulation(
    built,
) -> None:
    store = built("no_route")
    sid = store.sim_id
    sz = store.open_zarr(sid)
    try:
        listed = available_virtual_fields(sz.root)
    finally:
        sz.close()

    for field in NO_ROUTE_FIELDS:
        assert field not in listed
        with pytest.raises(KeyError):
            read_field_or_virtual(store, sid, field, 0)
        with pytest.raises(KeyError):
            read_field_range_or_virtual(store, sid, field, 0, 2)
    assert {"release_flux", "outflow_drain", "seepage_mask"} <= set(listed)


def test_the_stores_list_the_fields_they_can_serve(built) -> None:
    listed = {}
    for kind in reference.STORE_KINDS:
        store = built(kind)
        sid = store.sim_id
        sz = store.open_zarr(sid)
        try:
            listed[kind] = set(available_virtual_fields(sz.root))
        finally:
            sz.close()

    chain = {"concentration_seepage", "mass_seepage", "mass_seepage_running_sum"}
    assert chain <= listed["transport"]
    for kind in set(reference.STORE_KINDS) - {"transport"}:
        assert not chain & listed[kind]
    for kind in ("mf6", "mf6_no_descent", "boussinesq", "boussinesq_no_excess", "transport"):
        assert set(NO_ROUTE_FIELDS) <= listed[kind]
    assert "budget_flux_per_area" not in listed["boussinesq"]


def test_a_step_outside_the_time_axis_is_refused(built) -> None:
    store = built("mf6")
    sid = store.sim_id

    for field in (
        "watertable_elevation",
        "seepage_mask",
        "drain_accumulation_flux",
        "outflow_drain",
    ):
        with pytest.raises(IndexError):
            read_field_or_virtual(store, sid, field, reference.N_STEPS)
        with pytest.raises(IndexError):
            read_field_range_or_virtual(store, sid, field, 0, reference.N_STEPS + 1)


# -- The geometric fallback warns once per read ------------------------------


def _fallback_warnings(caplog) -> list[logging.LogRecord]:
    return [record for record in caplog.records if "geometric criterion" in record.getMessage()]


def test_the_geometric_fallback_warns_once_for_a_whole_range(
    built, caplog, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = built("boussinesq_no_excess")
    sid = store.sim_id
    monkeypatch.setattr(virtual_fields, "ROWS_PER_PASS_ELEMENTS", reference.N_CELLS)

    with caplog.at_level(logging.WARNING, logger="hydromodpy.spatial.drainage.graph"):
        read_field_range_or_virtual(store, sid, "seepage_mask", 0, reference.N_STEPS)

    assert len(_fallback_warnings(caplog)) == 1


def test_the_geometric_fallback_warns_once_for_each_step_read_alone(built, caplog) -> None:
    store = built("boussinesq_no_excess")
    sid = store.sim_id

    with caplog.at_level(logging.WARNING, logger="hydromodpy.spatial.drainage.graph"):
        read_field_or_virtual(store, sid, "seepage_mask", 1)
        read_field_or_virtual(store, sid, "seepage_mask", 2)

    assert len(_fallback_warnings(caplog)) == 2


def test_a_modflow_store_stays_quiet_and_so_does_a_surface_excess_store(built, caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="hydromodpy.spatial.drainage.graph"):
        for kind in ("mf6", "boussinesq"):
            store = built(kind)
            sid = store.sim_id
            read_field_range_or_virtual(store, sid, "seepage_mask", 0, reference.N_STEPS)

    assert _fallback_warnings(caplog) == []


def test_the_solute_chain_warns_once_when_it_falls_back_to_the_geometric_mask(
    built, caplog, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = built("boussinesq_no_excess")
    sid = store.sim_id
    sz = store.open_zarr(sid)
    try:
        sz.write_field_stack("concentration", np.ones((reference.N_STEPS, reference.N_CELLS)))
    finally:
        sz.close()
    monkeypatch.setattr(virtual_fields, "ROWS_PER_PASS_ELEMENTS", reference.N_CELLS)

    with caplog.at_level(logging.WARNING, logger="hydromodpy.spatial.drainage.graph"):
        read_field_range_or_virtual(store, sid, "mass_seepage_running_sum", 0, reference.N_STEPS)

    assert len(_fallback_warnings(caplog)) == 1


# -- A run written before: the stored array is read first, upstream too ------


def _write_derived(store: RunStore, sid: str, name: str, values: np.ndarray) -> None:
    sz = store.open_zarr(sid)
    try:
        sz.write_field_stack(name, values, subgroup="derived")
    finally:
        sz.close()


def _budget_of(store: RunStore, sid: str, name: str) -> np.ndarray:
    sz = store.open_zarr(sid)
    try:
        return np.asarray(sz.root["budget"][name][:], dtype="float64")
    finally:
        sz.close()


def test_an_old_stored_water_table_feeds_the_depth_and_the_geometric_seepage(
    built,
) -> None:
    store = built("mf6")
    sid = store.sim_id
    stored = np.linspace(15.0, 30.0, reference.N_STEPS * reference.N_CELLS).reshape(
        reference.N_STEPS, reference.N_CELLS
    )
    _write_derived(store, sid, "watertable_elevation", stored)
    sz = store.open_zarr(sid)
    try:
        top = np.asarray(sz.root["mesh"]["topography"][:], dtype="float64")
    finally:
        sz.close()
    expected_depth = np.maximum(top - stored, 0.0)
    expected_seepage = (stored >= top - 0.5 * reference.BAND_DEPTH_M).astype("float64")

    depth = read_field_range_or_virtual(store, sid, "watertable_depth", 0, reference.N_STEPS)
    seepage = read_field_range_or_virtual(store, sid, "seepage_mask", 0, reference.N_STEPS)

    np.testing.assert_array_equal(depth, expected_depth)
    np.testing.assert_array_equal(seepage, expected_seepage)
    np.testing.assert_array_equal(
        read_field_or_virtual(store, sid, "watertable_depth", 3), expected_depth[3]
    )


def test_an_old_stored_seepage_mask_decides_the_concentration_at_seepage(built) -> None:
    store = built("transport")
    sid = store.sim_id
    mask = np.zeros((reference.N_STEPS, reference.N_CELLS))
    mask[:, ::2] = 1.0
    _write_derived(store, sid, "seepage_mask", mask)
    sz = store.open_zarr(sid)
    try:
        conc = np.asarray(sz.root["concentration"][:, 0], dtype="float64")
    finally:
        sz.close()

    rebuilt = read_field_range_or_virtual(store, sid, "concentration_seepage", 0, reference.N_STEPS)

    np.testing.assert_array_equal(rebuilt, np.where(mask > 0, conc * mask, np.nan))


def test_an_old_stored_concentration_and_mass_feed_the_next_field(built) -> None:
    store = built("transport")
    sid = store.sim_id
    shape = (reference.N_STEPS, reference.N_CELLS)
    stored_concentration = np.arange(np.prod(shape), dtype="float64").reshape(shape) / 7.0
    _write_derived(store, sid, "concentration_seepage", stored_concentration)
    drain = _budget_of(store, sid, "drain")
    from hydromodpy.core.budget.flux import budget_outflow_stack

    flux = budget_outflow_stack(drain, n_cells=reference.N_CELLS)

    mass = read_field_range_or_virtual(store, sid, "mass_seepage", 0, reference.N_STEPS)

    np.testing.assert_array_equal(mass, stored_concentration * flux)

    stored_mass = np.arange(np.prod(shape), dtype="float64").reshape(shape) * 0.1
    _write_derived(store, sid, "mass_seepage", stored_mass)

    total = read_field_range_or_virtual(
        store, sid, "mass_seepage_running_sum", 0, reference.N_STEPS
    )

    np.testing.assert_array_equal(total, np.cumsum(stored_mass, axis=0))
    np.testing.assert_array_equal(
        read_field_or_virtual(store, sid, "mass_seepage_running_sum", 4), total[4]
    )


def test_the_mass_flux_multiplies_by_one_when_the_run_has_no_drain_term(
    exact_store: RunStore,
) -> None:
    store = exact_store
    sid = store.sim_id
    concentration = np.full((N_STEPS, 1, N_CELLS), 2.0)
    sz = store.open_zarr(sid)
    try:
        sz.write_topography(np.full(N_CELLS, 100.0))
        sz.write_field_stack("head", np.full((N_STEPS, 1, N_CELLS), 101.0))
        sz.write_field_stack("concentration", concentration)
        sz.write_field_stack("recharge", np.full((N_STEPS, 1, N_CELLS), 1e-4), subgroup="budget")
    finally:
        sz.close()

    mass = read_field_range_or_virtual(store, sid, "mass_seepage", 0, N_STEPS)

    np.testing.assert_array_equal(mass, np.full((N_STEPS, N_CELLS), 2.0))


def test_the_mass_chain_needs_a_budget_group(exact_store: RunStore) -> None:
    store = exact_store
    sid = store.sim_id
    sz = store.open_zarr(sid)
    try:
        sz.write_topography(np.full(N_CELLS, 100.0))
        sz.write_field_stack("head", np.full((N_STEPS, 1, N_CELLS), 101.0))
        sz.write_field_stack("concentration", np.ones((N_STEPS, 1, N_CELLS)))
        listed = available_virtual_fields(sz.root)
    finally:
        sz.close()

    assert "concentration_seepage" in listed
    assert "mass_seepage" not in listed
    assert "mass_seepage_running_sum" not in listed
    with pytest.raises(KeyError):
        read_field_range_or_virtual(store, sid, "mass_seepage", 0, N_STEPS)


# -- Readers that walk the steps read the range ------------------------------


def test_the_golden_signature_reads_the_time_axis_not_a_probe(built) -> None:
    store = built("transport")
    sid = store.sim_id

    stored = store_field_signature(store, sid, "head")
    rebuilt = store_field_signature(store, sid, "mass_seepage_running_sum")

    assert stored["available_timesteps"] == reference.N_STEPS
    assert stored["timestep"] == reference.N_STEPS - 1
    assert stored["shape"] == [2 * reference.N_CELLS]
    assert rebuilt["available_timesteps"] == reference.N_STEPS
    last = _reference("transport", "base__mass_accumulated")[-1]
    assert rebuilt["count"] == int(np.isfinite(last).sum())
    with pytest.raises(KeyError):
        store_field_signature(store, sid, "seepage_areas")
