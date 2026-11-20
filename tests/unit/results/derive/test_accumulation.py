"""Drained and released water (m3/s per cell) summed down the descent D of the run.

``drain_accumulation_flux`` and ``release_accumulation_flux`` route a local
flux down D, the descent stored under ``mesh/``. A run stored before D was gets
one rebuilt from its stored top, once per store. A run with neither serves no
accumulation at all.
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
# A bowl. Cell 10 (row 2, col 2) is the lowest, with a pit the steepest descent dies in.
TOP = np.array(
    [
        [9.0, 8.0, 7.0, 8.0],
        [8.0, 5.0, 4.0, 7.0],
        [7.0, 4.0, 1.0, 6.0],
        [6.0, 5.0, 4.0, 5.0],
    ]
)
PIT = 10


@pytest.fixture(autouse=True)
def _empty_graph_cache():
    accumulation._graphs.clear()
    yield
    accumulation._graphs.clear()


def random_budget() -> dict[str, np.ndarray]:
    rng = np.random.default_rng(3)
    return {
        "drain": -rng.uniform(0.0, 2e-3, (N_STEPS, 1, N_CELLS)),
        "stream": rng.uniform(-3e-3, 1e-3, (N_STEPS, 1, N_CELLS)),
    }


def pit_as_a_constant_head() -> np.ndarray:
    base_level = np.zeros(N_CELLS, dtype=bool)
    base_level[PIT] = True
    return base_level


def store_of_a_run(
    tmp_path: Path,
    budget: dict[str, np.ndarray] | None = None,
    *,
    descent=None,
    mesh: bool = True,
) -> SimulationZarr:
    """A run store. ``descent`` is the D to store, none for a run stored before D."""
    store = SimulationZarr.create(tmp_path / "run.zarr", n_cells=N_CELLS, n_layers=1)
    if mesh:
        vertices, connectivity = quad_mesh(NROW, NCOL)
        store.write_mesh(vertices, connectivity, np.array([10.0, 0.0]), topography=TOP.ravel())
    if descent is not None:
        store.write_descent(
            receiver=descent.receiver,
            surface=descent.surface,
            base_level=descent.base_level,
            constant_head=descent.constant_head,
            raised=descent.raised,
            channel=descent.channel,
            pinned=descent.pinned,
            attrs={},
        )
    store.write_field_stack("head", np.full((N_STEPS, 1, N_CELLS), 5.0))
    for name, values in (budget if budget is not None else random_budget()).items():
        store.write_field_stack(name, values, subgroup="budget")
    return store


def stored_term(store: SimulationZarr, name: str) -> np.ndarray:
    """A budget term as the store holds it (single precision), as ``(time, cell)``."""
    return np.asarray(store.root["budget"][name][:], dtype="float64")[:, 0, :]


def test_unavailable_without_d_or_topology(tmp_path: Path) -> None:
    store = store_of_a_run(tmp_path, mesh=False)

    assert not drain_accumulation_flux_available(store.root)
    assert not release_accumulation_flux_available(store.root)
    with pytest.raises(KeyError):
        drain_accumulation_flux_rows(store.root, 0, 1)
    with pytest.raises(KeyError):
        release_accumulation_flux_rows(store.root, 0, 1)
    store.close()


def test_a_single_step_is_a_row_of_the_range(tmp_path: Path) -> None:
    store = store_of_a_run(tmp_path)
    for rows_of in (drain_accumulation_flux_rows, release_accumulation_flux_rows):
        whole = rows_of(store.root, 0, N_STEPS)
        for step in range(N_STEPS):
            np.testing.assert_array_equal(rows_of(store.root, step, step + 1)[0], whole[step])
        np.testing.assert_array_equal(rows_of(store.root, 1, 4), whole[1:4])
    store.close()


def test_an_empty_range_has_no_row(tmp_path: Path) -> None:
    store = store_of_a_run(tmp_path)

    assert drain_accumulation_flux_rows(store.root, 2, 2).shape == (0, N_CELLS)
    assert release_accumulation_flux_rows(store.root, 3, 1).shape == (0, N_CELLS)
    store.close()


def test_release_routes_every_release_path(tmp_path: Path) -> None:
    store = store_of_a_run(tmp_path, descent=grid_descent(TOP))
    graph = grid_descent(TOP).metric.graph
    local = np.maximum(-stored_term(store, "drain"), 0.0)
    local += np.maximum(-stored_term(store, "stream"), 0.0)

    rows = release_accumulation_flux_rows(store.root, 0, N_STEPS)

    np.testing.assert_allclose(rows, accumulate_on_downhill_graph(graph, local), rtol=0, atol=1e-15)
    store.close()


def test_the_stored_d_wins_over_a_rebuild(tmp_path: Path) -> None:
    # The stored D holds a constant head in the pit, which no rebuild from the
    # top can know of. A reader that rebuilt D would send the flux to the rim.
    n_steps = 3
    flux = np.ones((n_steps, N_CELLS)) * np.arange(1, n_steps + 1)[:, None]  # 1, 2, 3 per cell
    descent = grid_descent(TOP, base_level=pit_as_a_constant_head())
    store = store_of_a_run(
        tmp_path, {"drain": -flux[:, None, :].astype("float32")}, descent=descent
    )

    accumulated = drain_accumulation_flux_rows(store.root, 0, n_steps)

    # The whole flux of the mesh leaves through the seeds of the stored D.
    outlets = descent.receiver < 0
    np.testing.assert_allclose(accumulated[:, outlets].sum(axis=1), flux.sum(axis=1))
    np.testing.assert_array_equal(
        accumulated, accumulate_on_downhill_graph(descent.metric.graph, flux)
    )
    assert descent.receiver[PIT] < 0 <= grid_descent(TOP).receiver[PIT]
    assert accumulated[0, PIT] > 1.0, "the neighbours of the pit send their flux into it"
    store.close()
