"""``build_network_geometry`` must not rebuild the adjacency it already paid for.

Given a delineated catchment, the function builds the neighbour graph once to
flood it (:func:`fill_depressions_on_graph`) before descending it. Handing that
same graph to the downslope metric instead of letting it rebuild its own is
what makes ``diagonal_neighbors=True`` affordable on a real mesh: two probes
meant to compare a D4 and a D8 descent both exhausted memory rebuilding the
eight-neighbour graph a second time, on two different DEMs.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest

import hydromodpy.core.field_routing as field_routing_module
import hydromodpy.core.stream_geometry as stream_geometry_module
import hydromodpy.core.topographic_distance as topographic_distance_module
from hydromodpy.core.stream_geometry import NetworkGeometry, build_network_geometry
from tests._helpers.ugrid_meshes import quad_mesh

N_ROWS = 6
N_COLS = 4
N_CELLS = N_ROWS * N_COLS
CELL_SIZE = 10.0


def _ramp() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A surface with no depression at all: every cell already has a strictly lower neighbour."""
    vertices, connectivity = quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)
    rows = np.repeat(np.arange(N_ROWS, dtype=float), N_COLS)
    elevation = 100.0 - rows
    return vertices, connectivity, elevation


def _build(*, diagonal_neighbors: bool, delineated_catchment: np.ndarray | None) -> NetworkGeometry:
    vertices, connectivity, elevation = _ramp()
    observed = np.zeros(N_CELLS, dtype=bool)
    observed[(N_ROWS - 1) * N_COLS :] = True
    return build_network_geometry(
        topography=elevation,
        face_node_connectivity=connectivity,
        vertices=vertices,
        observed=observed,
        cell_area_m2=np.full(N_CELLS, CELL_SIZE * CELL_SIZE),
        mean_recharge_m_s=1e-8,
        tau_specific_ratio=1e-4,
        delineated_catchment=delineated_catchment,
        diagonal_neighbors=diagonal_neighbors,
    )


def _counting(
    original: Callable[..., list[set[int]]],
) -> tuple[dict[str, int], Callable[..., list[set[int]]]]:
    """A wrapper that still does the real construction, but counts the calls."""
    calls = {"n": 0}

    def wrapper(*args: object, **kwargs: object) -> list[set[int]]:
        calls["n"] += 1
        return original(*args, **kwargs)

    return calls, wrapper


class TestTheAdjacencyIsBuiltOnce:
    def test_the_diagonal_adjacency_is_built_once_not_twice(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls, wrapper = _counting(topographic_distance_module.shared_node_adjacency)
        monkeypatch.setattr(stream_geometry_module, "shared_node_adjacency", wrapper)
        monkeypatch.setattr(topographic_distance_module, "shared_node_adjacency", wrapper)

        _build(diagonal_neighbors=True, delineated_catchment=np.ones(N_CELLS, dtype=bool))

        assert calls["n"] == 1

    def test_the_shared_edge_adjacency_is_built_once_not_twice(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls, wrapper = _counting(field_routing_module.cell_adjacency_from_face_connectivity)
        monkeypatch.setattr(
            stream_geometry_module, "cell_adjacency_from_face_connectivity", wrapper
        )
        monkeypatch.setattr(field_routing_module, "cell_adjacency_from_face_connectivity", wrapper)

        _build(diagonal_neighbors=False, delineated_catchment=np.ones(N_CELLS, dtype=bool))

        assert calls["n"] == 1

    def test_without_a_catchment_nothing_is_built_early_to_reuse(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No flood runs without a delineated catchment, so the metric builds its own."""
        calls, wrapper = _counting(topographic_distance_module.shared_node_adjacency)
        monkeypatch.setattr(topographic_distance_module, "shared_node_adjacency", wrapper)

        _build(diagonal_neighbors=True, delineated_catchment=None)

        assert calls["n"] == 1


class TestTheGraphFollowsTheAdjacencyItWasGiven:
    def test_a_disconnected_adjacency_strands_the_descent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The graph the metric descends must be the one the flood just used.

        The ramp has no depression, so a disconnected adjacency changes nothing
        for the flood: this isolates the one place left where the adjacency
        can still matter, the metric. If the descent still reaches the whole
        catchment despite it, the metric rebuilt its own, correct graph instead
        of receiving this one, which is the bug this file pins.
        """
        catchment = np.ones(N_CELLS, dtype=bool)
        baseline = _build(diagonal_neighbors=True, delineated_catchment=catchment)
        assert baseline.frac_reachable_obs_raw == pytest.approx(1.0)

        def _disconnected(face_node_connectivity: np.ndarray, *, n_cells: int) -> list[set[int]]:
            return [set() for _ in range(n_cells)]

        monkeypatch.setattr(stream_geometry_module, "shared_node_adjacency", _disconnected)

        broken = _build(diagonal_neighbors=True, delineated_catchment=catchment)

        assert broken.frac_reachable_obs_raw < 0.5
