"""Reading a field over a range of steps, in one store opening, equals reading it step by step.

``Run.field`` reads one step and opens the store for it. ``field_range`` and ``field_steps``
open it once. Each row must be the step read, bit for bit, on a compact store. Heads are in m,
fluxes in m3/s, cell areas in m2.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.budget.terms import budget_terms_for
from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.derive import virtual_fields
from hydromodpy.results.derive.stream_network.run_extent import _release_rows
from hydromodpy.results.derive.virtual_fields import read_field_range_or_virtual
from hydromodpy.results.errors import FieldNotFoundError
from hydromodpy.results.run.geographic import field_range, field_steps
from hydromodpy.results.run.view import Run
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_stores import claim_run, facts_of

N_STEPS = 7
N_LAYERS = 2
AREAS = np.array([10.0, 20.0, 40.0, 80.0, 20.0])  # m2, unit-height rectangles
N_CELLS = AREAS.size
TOP = np.array([130.0, 128.0, 125.0, 121.0, 119.0])  # m


def row_of_rectangles():
    x = np.concatenate([[0.0], np.cumsum(AREAS)])
    vertices = np.array([[xi, 0.0, 0.0] for xi in x] + [[xi, 1.0, 0.0] for xi in x])
    n_x = x.size
    connectivity = np.array([[i, i + 1, n_x + i + 1, n_x + i] for i in range(N_CELLS)])
    return vertices, connectivity.astype("int32")


@contextmanager
def sealed_run(project: Path) -> Iterator[tuple[Catalog, str]]:
    """Seal a two-layer run with head, drain, stream and recharge, index it, yield the catalog and id."""
    rng = np.random.default_rng(11)
    claim = claim_run(project, "run")
    store = RunStore.open(
        claim.run_dir,
        facts=facts_of(claim, project="p", n_cells=N_CELLS, n_layers=N_LAYERS, n_timesteps=N_STEPS),
        persistence=PersistenceConfig(),
        workspace=project,
    )
    store.create_zarr(n_cells=N_CELLS, n_layers=N_LAYERS)
    sid = store.sim_id
    shape = (N_STEPS, N_LAYERS, N_CELLS)
    head = rng.uniform(110.0, 131.0, shape)
    head[:, 0, 1] = np.nan
    drain = -rng.uniform(0.0, 2e-3, shape)
    stream = rng.uniform(-3e-3, 1e-3, shape)
    recharge = rng.uniform(0.0, 1e-4, shape)
    vertices, connectivity = row_of_rectangles()
    zarr_store = store.open_zarr(sid)
    try:
        zarr_store.write_mesh(vertices, connectivity, np.array([150.0, 100.0, 50.0]))
        zarr_store.write_topography(TOP)
        zarr_store.write_field_stack("head", head)
        for name, values in (("drain", drain), ("stream", stream), ("recharge", recharge)):
            zarr_store.write_field_stack(name, values, subgroup="budget")
    finally:
        zarr_store.close()
    seal_completed(store)
    rebuild_index(project)
    with Catalog(project) as catalog:
        yield catalog, sid


@pytest.fixture
def seeded(tmp_path):
    with sealed_run(tmp_path / "workspace") as pair:
        yield pair


@pytest.fixture
def catalog(seeded):
    return seeded[0]


@pytest.fixture
def sid(seeded):
    return seeded[1]


def step_by_step(run, variable, steps, layer=None):
    return np.stack([run.field(variable, time=int(t), layer=layer) for t in steps])


def test_layer_range(catalog, sid):
    run = Run(sid, catalog)

    lower = field_range(run, "head", 1, 6, layer=1)

    assert lower.shape == (5, N_CELLS)
    np.testing.assert_array_equal(lower, step_by_step(run, "head", range(1, 6), layer=1))


def test_static_field_range(catalog, sid):
    run = Run(sid, catalog)

    np.testing.assert_array_equal(
        field_range(run, "topography", 0, 3), step_by_step(run, "topography", range(3))
    )


@pytest.mark.parametrize("variable", ["release_flux", "budget_flux_per_area"])
def test_rebuilt_field_range(catalog, sid, variable):
    run = Run(sid, catalog)

    whole = field_range(run, variable, 0, N_STEPS)

    assert whole.shape == (N_STEPS, N_CELLS)
    np.testing.assert_array_equal(whole, step_by_step(run, variable, range(N_STEPS)))
    np.testing.assert_array_equal(
        field_range(run, variable, 3, 6), step_by_step(run, variable, range(3, 6))
    )


def test_network_graph_built_once(catalog, sid, monkeypatch):
    calls = []

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


@pytest.mark.parametrize("variable", ["no_such_field", "mass_seepage_running_sum"])
def test_unknown_field_errors(catalog, sid, variable):
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
    if budget_terms_for(variable):
        assert "run the simulation again" in str(by_range.value)


# A slice would hand back fewer rows than asked, so the range refuses instead.
@pytest.mark.parametrize("variable", ["head", "release_flux", "watertable_elevation"])
@pytest.mark.parametrize(
    ("start", "stop"), [(0, N_STEPS + 1), (4, 2), (-N_STEPS - 1, 2), (N_STEPS + 1, N_STEPS + 2)]
)
def test_range_off_time_axis(catalog, sid, variable, start, stop):
    with pytest.raises(IndexError):
        read_field_range_or_virtual(catalog, sid, variable, start, stop)


def test_step_off_time_axis(catalog, sid):
    with pytest.raises(IndexError):
        catalog.query_field(sid, "head", N_STEPS)
    with pytest.raises(IndexError):
        field_range(Run(sid, catalog), "head", N_STEPS - 1, N_STEPS + 1)


@pytest.mark.parametrize(
    "steps", [[0, 1, 2, 3, 4, 5, 6], [0, 1, 2, 4], [5, 1, 2, 3, 0], [3], [6, 5, 4]]
)
def test_release_rows(catalog, sid, steps):
    run = Run(sid, catalog)

    rows = _release_rows(run, np.asarray(steps), N_CELLS)

    np.testing.assert_array_equal(rows, step_by_step(run, "release_flux", steps))


def test_release_rows_cell_count(catalog, sid):
    with pytest.raises(ValueError, match="not written for the same run"):
        _release_rows(Run(sid, catalog), np.arange(3), N_CELLS + 1)


@pytest.mark.parametrize("steps", [[-2, -1], [-1, 0, 1, 2], [6, -1, 4, 5]])
def test_negative_steps(catalog, sid, steps):
    run = Run(sid, catalog)

    np.testing.assert_array_equal(
        field_steps(run, "release_flux", steps), step_by_step(run, "release_flux", steps)
    )
