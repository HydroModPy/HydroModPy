"""A cell mesh keeps its line families as bit fields over cells and edges.

The mesh is two rows of three cells. The river chain runs along the top row, a
lake face separates cell 1 from cell 4, and the west boundary closes cell 3.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from hydromodpy.core.exceptions import MeshError
from hydromodpy.mesh.planar.planar_cell_mesh import CellChain, FaceFamilyTable, PlanarCellMesh
from hydromodpy.results.zarr_store.mesh_layout import (
    MAX_FAMILIES,
    cell_family_bits,
    cell_family_names,
    edge_family_bits,
    edge_family_names,
    face_row_edges,
)
from tests._helpers.mesh_cases import regular_mesh


def _edge_between(cell_mesh: PlanarCellMesh, cell_a: int, cell_b: int) -> tuple[int, int, int]:
    """Return the rank and the two nodes of the edge shared by two cells (-1 for the boundary)."""
    geometry = cell_mesh.geometry
    rank = int(np.flatnonzero((geometry.edge_cells == [cell_a, cell_b]).all(axis=1))[0])
    node_a, node_b = geometry.edge_nodes[rank]
    return rank, int(node_a), int(node_b)


def _mesh_with_families() -> tuple[PlanarCellMesh, dict[str, int]]:
    base = regular_mesh(2, 3, dx=10.0)
    lake_rank, lake_a, lake_b = _edge_between(base, 1, 4)
    west_rank, west_a, west_b = _edge_between(base, 3, -1)
    table = FaceFamilyTable(
        names=("lakes", "boundary:west"),
        family=[0, 1],
        cell_a=[1, 3],
        cell_b=[4, -1],
        node_a=[lake_a, west_a],
        node_b=[lake_b, west_b],
        zone_left=[-1, -1],
        zone_right=[-1, -1],
    )
    chain = CellChain(family="rivers", chain_id=0, cell_ids=np.array([0, 1, 2]))
    mesh = dataclasses.replace(base, cell_chains=(chain,), face_families=table)
    return mesh, {"lake": lake_rank, "west": west_rank}


def test_a_face_row_off_the_mesh_edges_is_a_topology_error():
    cell_mesh, _ = _mesh_with_families()
    table = cell_mesh.face_families
    # nodes 0 and 11 are the two far corners of the grid: never an edge
    broken = dataclasses.replace(table, node_a=[0, table.node_a[1]], node_b=[11, table.node_b[1]])

    with pytest.raises(MeshError, match="not an edge of the mesh"):
        face_row_edges(dataclasses.replace(cell_mesh, face_families=broken))


def test_a_mesh_without_family_has_empty_bit_fields():
    base = regular_mesh(2, 3, dx=10.0)

    assert cell_family_names(base) == ()
    assert not cell_family_bits(base).any()
    assert edge_family_names(base) == ()
    assert not edge_family_bits(base).any()
    assert face_row_edges(base).size == 0


def test_more_families_than_an_int32_holds_is_refused():
    base = regular_mesh(2, 3, dx=10.0)
    chains = tuple(
        CellChain(family=f"line_{k}", chain_id=k, cell_ids=np.array([0]))
        for k in range(MAX_FAMILIES + 1)
    )

    with pytest.raises(MeshError, match=f"at most {MAX_FAMILIES} families"):
        cell_family_bits(dataclasses.replace(base, cell_chains=chains))
