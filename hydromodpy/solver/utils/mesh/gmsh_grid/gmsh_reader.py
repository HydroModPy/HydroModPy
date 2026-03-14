"""Low-level read/write helpers for planar 2D meshes handled via meshio."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

_SUPPORTED_MESHIO_CELL_TYPES = {"triangle", "quad"}
_CELL_TYPE_ALIASES = {
    "triangle": "triangle",
    "triangles": "triangle",
    "quad": "quadrilateral",
    "quads": "quadrilateral",
    "quadrilateral": "quadrilateral",
    "quadrilaterals": "quadrilateral",
}
_MESHIO_CELL_TYPE_BY_INTERNAL = {
    "triangle": "triangle",
    "quadrilateral": "quad",
}
_NODES_PER_CELL = {
    "triangle": 3,
    "quadrilateral": 4,
}


def _require_meshio():
    try:
        import meshio  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on environment
        raise ImportError(
            "meshio is required for Gmsh mesh read/write support. "
            "Install the 'meshio' package to use from_file()/to_file()."
        ) from exc
    return meshio


def _parse_int_tokens(line: str, *, expected_at_least: int) -> list[int]:
    tokens = [token for token in str(line).strip().split() if token]
    if len(tokens) < expected_at_least:
        raise ValueError(f"Invalid Gmsh line '{line.strip()}': expected at least {expected_at_least} tokens")
    return [int(token) for token in tokens]


def _read_gmsh22_ascii_mesh(path: Path, *, cell_type: str | None = None) -> GmshMeshData:
    """Fallback parser for simple ASCII `.msh` 2.2 files with 2D triangles/quads."""
    requested_cell_type = None if cell_type is None else normalize_cell_type(cell_type)
    lines = path.read_text(encoding="utf-8").splitlines()

    def _find_section(name: str) -> int:
        marker = f"${name}"
        for idx, line in enumerate(lines):
            if line.strip() == marker:
                return idx
        raise ValueError(f"Missing Gmsh section '{marker}' in '{path}'")

    nodes_start = _find_section("Nodes")
    n_nodes = int(lines[nodes_start + 1].strip())
    raw_points: dict[int, tuple[float, float]] = {}
    for offset in range(n_nodes):
        tokens = lines[nodes_start + 2 + offset].strip().split()
        if len(tokens) < 4:
            raise ValueError(f"Invalid node line in '{path}': {lines[nodes_start + 2 + offset]!r}")
        node_id = int(tokens[0])
        raw_points[node_id] = (float(tokens[1]), float(tokens[2]))
    node_ids = sorted(raw_points)
    if node_ids != list(range(1, n_nodes + 1)):
        raise ValueError("Fallback Gmsh reader requires contiguous node ids starting at 1")
    points_xy = np.array([raw_points[node_id] for node_id in node_ids], dtype=float)

    elements_start = _find_section("Elements")
    n_elements = int(lines[elements_start + 1].strip())
    blocks: dict[str, list[list[int]]] = {"triangle": [], "quadrilateral": []}
    for offset in range(n_elements):
        raw_line = lines[elements_start + 2 + offset]
        values = _parse_int_tokens(raw_line, expected_at_least=3)
        _element_id, element_type, n_tags = values[:3]
        node_tokens = values[3 + n_tags :]
        if element_type == 2:
            normalized_type = "triangle"
        elif element_type == 3:
            normalized_type = "quadrilateral"
        else:
            continue
        if requested_cell_type is not None and normalized_type != requested_cell_type:
            continue
        expected_width = _NODES_PER_CELL[normalized_type]
        if len(node_tokens) != expected_width:
            raise ValueError(
                f"Invalid {normalized_type} element in '{path}': expected {expected_width} node ids"
            )
        blocks[normalized_type].append([int(node_id) - 1 for node_id in node_tokens])

    selected_types = [kind for kind, items in blocks.items() if items]
    if not selected_types:
        raise ValueError(f"No supported 2D triangle/quadrilateral elements found in '{path}'")
    if requested_cell_type is None and len(selected_types) > 1:
        present = ", ".join(sorted(selected_types))
        raise ValueError(
            "Mixed 2D cell types are not supported in one planar mesh. "
            f"Found: {present}. Pass cell_type=... to select one type."
        )

    cell_blocks = tuple(
        GmshCellBlock(
            cell_type=kind,
            connectivity=np.asarray(items, dtype=int),
        )
        for kind, items in blocks.items()
        if items
    )
    return GmshMeshData(points_xy=points_xy, cell_blocks=cell_blocks, source_path=path)


def normalize_cell_type(cell_type: str) -> str:
    """Normalize external and meshio cell-type names to the internal convention."""
    normalized = _CELL_TYPE_ALIASES.get(str(cell_type).strip().lower())
    if normalized is None:
        allowed = ", ".join(sorted(set(_CELL_TYPE_ALIASES)))
        raise ValueError(f"Unsupported planar cell type '{cell_type}'. Allowed: {allowed}")
    return normalized


def _normalize_meshio_cell_type(cell_type: str) -> str | None:
    raw = str(cell_type).strip().lower()
    if raw not in _SUPPORTED_MESHIO_CELL_TYPES:
        return None
    return normalize_cell_type(raw)


@dataclass(frozen=True)
class GmshCellBlock:
    """One homogeneous 2D cell block read from one mesh file."""

    cell_type: str
    connectivity: np.ndarray

    def __post_init__(self) -> None:
        normalized_type = normalize_cell_type(self.cell_type)
        connectivity = np.asarray(self.connectivity, dtype=int)
        expected_width = _NODES_PER_CELL[normalized_type]
        if connectivity.ndim != 2 or connectivity.shape[1] != expected_width:
            raise ValueError(
                f"{normalized_type} connectivity must have shape (n_cells, {expected_width})"
            )
        object.__setattr__(self, "cell_type", normalized_type)
        object.__setattr__(self, "connectivity", connectivity.copy())

    @property
    def n_cells(self) -> int:
        return int(self.connectivity.shape[0])


@dataclass(frozen=True)
class GmshMeshData:
    """Raw planar mesh payload independent from the Field/FieldParam layers."""

    points_xy: np.ndarray
    cell_blocks: tuple[GmshCellBlock, ...]
    source_path: Path | None = None

    def __post_init__(self) -> None:
        points_xy = np.asarray(self.points_xy, dtype=float)
        if points_xy.ndim != 2 or points_xy.shape[1] != 2:
            raise ValueError("points_xy must have shape (n_nodes, 2)")
        if len(self.cell_blocks) == 0:
            raise ValueError("cell_blocks cannot be empty")
        n_nodes = int(points_xy.shape[0])
        for block in self.cell_blocks:
            if np.any(block.connectivity < 0) or np.any(block.connectivity >= n_nodes):
                raise ValueError("cell connectivity references node indices outside points_xy")
        source_path = None if self.source_path is None else Path(self.source_path).resolve()
        object.__setattr__(self, "points_xy", points_xy.copy())
        object.__setattr__(self, "source_path", source_path)

    @property
    def cell_type(self) -> str:
        kinds = {block.cell_type for block in self.cell_blocks}
        if len(kinds) != 1:
            raise ValueError(
                "GmshMeshData contains mixed cell types; select one type before building a planar mesh"
            )
        return next(iter(kinds))

    @property
    def connectivity(self) -> np.ndarray:
        return np.vstack([block.connectivity for block in self.cell_blocks]).astype(int, copy=False)

    @property
    def n_nodes(self) -> int:
        return int(self.points_xy.shape[0])

    @property
    def n_cells(self) -> int:
        return int(sum(block.n_cells for block in self.cell_blocks))


def meshio_to_mesh_data(mesh: Any, *, cell_type: str | None = None) -> GmshMeshData:
    """Convert one meshio mesh into a normalized planar mesh payload."""
    requested_cell_type = None if cell_type is None else normalize_cell_type(cell_type)

    points = np.asarray(mesh.points, dtype=float)
    if points.ndim != 2 or points.shape[1] < 2:
        raise ValueError("mesh points must expose at least x and y coordinates")
    points_xy = np.asarray(points[:, :2], dtype=float)

    selected_blocks: list[GmshCellBlock] = []
    selected_kinds: set[str] = set()
    for block in tuple(mesh.cells):
        normalized_type = _normalize_meshio_cell_type(block.type)
        if normalized_type is None:
            continue
        if requested_cell_type is not None and normalized_type != requested_cell_type:
            continue
        connectivity = np.asarray(block.data, dtype=int)
        selected_blocks.append(
            GmshCellBlock(
                cell_type=normalized_type,
                connectivity=connectivity,
            )
        )
        selected_kinds.add(normalized_type)

    if not selected_blocks:
        supported = ", ".join(sorted(_SUPPORTED_MESHIO_CELL_TYPES))
        raise ValueError(
            "Mesh does not contain supported 2D cell blocks "
            f"({supported}) for the requested selection."
        )
    if requested_cell_type is None and len(selected_kinds) > 1:
        present = ", ".join(sorted(selected_kinds))
        raise ValueError(
            "Mixed 2D cell types are not supported in one planar mesh. "
            f"Found: {present}. Pass cell_type=... to select one type."
        )

    source_path = getattr(mesh, "path", None)
    return GmshMeshData(
        points_xy=points_xy,
        cell_blocks=tuple(selected_blocks),
        source_path=None if source_path is None else Path(source_path),
    )


def read_gmsh_2d_mesh(path: str | Path, *, cell_type: str | None = None) -> GmshMeshData:
    """Read one planar 2D triangle or quadrilateral mesh from disk."""
    path_obj = Path(path).resolve()
    try:
        meshio = _require_meshio()
    except ImportError:
        if path_obj.suffix.lower() == ".msh":
            return _read_gmsh22_ascii_mesh(path_obj, cell_type=cell_type)
        raise
    mesh = meshio.read(path_obj)
    mesh.path = path_obj
    return meshio_to_mesh_data(mesh, cell_type=cell_type)


def mesh_data_to_meshio(mesh_data: GmshMeshData):
    """Convert one normalized planar mesh payload back to a meshio object."""
    meshio = _require_meshio()
    points_xy = np.asarray(mesh_data.points_xy, dtype=float)
    points_xyz = np.column_stack((points_xy, np.zeros(points_xy.shape[0], dtype=float)))
    cells = [
        (_MESHIO_CELL_TYPE_BY_INTERNAL[block.cell_type], np.asarray(block.connectivity, dtype=int))
        for block in mesh_data.cell_blocks
    ]
    return meshio.Mesh(points=points_xyz, cells=cells)


def write_gmsh_2d_mesh(
    path: str | Path,
    mesh_data: GmshMeshData,
    *,
    file_format: str | None = None,
) -> Path:
    """Write one planar mesh payload to disk through meshio."""
    meshio = _require_meshio()
    path_obj = Path(path).resolve()
    mesh = mesh_data_to_meshio(mesh_data)
    meshio.write(path_obj, mesh, file_format=file_format)
    return path_obj
