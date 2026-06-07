"""Export helpers for reading and writing planar Gmsh meshes."""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from pathlib import Path

import numpy as np

from hydromodpy.spatial.mesh.gmsh_grid.gmsh_planar_mesh import GmshPlanarMesh2D
from hydromodpy.spatial.mesh.gmsh_grid.gmsh_reader import (
    GmshCellBlock,
    GmshMeshData,
)

_PLANAR_GMSH_ELEMENT_TYPES = {
    2: ("triangle", 3),
    3: ("quadrilateral", 4),
}
_WINDOWS_GMSH_PATH_LIMIT = 240


def write_repository_compatible_mesh(gmsh, output_path: str | os.PathLike[str]) -> None:
    """Write one planar mesh in the ASCII MSH2 format expected by repo readers."""
    output_path_obj = Path(output_path).resolve()
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)
    gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
    gmsh.option.setNumber("Mesh.Binary", 0)
    output_path_text = str(output_path_obj)
    if os.name == "nt" and len(output_path_text) >= _WINDOWS_GMSH_PATH_LIMIT:
        _write_mesh_via_short_windows_temp_path(gmsh, output_path_obj)
        return
    gmsh.write(output_path_text)


def _write_mesh_via_short_windows_temp_path(gmsh, output_path: Path) -> None:
    """Write through one short temp path when Gmsh cannot handle long paths."""
    scratch_dir = Path(tempfile.gettempdir()) / "hydromodpy_gmsh_export"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    temp_name = f"{output_path.stem[:32]}_{uuid.uuid4().hex[:8]}{output_path.suffix or '.msh'}"
    temp_path = scratch_dir / temp_name
    try:
        gmsh.write(str(temp_path))
        shutil.copyfile(
            str(temp_path),
            _as_windows_extended_length_path(output_path),
        )
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass


def _as_windows_extended_length_path(path: Path) -> str:
    """Return one Windows long-path-safe string for filesystem operations."""
    normalized = str(Path(path).resolve())
    if not normalized.startswith("\\\\?\\"):
        if normalized.startswith("\\\\"):
            return "\\\\?\\UNC\\" + normalized.lstrip("\\")
        return "\\\\?\\" + normalized
    return normalized


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
        raise ValueError("Live Gmsh node coordinates are inconsistent with returned node tags.")

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
            f"Mixed 2D cell types are not supported in one planar mesh. Found: {present}."
        )

    ordered_node_tags = sorted(set(int(tag) for tag in used_node_tags))
    missing_node_tags = [tag for tag in ordered_node_tags if tag not in coords_by_tag]
    if missing_node_tags:
        preview = ", ".join(str(tag) for tag in missing_node_tags[:5])
        raise ValueError(
            "Live Gmsh node coordinates are missing for at least one planar cell "
            f"node tag ({preview})."
        )

    node_index_by_tag = {int(tag): idx for idx, tag in enumerate(ordered_node_tags)}
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
