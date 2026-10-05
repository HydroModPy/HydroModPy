"""Cell adjacency of a planar mesh: polygon edges, never a mismatched support."""

from __future__ import annotations

import numpy as np

from hydromodpy.spatial.mesh.model.cell_adjacency import build_planar_cell_adjacency


class _StubSupport:
    def __init__(self, edge_cell_a, edge_cell_b):
        self.edge_cell_a = np.asarray(edge_cell_a, dtype=int)
        self.edge_cell_b = np.asarray(edge_cell_b, dtype=int)


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
