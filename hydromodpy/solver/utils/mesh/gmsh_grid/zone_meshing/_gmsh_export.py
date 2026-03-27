"""Export helpers for reading and writing planar Gmsh meshes."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from hydromodpy.solver.utils.mesh.gmsh_grid.gmsh_planar_mesh import GmshPlanarMesh2D
from hydromodpy.solver.utils.mesh.gmsh_grid.gmsh_reader import (
    GmshCellBlock,
    GmshMeshData,
)

_PLANAR_GMSH_ELEMENT_TYPES = {
    2: ("triangle", 3),
    3: ("quadrilateral", 4),
}


def write_repository_compatible_mesh(gmsh, output_path: str | os.PathLike[str]) -> None:
    """Write one planar mesh in the ASCII MSH2 format expected by repo readers."""
    gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
    gmsh.option.setNumber("Mesh.Binary", 0)
    gmsh.write(str(output_path))


def build_runtime_planar_mesh_from_gmsh(
    gmsh,
    *,
    source_path: str | os.PathLike[str] | None = None,
) -> GmshPlanarMesh2D:
    """Capture one normalized planar mesh directly from one live Gmsh session."""
    node_tags, coords, _ = gmsh.model.mesh.getNodes()
    node_tags_arr = np.asarray(node_tags, dtype=int).reshape(-1)
    coords_arr = np.asarray(coords, dtype=float).reshape(-1, 3)
    if node_tags_arr.size != coords_arr.shape[0]:
        raise ValueError(
            "Live Gmsh node coordinates are inconsistent with returned node tags."
        )

    coords_by_tag = {
        int(tag): (float(coord[0]), float(coord[1]))
        for tag, coord in zip(node_tags_arr, coords_arr, strict=False)
    }
    element_types, _element_tags, element_nodes = gmsh.model.mesh.getElements(dim=2)

    used_node_tags: list[int] = []
    cell_blocks: list[GmshCellBlock] = []
    cell_kinds: set[str] = set()
    for element_type, flat_nodes in zip(
        np.asarray(element_types, dtype=int).reshape(-1),
        tuple(element_nodes),
        strict=False,
    ):
        block_spec = _PLANAR_GMSH_ELEMENT_TYPES.get(int(element_type))
        if block_spec is None:
            continue
        cell_type, nodes_per_cell = block_spec
        flat_nodes_arr = np.asarray(flat_nodes, dtype=int).reshape(-1)
        if flat_nodes_arr.size == 0:
            continue
        if flat_nodes_arr.size % nodes_per_cell != 0:
            raise ValueError(
                f"Live Gmsh {cell_type} block does not contain a whole number of cells."
            )
        cell_node_tags = flat_nodes_arr.reshape(-1, nodes_per_cell)
        used_node_tags.extend(int(tag) for tag in cell_node_tags.reshape(-1))
        cell_blocks.append(
            GmshCellBlock(
                cell_type=cell_type,
                connectivity=cell_node_tags,
            )
        )
        cell_kinds.add(cell_type)

    if not cell_blocks:
        raise ValueError(
            "Live Gmsh model does not contain supported 2D triangle/quadrilateral elements."
        )
    if len(cell_kinds) > 1:
        present = ", ".join(sorted(cell_kinds))
        raise ValueError(
            "Mixed 2D cell types are not supported in one planar mesh. "
            f"Found: {present}."
        )

    ordered_node_tags = sorted(set(int(tag) for tag in used_node_tags))
    missing_node_tags = [tag for tag in ordered_node_tags if tag not in coords_by_tag]
    if missing_node_tags:
        preview = ", ".join(str(tag) for tag in missing_node_tags[:5])
        raise ValueError(
            "Live Gmsh node coordinates are missing for at least one planar cell "
            f"node tag ({preview})."
        )

    node_index_by_tag = {
        int(tag): idx for idx, tag in enumerate(ordered_node_tags)
    }
    points_xy = np.asarray(
        [coords_by_tag[int(tag)] for tag in ordered_node_tags],
        dtype=float,
    )
    normalized_blocks = tuple(
        GmshCellBlock(
            cell_type=block.cell_type,
            connectivity=np.asarray(
                [
                    [node_index_by_tag[int(tag)] for tag in row]
                    for row in np.asarray(block.connectivity, dtype=int)
                ],
                dtype=int,
            ),
        )
        for block in cell_blocks
    )
    mesh_data = GmshMeshData(
        points_xy=points_xy,
        cell_blocks=normalized_blocks,
        source_path=None if source_path is None else Path(source_path).resolve(),
    )
    return GmshPlanarMesh2D.from_mesh_data(mesh_data)


__all__ = [
    "build_runtime_planar_mesh_from_gmsh",
    "write_repository_compatible_mesh",
]
