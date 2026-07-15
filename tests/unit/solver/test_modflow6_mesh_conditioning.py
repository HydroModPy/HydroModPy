"""Priority-flood conditioning of the DISV mesh top surface."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from hydromodpy.solver.modflow6.mesh_conditioning import condition_solver_mesh_top
from hydromodpy.spatial.mesh.model.cell_adjacency import build_planar_cell_adjacency


@dataclass(frozen=True)
class _StubMesh:
    """Minimal frozen stand-in for SolverMesh (top + inactive_mask only)."""

    top: np.ndarray
    inactive_mask: np.ndarray


class _StubSupport:
    def __init__(self, edge_cell_a, edge_cell_b):
        self.edge_cell_a = np.asarray(edge_cell_a, dtype=int)
        self.edge_cell_b = np.asarray(edge_cell_b, dtype=int)


def _chain_support(n_active):
    """Linear chain 0-1-...-(n_active-1)-(inactive boundary)."""
    a, b = [], []
    for i in range(n_active - 1):
        a.append(i)
        b.append(i + 1)
    a.append(n_active - 1)  # last active cell borders the inactive boundary cell
    b.append(n_active)
    return _StubSupport(a, b)


def _interior_pits(top, adjacency, active):
    pits = []
    for c in range(len(top)):
        if not active[c]:
            continue
        if any(not active[n] for n in adjacency[c]):
            continue  # boundary cell drains off-grid
        if all(top[n] > top[c] + 1e-6 for n in adjacency[c] if active[n]):
            pits.append(c)
    return pits


class _RaggedMesh:
    """Planar mesh exposing ragged per-cell node lists (Voronoi-style)."""

    def __init__(self, cells):
        self.flat_connectivity = tuple(np.asarray(c, dtype=int) for c in cells)


def test_adjacency_falls_back_to_ragged_polygon_connectivity():
    # 2x2 quad grid; edge neighbours only (diagonal cells 0-3 share a vertex, not
    # an edge, so they are not adjacent).
    mesh = _RaggedMesh([[0, 1, 4, 3], [1, 2, 5, 4], [3, 4, 7, 6], [4, 5, 8, 7]])
    adj = build_planar_cell_adjacency(mesh, 4, None)
    assert [sorted(s) for s in adj] == [[1, 2], [0, 3], [0, 3], [1, 2]]


def test_adjacency_ignores_out_of_range_support_edges_and_falls_back():
    # A Voronoi dual's runtime edges index the finer triangulation, so their cell
    # ids overrun n_cells; the builder must ignore them and rebuild from polygons.
    mesh = _RaggedMesh([[0, 1, 4, 3], [1, 2, 5, 4], [3, 4, 7, 6], [4, 5, 8, 7]])
    support = _StubSupport([10, 11], [12, 13])  # all >= n_cells = 4
    adj = build_planar_cell_adjacency(mesh, 4, support)
    assert [sorted(s) for s in adj] == [[1, 2], [0, 3], [0, 3], [1, 2]]


def test_adjacency_rejects_partly_in_range_support_wholesale():
    # The real Voronoi bug: half the triangulation ids still fall below n_cells, so
    # a per-edge bounds check would keep a WRONG (triangle) partial topology. Any id
    # out of range must reject the whole incidence and rebuild from polygons.
    mesh = _RaggedMesh([[0, 1, 4, 3], [1, 2, 5, 4], [3, 4, 7, 6], [4, 5, 8, 7]])
    # a bogus in-range edge (0-3, diagonal, not a real neighbour) mixed with an
    # out-of-range one; the in-range one must NOT leak into the result.
    support = _StubSupport([0, 2], [3, 99])
    adj = build_planar_cell_adjacency(mesh, 4, support)
    assert [sorted(s) for s in adj] == [[1, 2], [0, 3], [0, 3], [1, 2]]
    assert 3 not in adj[0]  # the bogus 0-3 diagonal edge did not leak in


def test_fills_interior_pit_so_it_drains():
    # cell 2 (top 5) sits below both neighbours (8 and 7): a closed pit.
    top = np.array([10.0, 8.0, 5.0, 7.0, 3.0, -9999.0])
    inactive = np.array([[False, False, False, False, False, True]])
    mesh = _StubMesh(top=top, inactive_mask=inactive)
    support = _chain_support(5)

    active = ~inactive[0]
    adj = build_planar_cell_adjacency(None, len(top), support)
    assert _interior_pits(top, adj, active) == [2]

    new_mesh, info = condition_solver_mesh_top(mesh, support, epsilon=1e-3)

    assert _interior_pits(new_mesh.top, adj, active) == []
    assert new_mesh.top[2] > top[2]  # pit was raised
    assert info["cells_raised"] >= 1
    assert info["unreached_active"] == 0
    # the outlet (lowest, boundary) and the high cells are untouched
    assert new_mesh.top[4] == pytest.approx(3.0)
    assert new_mesh.top[0] == pytest.approx(10.0)


def test_protected_cells_are_never_raised():
    # cell 2 is a marnage lake bed (low on purpose) and must stay put.
    top = np.array([10.0, 8.0, 5.0, 7.0, 3.0, -9999.0])
    inactive = np.array([[False, False, False, False, False, True]])
    mesh = _StubMesh(top=top, inactive_mask=inactive)
    support = _chain_support(5)

    new_mesh, info = condition_solver_mesh_top(mesh, support, protected_cells={2}, epsilon=1e-3)

    assert new_mesh.top[2] == pytest.approx(5.0)  # protected, unchanged
    # cell 3 can now drain into the protected low cell 2, so it is not raised
    assert info["cells_raised"] == 0


def test_botm_is_untouched_only_top_changes():
    top = np.array([10.0, 8.0, 5.0, 7.0, 3.0, -9999.0])
    botm = np.array([[0.0, 0.0, 0.0, 0.0, 0.0, -9999.0]])
    inactive = np.array([[False, False, False, False, False, True]])

    @dataclass(frozen=True)
    class _MeshWithBotm:
        top: np.ndarray
        botm: np.ndarray
        inactive_mask: np.ndarray

    mesh = _MeshWithBotm(top=top, botm=botm, inactive_mask=inactive)
    new_mesh, _ = condition_solver_mesh_top(mesh, _chain_support(5), epsilon=1e-3)
    assert np.array_equal(new_mesh.botm, botm)
    assert new_mesh.top[2] > top[2]


def test_isolated_basin_reports_unreached():
    # two active cells, neither touches the inactive boundary and no protected
    # seed: the flood can never start, so both stay unreachable.
    top = np.array([5.0, 4.0])
    inactive = np.array([[False, False]])
    mesh = _StubMesh(top=top, inactive_mask=inactive)
    support = _StubSupport([0], [1])  # single interior edge, no boundary edge

    _, info = condition_solver_mesh_top(mesh, support)
    assert info["unreached_active"] == 2
    assert info["cells_raised"] == 0
