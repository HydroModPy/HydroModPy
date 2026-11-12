"""``drain_accumulation_flux`` and ``release_accumulation_flux`` are rebuilt on read.

Both route a local flux down the descent D of the run. D is the one stored
under ``mesh/``; a run stored before D was gets one rebuilt from its stored
top, once per store, and a run with neither serves no accumulation at all.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.catchment.drainage.graph import accumulate_on_downhill_graph
from hydromodpy.results.derive import accumulation
from hydromodpy.results.derive.accumulation import (
    drain_accumulation_flux_available,
    drain_accumulation_flux_rows,
    release_accumulation_flux_available,
    release_accumulation_flux_rows,
)
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from tests._helpers.descent_cases import grid_descent
from tests._helpers.ugrid_meshes import quad_mesh

NROW = NCOL = 4
N_CELLS = NROW * NCOL
N_STEPS = 5
TOP = np.array(
    [
        [9.0, 8.0, 7.0, 8.0],
        [8.0, 5.0, 4.0, 7.0],
        [7.0, 4.0, 1.0, 6.0],
        [6.0, 5.0, 4.0, 5.0],
    ]
)


@pytest.fixture(autouse=True)
def _empty_graph_cache():
    accumulation._graphs.clear()
    yield
    accumulation._graphs.clear()


def _budget() -> dict[str, np.ndarray]:
    rng = np.random.default_rng(3)
    return {
        "drain": -rng.uniform(0.0, 2e-3, (N_STEPS, 1, N_CELLS)),
        "stream": rng.uniform(-3e-3, 1e-3, (N_STEPS, 1, N_CELLS)),
    }


def _store(
    tmp_path: Path,
    budget: dict[str, np.ndarray] | None = None,
    *,
    descent: bool = False,
    mesh: bool = True,
) -> SimulationZarr:
    store = SimulationZarr.create(tmp_path / "run.zarr", n_cells=N_CELLS, n_layers=1)
    if mesh:
        vertices, connectivity = quad_mesh(NROW, NCOL)
        store.write_mesh(vertices, connectivity, np.array([10.0, 0.0]), topography=TOP.ravel())
    if descent:
        built = grid_descent(TOP)
        store.write_descent(
            receiver=built.receiver,
            surface=built.surface,
            base_level=built.base_level,
            constant_head=built.constant_head,
            raised=built.raised,
            channel=built.channel,
            pinned=built.pinned,
            attrs={},
        )
    store.write_field_stack("head", np.full((N_STEPS, 1, N_CELLS), 5.0))
    for name, values in (budget if budget is not None else _budget()).items():
        store.write_field_stack(name, values, subgroup="budget")
    return store


def _stored(store: SimulationZarr, name: str) -> np.ndarray:
    """A budget term as the store holds it (single precision), as ``(time, cell)``."""
    return np.asarray(store.root["budget"][name][:], dtype="float64")[:, 0, :]


def test_without_d_and_without_topology_the_field_is_unavailable(tmp_path: Path) -> None:
    store = _store(tmp_path, mesh=False)

    assert not drain_accumulation_flux_available(store.root)
    assert not release_accumulation_flux_available(store.root)
    with pytest.raises(KeyError):
        drain_accumulation_flux_rows(store.root, 0, 1)
    with pytest.raises(KeyError):
        release_accumulation_flux_rows(store.root, 0, 1)
    store.close()


def test_a_single_step_equals_the_matching_row_of_a_range(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for rows_of in (drain_accumulation_flux_rows, release_accumulation_flux_rows):
        whole = rows_of(store.root, 0, N_STEPS)
        for step in range(N_STEPS):
            np.testing.assert_array_equal(rows_of(store.root, step, step + 1)[0], whole[step])
        np.testing.assert_array_equal(rows_of(store.root, 1, 4), whole[1:4])
    store.close()


def test_an_empty_range_has_no_row(tmp_path: Path) -> None:
    store = _store(tmp_path)

    assert drain_accumulation_flux_rows(store.root, 2, 2).shape == (0, N_CELLS)
    assert release_accumulation_flux_rows(store.root, 3, 1).shape == (0, N_CELLS)
    store.close()


def test_the_release_accumulation_routes_every_release_path(tmp_path: Path) -> None:
    store = _store(tmp_path, descent=True)
    graph = grid_descent(TOP).metric.graph
    local = np.maximum(-_stored(store, "drain"), 0.0) + np.maximum(-_stored(store, "stream"), 0.0)

    rows = release_accumulation_flux_rows(store.root, 0, N_STEPS)

    np.testing.assert_allclose(rows, accumulate_on_downhill_graph(graph, local), rtol=0, atol=1e-15)
    store.close()
