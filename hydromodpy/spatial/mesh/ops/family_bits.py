"""Family membership of the cells and edges of a cell mesh, as bit fields.

A run store keeps the line families of its mesh as two int32 bit fields: one per
cell, one per mesh edge. Bit ``k`` of a cell is set when the cell belongs to the
family ``k`` (``PlanarCellMesh.family_cells``). Bit ``k`` of an edge is set when
the edge lies on a face row of the face family ``k``.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.core.exceptions import MeshError
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh

__all__ = [
    "MAX_FAMILIES",
    "cell_family_bits",
    "cell_family_names",
    "edge_family_bits",
    "edge_family_names",
    "face_row_edges",
]

MAX_FAMILIES = 31
"""Bits an int32 field holds without touching the sign."""


def cell_family_names(cell_mesh: PlanarCellMesh) -> tuple[str, ...]:
    """Return the family names of the cell bit field, in order of first appearance.

    The families of the cell chains come first, then those of the face rows. A
    name met twice owns one bit.
    """
    names: dict[str, None] = {}
    for chain in cell_mesh.cell_chains:
        names.setdefault(chain.family)
    if cell_mesh.face_families is not None:
        for name in cell_mesh.face_families.names:
            names.setdefault(name)
    return _checked(tuple(names))


def edge_family_names(cell_mesh: PlanarCellMesh) -> tuple[str, ...]:
    """Return the family names of the edge bit field: the face family names."""
    if cell_mesh.face_families is None:
        return ()
    return _checked(cell_mesh.face_families.names)


def _checked(names: tuple[str, ...]) -> tuple[str, ...]:
    if len(names) > MAX_FAMILIES:
        raise MeshError(
            f"a mesh holds at most {MAX_FAMILIES} families in a bit field, got {len(names)}: "
            f"{list(names)}"
        )
    return names


def cell_family_bits(cell_mesh: PlanarCellMesh) -> np.ndarray:
    """Return the int32 family bit field of every cell."""
    bits = np.zeros(cell_mesh.n_cells, dtype=np.int32)
    for k, name in enumerate(cell_family_names(cell_mesh)):
        bits[cell_mesh.family_cells(name)] |= np.int32(1 << k)
    return bits


def face_row_edges(cell_mesh: PlanarCellMesh) -> np.ndarray:
    """Return, for every row of the face family table, the rank of its mesh edge.

    The rank indexes ``cell_mesh.geometry.edge_nodes``. A row whose two nodes are
    not an edge of the mesh is a topology error.
    """
    table = cell_mesh.face_families
    if table is None or table.n_rows == 0:
        return np.empty(0, dtype=np.int64)
    n_nodes = np.int64(cell_mesh.mesh.n_nodes)
    edge_nodes = cell_mesh.geometry.edge_nodes
    edge_keys = edge_nodes[:, 0] * n_nodes + edge_nodes[:, 1]
    row_keys = np.minimum(table.node_a, table.node_b) * n_nodes + np.maximum(
        table.node_a, table.node_b
    )
    rank = np.searchsorted(edge_keys, row_keys)
    rank_in_range = np.minimum(rank, edge_keys.size - 1)
    missing = (rank >= edge_keys.size) | (edge_keys[rank_in_range] != row_keys)
    if missing.any():
        row = int(np.flatnonzero(missing)[0])
        raise MeshError(
            f"face family row {row} ('{table.names[int(table.family[row])]}') joins nodes "
            f"({int(table.node_a[row])}, {int(table.node_b[row])}), which are not an edge of the mesh"
        )
    return rank.astype(np.int64)


def edge_family_bits(cell_mesh: PlanarCellMesh) -> np.ndarray:
    """Return the int32 family bit field of every mesh edge."""
    bits = np.zeros(cell_mesh.geometry.edge_nodes.shape[0], dtype=np.int32)
    table = cell_mesh.face_families
    if table is None or table.n_rows == 0:
        return bits
    _checked(table.names)
    row_bits = np.int32(1) << table.family.astype(np.int32)
    np.bitwise_or.at(bits, face_row_edges(cell_mesh), row_bits)
    return bits
