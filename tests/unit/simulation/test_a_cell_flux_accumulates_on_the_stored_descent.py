"""``accumulation_flux`` routes on the descent D the build stored, not on the raw top.

The top of this bowl holds a pit the steepest descent dies in, so a flux routed
on it never reaches the rim. D fills the pit and drains it: the whole flux of the
mesh leaves through the seed. The stored D holds a constant head in the pit,
which no rebuild from the top can know of, so the flux there stops in the pit:
a reader that rebuilt D instead of reading it would send it to the rim. The
cases of a run stored without D are in
``tests/unit/results/test_accumulation_rebuilt_on_read.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from hydromodpy.core.field_routing import accumulate_on_downhill_graph
from hydromodpy.results.derive import accumulation
from hydromodpy.results.derive.accumulation import accumulation_flux_rows
from hydromodpy.results.zarr_store import SimulationZarr
from tests._helpers.ugrid_meshes import quad_mesh
from tests.unit.core._descent_meshes import grid_descent

TOP = np.array(
    [
        [9.0, 8.0, 7.0, 8.0],
        [8.0, 5.0, 4.0, 7.0],
        [7.0, 4.0, 1.0, 6.0],
        [6.0, 5.0, 4.0, 5.0],
    ]
)
N_CELLS = TOP.size
N_STEPS = 3
PIT = 10


def _constant_head_in_the_pit() -> np.ndarray:
    base_level = np.zeros(N_CELLS, dtype=bool)
    base_level[PIT] = True
    return base_level


def _flux() -> np.ndarray:
    return np.ones((N_STEPS, N_CELLS)) * np.arange(1, N_STEPS + 1)[:, None]


def _store_with_the_pit_as_a_seed(tmp_path: Path) -> SimulationZarr:
    """A store whose drain is the unit flux per step and whose D keeps the pit as a seed."""
    store = SimulationZarr.create(tmp_path / "run.zarr", n_cells=N_CELLS, n_layers=1)
    vertices, connectivity = quad_mesh(4, 4)
    store.write_mesh(vertices, connectivity, np.array([10.0, 0.0]), topography=TOP.ravel())
    built = grid_descent(TOP, base_level=_constant_head_in_the_pit())
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
    store.write_field_stack(
        "head",
        np.full((N_STEPS, 1, N_CELLS), 5.0),
    )
    store.write_field_stack("drain", -_flux()[:, None, :].astype("float32"), subgroup="budget")
    return store


def test_the_whole_flux_leaves_through_the_seeds_of_the_stored_descent(tmp_path: Path) -> None:
    accumulation._graphs.clear()
    store = _store_with_the_pit_as_a_seed(tmp_path)
    descent = grid_descent(TOP, base_level=_constant_head_in_the_pit())

    accumulated = accumulation_flux_rows(store.root, 0, N_STEPS)

    outlets = descent.receiver < 0
    np.testing.assert_allclose(accumulated[:, outlets].sum(axis=1), _flux().sum(axis=1))
    expected = accumulate_on_downhill_graph(descent.metric.graph, _flux())
    np.testing.assert_array_equal(accumulated, expected)
    assert descent.receiver[PIT] < 0 <= grid_descent(TOP).receiver[PIT]
    assert accumulated[0, PIT] > 1.0, "the stored D sends its neighbours into the pit"
    store.close()


def test_the_steepest_descent_of_the_raw_top_ends_in_the_pit_and_d_ends_on_the_rim() -> None:
    from hydromodpy.core.field_routing import build_downhill_graph

    vertices, connectivity = quad_mesh(4, 4)
    raw = build_downhill_graph(TOP.ravel(), connectivity, vertices=vertices)
    rim = np.ones((4, 4), dtype=bool)
    rim[1:3, 1:3] = False

    pit = np.flatnonzero(raw.downstream < 0)
    outlets = np.flatnonzero(grid_descent(TOP).receiver < 0)

    assert pit.tolist() == [10], "every path of the raw top ends in the interior pit"
    assert not rim.ravel()[pit].any()
    assert rim.ravel()[outlets].all(), "D lets the water out through the rim"
