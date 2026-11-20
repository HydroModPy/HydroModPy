"""Round-trip conversion between ``HydroMesh`` and ``meshio`` meshes.

``meshio`` is the generic I/O backbone used by HydroModPy to access common
mesh file formats (VTU, MSH, XDMF, ...).  The goal of this module is to keep a
lossless-enough bridge for the information that HydroModPy itself cares about:

- points / vertices,
- cell connectivity,
- per-cell arrays,
- per-point arrays.

Unsupported ``meshio`` blocks such as line or vertex-only blocks are skipped
deliberately because they do not map to the ``HydroMesh`` pivot contract.

meshio holds polygons of one node count per block. A ``POLYGON`` block of
``HydroMesh`` (a Voronoi mesh, its rows padded with ``-1``) goes to meshio as
its consecutive runs of one node count, so the cell order is kept, and
consecutive polygon blocks read from meshio come back as one padded block.
"""

from __future__ import annotations

from typing import Any

import meshio
import numpy as np

from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh

# meshio name → CellType
_FROM_MESHIO: dict[str, CellType] = {ct.meshio_name: ct for ct in CellType}


def _cell_values(array: Any) -> np.ndarray:
    """Return a per-cell array flat, or a row per cell when it has several components."""
    values = np.asarray(array)
    return values if values.ndim == 2 and values.shape[1] > 1 else values.reshape(-1)


def from_meshio(mesh: Any) -> HydroMesh:
    """Convert a ``meshio.Mesh`` into a ``HydroMesh``.

    Consecutive polygon blocks merge into one ``POLYGON`` block, its rows
    padded with ``-1``. The
    vertices keep x and y only when every cell is planar (triangle,
    quadrilateral, polygon) and every z is zero, the z that ``to_meshio`` adds
    to a planar mesh; any other mesh keeps its z.

    Parameters
    ----------
    mesh :
        Any object exposing the standard ``meshio.Mesh`` attributes
        ``points``, ``cells``, ``cell_data`` and ``point_data``.

    Returns
    -------
    HydroMesh
        Mesh pivot populated from the supported cell blocks found in
        ``mesh``.
    """
    points = np.asarray(mesh.points, dtype=float)
    if points.ndim != 2 or points.shape[1] < 2:
        raise ValueError("meshio mesh must have at least 2D points")
    # Keep only xy or xyz
    vertices = points[:, : min(points.shape[1], 3)]

    # Each entry is one cell type and its connectivity parts; consecutive
    # polygon blocks share one entry.
    retained: list[tuple[CellType, list[np.ndarray]]] = []
    for block in mesh.cells:
        raw_type = str(block.type).strip().lower()
        ct = _FROM_MESHIO.get(raw_type)
        if ct is None:
            continue  # skip unsupported (line, vertex, etc.)
        connectivity = np.asarray(block.data, dtype=int)
        if ct.is_ragged and retained and retained[-1][0].is_ragged:
            retained[-1][1].append(connectivity)
        else:
            retained.append((ct, [connectivity]))
    cell_blocks = [
        CellBlock(cell_type=ct, connectivity=parts[0])
        if len(parts) == 1
        else CellBlock(cell_type=ct, connectivity=tuple(row for part in parts for row in part))
        for ct, parts in retained
    ]

    if not cell_blocks:
        raise ValueError(
            f"meshio mesh contains no supported cell types ({', '.join(sorted(_FROM_MESHIO))})"
        )
    if (
        vertices.shape[1] == 3
        and all(block.cell_type.dimension == 2 for block in cell_blocks)
        and not vertices[:, 2].any()
    ):
        vertices = vertices[:, :2]

    # Collect cell_data: flatten per-block lists into flat arrays
    cell_data: dict[str, np.ndarray] = {}
    meshio_cell_data = getattr(mesh, "cell_data", {}) or {}
    for key, per_block_list in meshio_cell_data.items():
        if not isinstance(per_block_list, (list, tuple)):
            continue
        # Filter to keep only blocks we retained
        retained_indices = []
        for idx, block in enumerate(mesh.cells):
            raw_type = str(block.type).strip().lower()
            if raw_type in _FROM_MESHIO:
                retained_indices.append(idx)
        arrays = [
            _cell_values(per_block_list[i]) for i in retained_indices if i < len(per_block_list)
        ]
        if arrays:
            cell_data[key] = np.concatenate(arrays)

    # Collect point_data
    point_data: dict[str, np.ndarray] = {}
    meshio_point_data = getattr(mesh, "point_data", {}) or {}
    for key, arr in meshio_point_data.items():
        point_data[key] = np.asarray(arr).reshape(-1)

    return HydroMesh(
        vertices=vertices,
        cell_blocks=tuple(cell_blocks),
        cell_data=cell_data,
        point_data=point_data,
    )


def to_meshio(hydro_mesh: HydroMesh) -> Any:
    """Convert a ``HydroMesh`` back into a ``meshio.Mesh``.

    Notes
    -----
    ``meshio`` expects 3D point coordinates even for planar meshes, so 2D
    vertices are padded with ``z=0`` before export. A polygon block becomes
    one meshio block per run of consecutive cells of one node count. The
    node indices are 32-bit integers when the nodes fit, as the run store keeps
    them.
    """
    # Ensure 3D points for meshio
    verts = np.asarray(hydro_mesh.vertices, dtype=float)
    if verts.shape[1] == 2:
        verts = np.column_stack((verts, np.zeros(verts.shape[0], dtype=float)))

    index = np.int32 if hydro_mesh.n_nodes <= np.iinfo(np.int32).max else np.int64
    cells: list[tuple[str, Any]] = []
    for block in hydro_mesh.cell_blocks:
        if block.cell_type.is_ragged:
            cells.extend(
                (block.cell_type.meshio_name, run)
                for run in _runs_of_one_arity(block.connectivity, index)
            )
        else:
            cells.append((block.cell_type.meshio_name, np.asarray(block.connectivity, dtype=index)))

    # Rebuild per-block cell_data lists, a row per cell for an array of several components.
    cell_data: dict[str, list[np.ndarray]] = {}
    if hydro_mesh.cell_data:
        total_cells = int(hydro_mesh.n_cells)
        block_sizes = [len(data) for _, data in cells]
        splits = np.cumsum(block_sizes[:-1])
        for key, array in hydro_mesh.cell_data.items():
            values = _cell_values(array)
            if values.shape[0] != total_cells:
                continue
            cell_data[key] = list(np.split(values, splits))

    point_data: dict[str, np.ndarray] = {}
    for key, arr in hydro_mesh.point_data.items():
        point_data[key] = np.asarray(arr)

    return meshio.Mesh(
        points=verts,
        cells=cells,
        cell_data=cell_data,
        point_data=point_data,
    )


def _runs_of_one_arity(rows: np.ndarray, index: type) -> list[np.ndarray]:
    """Split ``-1`` padded polygon rows into their consecutive runs of one node count, as 2D arrays of ``index``."""
    counts = (rows >= 0).sum(axis=1)
    bounds = np.r_[0, np.flatnonzero(np.diff(counts)) + 1, len(rows)]
    return [
        rows[start:stop, : counts[start]].astype(index, copy=False)
        for start, stop in zip(bounds[:-1], bounds[1:], strict=True)
        if stop > start
    ]
