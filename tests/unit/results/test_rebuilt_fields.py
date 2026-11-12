"""Fields rebuilt on read from the stored per-cell budget terms, never stored themselves.

Fluxes are in m3/s (negative leaves the aquifer), concentrations in mass/m3, so a
mass flux is mass/s. ``fixtures/derived_at_d5f485f88`` holds what the code before
the rebuild derived on synthetic stores: the rebuilt fields equal it bit for bit.
A run written before still holds some fields under ``derived/``, and that stored
array is what every reader returns.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import partial
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.budget.flux import budget_outflow, budget_outflow_stack
from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.derive import accumulation, virtual_fields
from hydromodpy.results.derive.views import _stack_field
from hydromodpy.results.derive.virtual_fields import (
    VIRTUAL_FIELD_ROWS,
    available_virtual_fields,
    derive_field_stack,
    read_field_or_virtual,
    read_field_range_or_virtual,
)
from hydromodpy.results.errors import FieldNotFoundError
from hydromodpy.results.run.view import Run
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_builders import RunBuilder, runs
from tests._helpers.run_stores import claim_run, facts_of
from tests.regression.golden_utils import store_field_signature
from tests.unit.results import _derived_reference_stores as reference

__all__ = ["runs"]

N_STEPS = 5
AREAS = np.array([10.0, 20.0, 40.0, 80.0])  # m2, one cell each
N_CELLS = AREAS.size
NO_ROUTE_FIELDS = ("drain_accumulation_flux", "release_accumulation_flux")
RENAMED_IN_THE_FIXTURES = {
    "accumulation_flux": "drain_accumulation_flux",
    "mass_accumulated": "mass_seepage_running_sum",
}  # the fixtures keep the names the fields had when the base derived them


# Small runs written through the run builder, read back through its reader.
# The store keeps float32, so values come back to about 1e-6 relative.
close = partial(np.testing.assert_allclose, rtol=1e-5, atol=1e-8)


def term(name, stack, subgroup=None):
    return name, stack, subgroup


def budget_term(name, stack):
    return term(name, stack, "budget")


def seed_run(runs: RunBuilder, n_ts, n_cells, *terms, head=9.0, mesh=True) -> str:
    """One-layer run with a flat head, a triangle mesh and the given terms."""
    sid = runs.open(solver="modflow_nwt", n_cells=n_cells, n_layers=1, n_timesteps=n_ts).sim_id
    if mesh:
        write_fan_mesh(runs, sid, n_cells)
    write_stack(runs, sid, "head", np.broadcast_to(head, (n_ts, 1, n_cells)))
    for name, stack, subgroup in terms:
        write_stack(runs, sid, name, stack, subgroup)
    return sid


def write_stack(runs, sid, name, stack, subgroup=None) -> None:
    for t, values in enumerate(stack):
        runs.store(sid).write_field(
            sid, name, t, values, n_timesteps=len(stack) if t == 0 else None, subgroup=subgroup
        )


def write_fan_mesh(runs, sid, n_cells) -> None:
    """Triangles on random vertices, with layer interfaces at 10, 5 and 0 m."""
    verts = np.random.default_rng(0).random((n_cells + 2, 2))
    conn = np.column_stack(
        [np.arange(n_cells), np.arange(1, n_cells + 1), np.full(n_cells, n_cells + 1)]
    ).astype("int32")
    runs.store(sid).write_mesh(sid, verts, conn, np.array([10.0, 5.0, 0.0]))


def strip_run(runs, drain, topography):
    """A strip of unit quads sharing vertical edges, so the descent is a real line graph."""
    n_ts, n_cells = len(drain), len(topography)
    sid = runs.open(solver="modflow_nwt", n_cells=n_cells, n_layers=1, n_timesteps=n_ts).sim_id
    bottom = np.column_stack([np.arange(n_cells + 1, dtype="float64"), np.zeros(n_cells + 1)])
    top = np.column_stack([np.arange(n_cells + 1, dtype="float64"), np.ones(n_cells + 1)])
    conn = np.array(
        [[i, i + 1, i + n_cells + 2, i + n_cells + 1] for i in range(n_cells)], dtype="int32"
    )
    z_intf = np.array([float(topography.max()) + 1.0, 0.0])
    runs.store(sid).write_mesh(sid, np.vstack([bottom, top]), conn, z_intf)
    write_stack(runs, sid, "topography", [topography], "mesh")
    write_stack(runs, sid, "head", np.full((n_ts, 1, n_cells), 9.0))
    write_stack(runs, sid, "drain", drain, "budget")
    return sid


def test_mass_chain_closure(runs):
    n_ts, n_cells = 4, 6
    rng = np.random.default_rng(7)
    conc = rng.uniform(0.5, 5.0, (n_ts, n_cells))
    drn = -rng.uniform(0.0, 3.0, (n_ts, n_cells))  # signed: negative leaves
    # Cells 0..2 seep at every step. Cell 3 seeps at step 1 only, to reach the
    # NaN path of the running sum on an intermittent cell.
    seep = np.zeros((n_ts, n_cells))
    seep[:, :3] = 1.0
    seep[1, 3] = 1.0
    stable = np.zeros(n_cells, dtype=bool)
    stable[:3] = True
    sid = seed_run(
        runs,
        n_ts,
        n_cells,
        term("concentration", conc),
        budget_term("drain", drn),
        term("seepage_mask", seep, "derived"),
    )
    reader = runs.reader()

    # concentration_seepage is the concentration where it seeps, NaN elsewhere.
    for t in range(n_ts):
        cs = reader.query_field(sid, "concentration_seepage", t)
        active = seep[t] > 0
        close(cs[active], conc[t][active])
        assert np.all(np.isnan(cs[~active]))

    # mass_seepage is concentration times positive drain outflow, (mass/m3) * (m3/s).
    mass = np.full((n_ts, n_cells), np.nan)
    for t in range(n_ts):
        ms = reader.query_field(sid, "mass_seepage", t)
        active = seep[t] > 0
        expected = conc[t] * budget_outflow(drn[t], n_cells=n_cells)
        close(ms[active], expected[active])
        assert np.all(np.isnan(ms[~active]))
        assert np.all(ms[active] >= 0.0)
        mass[t] = ms

    # The running sum is cumul[t] = cumul[t-1] + mass[t], cell by cell, NaN included.
    prev = np.zeros(n_cells)
    for t in range(n_ts):
        total = reader.query_field(sid, "mass_seepage_running_sum", t)
        close(total, prev + mass[t], equal_nan=True)
        prev = total

    # On the cells that always seep it is the partial sum and never decreases.
    partial = np.zeros(stable.sum())
    prev_partial = np.zeros(stable.sum())
    for t in range(n_ts):
        total = reader.query_field(sid, "mass_seepage_running_sum", t)[stable]
        partial = partial + mass[t][stable]
        close(total, partial)
        assert np.all(total + 1e-12 >= prev_partial)
        prev_partial = total


def test_mass_without_a_drain_is_the_concentration(runs):
    # A budget group without a drain key makes mass_seepage use a flux of one.
    conc = np.array([[1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0]])
    seep = np.array([[1, 1, 0, 0], [1, 0, 1, 0]], dtype="float64")
    sid = seed_run(
        runs,
        2,
        4,
        term("concentration", conc),
        term("seepage_mask", seep, "derived"),
        budget_term("surface_excess", np.zeros((2, 4))),
    )

    for t in range(2):
        ms = runs.reader().query_field(sid, "mass_seepage", t)
        active = seep[t] > 0
        close(ms[active], conc[t][active])
        assert np.all(np.isnan(ms[~active]))


def test_release_flux_adds_positive_outflows(runs):
    n_ts, n_cells = 3, 5
    rng = np.random.default_rng(11)
    drn = -rng.uniform(0.0, 2.0, (n_ts, n_cells))
    sexc = -rng.uniform(0.0, 1.5, (n_ts, n_cells))  # signed like every budget flux
    sid = seed_run(
        runs, n_ts, n_cells, budget_term("drain", drn), budget_term("surface_excess", sexc)
    )

    for t in range(n_ts):
        rf = runs.reader().query_field(sid, "release_flux", t)
        expected = budget_outflow(drn[t], n_cells=n_cells) + np.maximum(-sexc[t], 0.0)
        close(rf, expected)
        assert np.all(rf >= 0.0)
        assert np.all(np.isfinite(rf))


def test_seepage_cells_from_the_head(runs):
    # With no stored mask the seepage cells come from the head against the top (10 m).
    n_ts, n_cells = 3, 5
    rng = np.random.default_rng(99)
    sid = seed_run(
        runs,
        n_ts,
        n_cells,
        term("concentration", rng.uniform(1.0, 4.0, (n_ts, n_cells))),
        budget_term("drain", -rng.uniform(0.0, 2.0, (n_ts, n_cells))),
        head=rng.uniform(8.0, 12.0, (n_ts, 1, n_cells)),
    )
    reader = runs.reader()
    mass = np.stack([reader.query_field(sid, "mass_seepage", t) for t in range(n_ts)])

    prev = np.zeros(n_cells)
    for t in range(n_ts):
        total = reader.query_field(sid, "mass_seepage_running_sum", t)
        close(total, prev + mass[t], equal_nan=True)
        assert np.all(total[np.isfinite(total)] >= 0.0)
        prev = total


def test_flow_only_store_serves_no_solute(runs):
    # The flow run of a flow-then-transport plan holds no concentration.
    sid = seed_run(runs, 2, 4, budget_term("drain", -np.ones((2, 4))))

    for variable in ("concentration_seepage", "mass_seepage", "mass_seepage_running_sum"):
        with pytest.raises(KeyError):
            runs.reader().query_field(sid, variable, 0)


def test_outflow_drain_is_the_positive_outflow(runs):
    n_ts, n_cells = 3, 5
    drn = -np.random.default_rng(21).uniform(0.0, 4.0, (n_ts, n_cells))
    drn[0, 0] = -99999.0  # nodata sentinel, counted as zero outflow
    sid = seed_run(runs, n_ts, n_cells, budget_term("drain", drn))

    for t in range(n_ts):
        od = runs.reader().query_field(sid, "outflow_drain", t)
        close(od, budget_outflow(drn[t], n_cells=n_cells))
        assert np.all(od >= 0.0)
        assert np.all(np.isfinite(od))
    assert runs.reader().query_field(sid, "outflow_drain", 0)[0] == 0.0


def test_no_accumulation_without_a_route(runs):
    # The stored mesh has no topography and no stored descent: nothing to route on,
    # so the routed names are not served and the local flux never stands in for them.
    n_ts, n_cells = 2, 4
    rng = np.random.default_rng(22)
    sid = seed_run(
        runs,
        n_ts,
        n_cells,
        budget_term("drain", -rng.uniform(0.1, 3.0, (n_ts, n_cells))),
        budget_term("surface_excess", rng.uniform(0.0, 1.0, (n_ts, n_cells))),
    )

    for variable in NO_ROUTE_FIELDS:
        with pytest.raises(KeyError):
            runs.reader().query_field(sid, variable, 0)
    assert np.all(runs.reader().query_field(sid, "release_flux", 0) >= 0.0)


def test_outflow_drain_needs_a_budget(runs):
    sid = seed_run(runs, 2, 3, mesh=False)

    with pytest.raises(KeyError):
        runs.reader().query_field(sid, "outflow_drain", 0)


def test_routing_conserves_mass(runs):
    # Strictly decreasing topography is a single downhill chain to the last cell.
    topo = np.array([50.0, 40.0, 30.0, 20.0, 10.0])
    drn = -np.ones((1, 5))  # 1 m3/s released per cell
    sid = strip_run(runs, drn, topo)

    local = budget_outflow(drn[0], n_cells=5)
    acc = runs.reader().query_field(sid, "drain_accumulation_flux", 0)
    assert not np.allclose(acc, local)  # routing ran
    close(np.nanmax(acc), local.sum())  # the outlet carries the basin input
    assert np.all(acc[np.isfinite(acc)] >= 0.0)
    assert acc[-1] >= acc[0]


def test_budget_outflow_stack():
    # One step, two layers: outflow kept, inflow and nodata zeroed, layers summed.
    stack = np.array([[[-1.0, 2.0, -3.0, -99999.0], [-0.5, -4.0, np.nan, -2.0]]])

    out = budget_outflow_stack(stack, n_cells=4)[0]

    # cell 0: 1.0 + 0.5, cell 1: 0 + 4.0, cell 2: 3.0 + 0 (nan), cell 3: 0 (nodata) + 2.0
    np.testing.assert_allclose(out, [1.5, 4.0, 3.0, 2.0])


def test_budget_outflow_stack_empty():
    assert budget_outflow_stack(np.empty((0, 1, 3)), n_cells=3).shape == (0, 3)


# Sealed one-layer runs read through the catalog.


def row_of_rectangles() -> tuple[np.ndarray, np.ndarray]:
    """Unit-height rectangles whose width is the area: the mesh gives AREAS back."""
    x = np.concatenate([[0.0], np.cumsum(AREAS)])
    vertices = np.array([[xi, 0.0, 0.0] for xi in x] + [[xi, 1.0, 0.0] for xi in x])
    connectivity = np.array([[i, i + 1, x.size + i + 1, x.size + i] for i in range(N_CELLS)])
    return vertices, connectivity.astype("int32")


def random_budget() -> dict[str, np.ndarray]:
    rng = np.random.default_rng(7)
    drain = -rng.uniform(0.0, 2e-3, (N_STEPS, 1, N_CELLS))
    drain[:, :, 0] = 0.0
    stream = rng.uniform(-3e-3, 1e-3, (N_STEPS, 1, N_CELLS))
    recharge = rng.uniform(0.0, 1e-4, (N_STEPS, 1, N_CELLS))
    return {"drain": drain, "stream": stream, "recharge": recharge}


def open_store(project: Path, name: str, *, precision: str | None = None) -> RunStore:
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
def sealed_run(
    project: Path,
    budget: dict[str, np.ndarray],
    *,
    mesh: bool = True,
    derived: dict[str, np.ndarray] | None = None,
    precision: str | None = None,
) -> Iterator[tuple[Catalog, str]]:
    """Seal a one-layer run with its head and *budget*, index it, yield the catalog and id.

    ``derived`` holds the stacks a run written before kept under ``derived/``.
    """
    store = open_store(project, "run", precision=precision)
    sid = store.sim_id
    vertices, connectivity = row_of_rectangles()
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


def stored_budget(catalog: Catalog, sid: str) -> dict[str, np.ndarray]:
    sz = catalog.open_zarr(sid)
    try:
        group = sz.root["budget"]
        return {name: np.asarray(group[name][:], dtype="float64") for name in group.array_keys()}
    finally:
        sz.close()


def test_release_flux_is_the_union_of_paths_out(project):
    with sealed_run(project, random_budget()) as (catalog, sid):
        stored = stored_budget(catalog, sid)
        expected = np.maximum(-stored["drain"][:, 0], 0.0) + np.maximum(
            -stored["stream"][:, 0], 0.0
        )

        run = Run(sid, catalog)
        rows = np.stack([run.field("release_flux", time=t) for t in range(N_STEPS)])

    np.testing.assert_allclose(rows, expected, rtol=1e-12, atol=0.0)


def test_no_path_out_no_release_flux(project):
    with sealed_run(project, {"recharge": random_budget()["recharge"]}) as (catalog, sid):
        run = Run(sid, catalog)

        assert not run.has_field("release_flux")
        with pytest.raises(FieldNotFoundError):
            run.field("release_flux", time=0)


def test_budget_flux_per_area(project):
    with sealed_run(project, random_budget()) as (catalog, sid):
        drain = stored_budget(catalog, sid)["drain"][:, 0]

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


def test_budget_flux_per_area_needs_a_mesh(project):
    with sealed_run(project, {"drain": random_budget()["drain"]}, mesh=False) as (catalog, sid):
        run = Run(sid, catalog)

        assert not run.has_field("budget_flux_per_area")
        assert run.has_field("release_flux")


def test_stored_arrays_win(project):
    # Old runs are float64 with the two fields stored. The values differ from what the
    # budget rebuilds, so a recomputation is caught.
    budget = random_budget()
    stored_release = np.arange(N_STEPS * N_CELLS, dtype="float64").reshape(N_STEPS, N_CELLS)
    stored_unit = stored_release / 7.0 + 0.1
    derived = {"release_flux": stored_release, "budget_flux_per_area": stored_unit}
    with sealed_run(project, budget, derived=derived, precision="exact") as (catalog, sid):
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


# Every field against what the code before the rebuild derived.


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
    store = open_store(project, "run", precision="exact")
    yield store
    store.close()


@pytest.fixture(autouse=True)
def fresh_descent_cache():
    accumulation._graphs.clear()
    yield
    accumulation._graphs.clear()


def field_of(key: str) -> str:
    """Return the field a fixture array holds."""
    field = key.split("__", 1)[1]
    return RENAMED_IN_THE_FIXTURES.get(field, field)


def reference_cases() -> list[tuple[str, str]]:
    """Return (store, array name) for each stack the base code derived and a reader rebuilds.

    ``virtual__outflow_drain`` is the base per-step read, which took the drain
    term alone, so it is checked apart. The base wrote an unrouted local flux for
    a store with no descent, which a reader never serves.
    """
    cases = []
    for kind in reference.STORE_KINDS:
        with np.load(reference.fixture_path(kind)) as archive:
            for key in archive.files:
                if key.startswith("route__") or key == "virtual__outflow_drain":
                    continue
                if kind == "no_route" and field_of(key) in NO_ROUTE_FIELDS:
                    continue
                cases.append((kind, key))
    return cases


def without_guess(mass_seepage: np.ndarray) -> np.ndarray:
    stack = np.array(mass_seepage)
    stack[4] = stack[4] * 0.0
    return stack


def reference_stack(kind: str, key: str) -> np.ndarray:
    """Return what the base derived, without the step its sign guess read as an outflow.

    Step 4 of the drain is all positive. The base took that for an outflow when it read
    the drain alone, which only the solute chain does on these stores. A positive flux
    enters the aquifer, so no solute leaves at that step.
    """
    with np.load(reference.fixture_path(kind)) as archive:
        if key == "base__mass_seepage":
            return without_guess(archive[key])
        if key == "base__mass_accumulated":
            return np.cumsum(without_guess(archive["base__mass_seepage"]), axis=0)
        return archive[key]


@pytest.mark.parametrize(("kind", "key"), reference_cases())
def test_step_equals_row_of_range(built, kind, key):
    store = built(kind)
    sid = store.sim_id
    field = field_of(key)
    expected = reference_stack(kind, key)

    for step in range(reference.N_STEPS):
        np.testing.assert_array_equal(
            read_field_or_virtual(store, sid, field, step), expected[step]
        )
    np.testing.assert_array_equal(read_field_or_virtual(store, sid, field, -1), expected[-1])


@pytest.mark.parametrize(("kind", "key"), reference_cases())
def test_passes_join_into_the_range(built, monkeypatch, kind, key):
    # The running sum of mass_seepage_running_sum carries over from one pass to the next.
    store = built(kind)
    monkeypatch.setattr(virtual_fields, "ROWS_PER_PASS_ELEMENTS", reference.N_CELLS)

    rebuilt = read_field_range_or_virtual(store, store.sim_id, field_of(key), 0, reference.N_STEPS)

    np.testing.assert_array_equal(rebuilt, reference_stack(kind, key))


def test_virtual_field_names():
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


def test_step_outside_the_time_axis(built):
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


def test_geometric_fallback_warns_once(built, caplog, monkeypatch):
    store = built("boussinesq_no_excess")
    sid = store.sim_id
    sz = store.open_zarr(sid)
    try:
        sz.write_field_stack("concentration", np.ones((reference.N_STEPS, reference.N_CELLS)))
    finally:
        sz.close()
    monkeypatch.setattr(virtual_fields, "ROWS_PER_PASS_ELEMENTS", reference.N_CELLS)

    with caplog.at_level(logging.WARNING, logger="hydromodpy.catchment.drainage.graph"):
        read_field_range_or_virtual(store, sid, "mass_seepage_running_sum", 0, reference.N_STEPS)

    warnings = [r for r in caplog.records if "geometric criterion" in r.getMessage()]
    assert len(warnings) == 1


# A run written before: the stored array is read first, upstream too.


def write_derived(store: RunStore, sid: str, name: str, values: np.ndarray) -> None:
    sz = store.open_zarr(sid)
    try:
        sz.write_field_stack(name, values, subgroup="derived")
    finally:
        sz.close()


def read_group_array(store: RunStore, sid: str, group: str, name: str) -> np.ndarray:
    sz = store.open_zarr(sid)
    try:
        return np.asarray(sz.root[group][name][:], dtype="float64")
    finally:
        sz.close()


def test_old_water_table_feeds_depth_and_seepage(built):
    store = built("mf6")
    sid = store.sim_id
    stored = np.linspace(15.0, 30.0, reference.N_STEPS * reference.N_CELLS).reshape(
        reference.N_STEPS, reference.N_CELLS
    )
    write_derived(store, sid, "watertable_elevation", stored)
    top = read_group_array(store, sid, "mesh", "topography")
    expected_depth = np.maximum(top - stored, 0.0)
    expected_seepage = (stored >= top - 0.5 * reference.BAND_DEPTH_M).astype("float64")

    depth = read_field_range_or_virtual(store, sid, "watertable_depth", 0, reference.N_STEPS)
    seepage = read_field_range_or_virtual(store, sid, "seepage_mask", 0, reference.N_STEPS)

    np.testing.assert_array_equal(depth, expected_depth)
    np.testing.assert_array_equal(seepage, expected_seepage)
    np.testing.assert_array_equal(
        read_field_or_virtual(store, sid, "watertable_depth", 3), expected_depth[3]
    )


def test_old_concentration_and_mass_feed_the_next(built):
    store = built("transport")
    sid = store.sim_id
    shape = (reference.N_STEPS, reference.N_CELLS)
    stored_concentration = np.arange(np.prod(shape), dtype="float64").reshape(shape) / 7.0
    write_derived(store, sid, "concentration_seepage", stored_concentration)
    drain = read_group_array(store, sid, "budget", "drain")
    flux = budget_outflow_stack(drain, n_cells=reference.N_CELLS)

    mass = read_field_range_or_virtual(store, sid, "mass_seepage", 0, reference.N_STEPS)

    np.testing.assert_array_equal(mass, stored_concentration * flux)

    stored_mass = np.arange(np.prod(shape), dtype="float64").reshape(shape) * 0.1
    write_derived(store, sid, "mass_seepage", stored_mass)

    total = read_field_range_or_virtual(
        store, sid, "mass_seepage_running_sum", 0, reference.N_STEPS
    )

    np.testing.assert_array_equal(total, np.cumsum(stored_mass, axis=0))
    np.testing.assert_array_equal(
        read_field_or_virtual(store, sid, "mass_seepage_running_sum", 4), total[4]
    )


def write_flat_run(sz, concentration, recharge=None) -> None:
    sz.write_topography(np.full(N_CELLS, 100.0))
    sz.write_field_stack("head", np.full((N_STEPS, 1, N_CELLS), 101.0))
    sz.write_field_stack("concentration", concentration)
    if recharge is not None:
        sz.write_field_stack("recharge", recharge, subgroup="budget")


def test_mass_without_a_drain_term(exact_store):
    store = exact_store
    sz = store.open_zarr(store.sim_id)
    try:
        write_flat_run(
            sz, np.full((N_STEPS, 1, N_CELLS), 2.0), np.full((N_STEPS, 1, N_CELLS), 1e-4)
        )
    finally:
        sz.close()

    mass = read_field_range_or_virtual(store, store.sim_id, "mass_seepage", 0, N_STEPS)

    np.testing.assert_array_equal(mass, np.full((N_STEPS, N_CELLS), 2.0))


def test_mass_chain_needs_a_budget_group(exact_store):
    store = exact_store
    sid = store.sim_id
    sz = store.open_zarr(sid)
    try:
        write_flat_run(sz, np.ones((N_STEPS, 1, N_CELLS)))
        listed = available_virtual_fields(sz.root)
    finally:
        sz.close()

    assert "concentration_seepage" in listed
    assert "mass_seepage" not in listed
    assert "mass_seepage_running_sum" not in listed
    with pytest.raises(KeyError):
        read_field_range_or_virtual(store, sid, "mass_seepage", 0, N_STEPS)


def test_golden_signature_reads_the_time_axis(built):
    store = built("transport")
    sid = store.sim_id

    stored = store_field_signature(store, sid, "head")
    rebuilt = store_field_signature(store, sid, "mass_seepage_running_sum")

    assert stored["available_timesteps"] == reference.N_STEPS
    assert stored["timestep"] == reference.N_STEPS - 1
    assert stored["shape"] == [2 * reference.N_CELLS]
    assert rebuilt["available_timesteps"] == reference.N_STEPS
    last = reference_stack("transport", "base__mass_accumulated")[-1]
    assert rebuilt["count"] == int(np.isfinite(last).sum())
    with pytest.raises(KeyError):
        store_field_signature(store, sid, "seepage_areas")
