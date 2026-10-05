"""``accumulation_flux`` routes on the descent D the build stored, not on the raw top.

The top of this bowl holds a pit the steepest descent dies in, so a flux routed
on it never reaches the rim. D fills the pit and drains it: the whole flux of the
mesh leaves through the seed. The stored D holds a constant head in the pit,
which no rebuild from the top can know of, so the flux there stops in the pit:
a reader that rebuilt D instead of reading it would send it to the rim. A run
stored before D was gets one rebuilt from the stored top, and says so.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from types import SimpleNamespace

import numpy as np
import pytest
import zarr

from hydromodpy.core.field_routing import accumulate_on_downhill_graph
from hydromodpy.simulation.extraction.derivation.derived import (
    _accumulate_cell_stack_mesh_graph,
)
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


class _Store:
    """An in-memory store: one Zarr group, and the stacks it is asked to keep."""

    def __init__(self, *, with_descent: bool, with_connectivity: bool = True) -> None:
        self.root = zarr.group()
        mesh = self.root.create_group("mesh")
        vertices, connectivity = quad_mesh(4, 4)
        mesh.create_array("topography", data=TOP.ravel())
        if with_connectivity:
            mesh.create_array("face_node_connectivity", data=connectivity.astype("int32"))
            mesh.create_array("vertices", data=vertices)
        self.descent = grid_descent(TOP, base_level=_constant_head_in_the_pit())
        self.rebuilt = grid_descent(TOP)
        if with_descent:
            mesh.create_array("descent_receiver", data=self.descent.receiver)
            mesh.create_array("descent_surface", data=self.descent.surface)
        self.written: dict[str, np.ndarray] = {}

    def open_zarr(self, sim_id: str):
        return SimpleNamespace(root=self.root, close=lambda: None)

    def write_field_stack(self, sim_id, name, values, *, subgroup=None):
        self.written[name] = np.asarray(values)


def _flux() -> np.ndarray:
    return np.ones((N_STEPS, N_CELLS)) * np.arange(1, N_STEPS + 1)[:, None]


def test_the_whole_flux_leaves_through_the_seeds_of_the_stored_descent() -> None:
    store = _Store(with_descent=True)

    _accumulate_cell_stack_mesh_graph("s", store, _flux(), "accumulation_flux", N_STEPS, N_CELLS)

    accumulated = store.written["accumulation_flux"]
    receiver = store.descent.receiver
    outlets = receiver < 0
    np.testing.assert_allclose(accumulated[:, outlets].sum(axis=1), _flux().sum(axis=1))
    expected = accumulate_on_downhill_graph(store.descent.metric.graph, _flux())
    np.testing.assert_array_equal(accumulated, expected)
    assert receiver[PIT] < 0 <= store.rebuilt.receiver[PIT]
    assert accumulated[0, PIT] > 1.0, "the stored D sends its neighbours into the pit"


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


def test_a_run_with_no_stored_descent_routes_on_one_rebuilt_from_its_top(caplog) -> None:
    store = _Store(with_descent=False)

    with caplog.at_level(logging.INFO):
        _accumulate_cell_stack_mesh_graph(
            "old", store, _flux(), "accumulation_flux", N_STEPS, N_CELLS
        )

    accumulated = store.written["accumulation_flux"]
    np.testing.assert_array_equal(
        accumulated, accumulate_on_downhill_graph(store.rebuilt.metric.graph, _flux())
    )
    assert any(
        r.levelno == logging.INFO and "stores no descent" in r.getMessage() for r in caplog.records
    )


def test_a_store_with_a_descent_of_another_size_is_refused() -> None:
    store = _Store(with_descent=True)

    with pytest.raises(ValueError, match="expected"):
        _accumulate_cell_stack_mesh_graph("s", store, _flux(), "accumulation_flux", N_STEPS, 25)


def test_a_store_with_no_mesh_connectivity_is_left_to_the_raster_path() -> None:
    store = _Store(with_descent=False, with_connectivity=False)

    with pytest.raises(KeyError, match="mesh topology"):
        _accumulate_cell_stack_mesh_graph(
            "s", store, _flux(), "accumulation_flux", N_STEPS, N_CELLS
        )
