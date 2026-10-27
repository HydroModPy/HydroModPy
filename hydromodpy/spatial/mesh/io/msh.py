"""Read, normalize and write simple 2D Gmsh meshes.

This module is the low-level I/O layer for planar Gmsh support. It converts
between external mesh representations (`meshio` objects or ASCII `.msh`
content) and one small internal payload (`GmshMeshData`), and between a
``.msh`` file and a ``HydroMesh`` (:func:`read_msh`, :func:`write_msh`).

Its job is deliberately narrow: accept triangles or quads, normalize their
connectivity, reject unsupported mixed cases, and keep file handling separate
from the higher-level mesh classes. The two-node lines of the named
one-dimensional physical groups come with the cells, in
``GmshMeshData.line_groups``.

meshio reads the file. When it fails on a ``.msh`` file, a small in-house
parser reads the ASCII 2.2 format instead.

A ``.msh`` file carries no CRS. A mesh written with one gets a projection
file next to it, ``<name>.prj`` holding the WKT, and the reader takes it
back into ``GmshMeshData.crs_wkt``.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import meshio
import numpy as np

from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh

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
_LINE_ELEMENT = 1
"""Gmsh element type of a two-node line."""


def _parse_int_tokens(line: str, *, expected_at_least: int) -> list[int]:
    tokens = [token for token in str(line).strip().split() if token]
    if len(tokens) < expected_at_least:
        raise ValueError(
            f"Invalid Gmsh line '{line.strip()}': expected at least {expected_at_least} tokens"
        )
    return [int(token) for token in tokens]


def _read_gmsh22_ascii_mesh(path: Path, *, cell_type: str | None = None) -> GmshMeshData:
    """Fallback parser for simple ASCII ``.msh`` 2.2 files.

    This reader intentionally supports only the narrow subset used by the
    repository examples: 2D triangles or quads in a single topological layer.
    """
    requested_cell_type = None if cell_type is None else normalize_cell_type(cell_type)
    lines = path.read_text(encoding="utf-8").splitlines()

    def _find_section(name: str) -> int:
        marker = f"${name}"
        for idx, line in enumerate(lines):
            if line.strip() == marker:
                return idx
        raise ValueError(f"Missing Gmsh section '{marker}' in '{path}'")

    names: dict[int, str] = {}
    if any(line.strip() == "$PhysicalNames" for line in lines):
        names_start = _find_section("PhysicalNames")
        n_names = int(lines[names_start + 1].strip())
        names = _physical_line_names(lines[names_start + 2 : names_start + 2 + n_names])

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
    line_pairs: dict[str, list[list[int]]] = {}
    for offset in range(n_elements):
        raw_line = lines[elements_start + 2 + offset]
        values = _parse_int_tokens(raw_line, expected_at_least=3)
        _element_id, element_type, n_tags = values[:3]
        node_tokens = values[3 + n_tags :]
        if element_type == _LINE_ELEMENT:
            name = names.get(values[3]) if n_tags >= 1 else None
            if name is not None:
                line_pairs.setdefault(name, []).append([int(n) - 1 for n in node_tokens[:2]])
            continue
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
    return GmshMeshData(
        points_xy=points_xy,
        cell_blocks=cell_blocks,
        source_path=path,
        line_groups={name: np.asarray(pairs) for name, pairs in line_pairs.items()},
    )


def _physical_line_names(lines: list[str]) -> dict[int, str]:
    """Names of the one-dimensional physical groups, by physical tag.

    ``lines`` are the entries of a ``$PhysicalNames`` section, after its count.
    """
    names: dict[int, str] = {}
    for line in lines:
        dim, tag, name = line.split(maxsplit=2)
        if int(dim) == 1:
            names[int(tag)] = name.strip().strip('"')
    return names


def normalize_cell_type(cell_type: str) -> str:
    """Normalize external and ``meshio`` cell-type names to the internal convention."""
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
    """Raw planar mesh payload independent from the higher HydroModPy layers.

    This object stays intentionally small: points, homogeneous cell blocks,
    an optional source path and CRS, and the named line groups of the file.
    :func:`read_msh` gives the same mesh as a ``HydroMesh``.
    """

    points_xy: np.ndarray
    cell_blocks: tuple[GmshCellBlock, ...]
    source_path: Path | None = None
    crs_wkt: str | None = None
    line_groups: dict[str, np.ndarray] = field(default_factory=dict)
    """The two-node line elements of each named one-dimensional physical group,
    as ``(n, 2)`` node indices in file order."""

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
        line_groups = {
            str(name): np.asarray(pairs, dtype=np.int64).reshape(-1, 2)
            for name, pairs in self.line_groups.items()
        }
        for pairs in line_groups.values():
            if np.any(pairs < 0) or np.any(pairs >= n_nodes):
                raise ValueError("line groups reference node indices outside points_xy")
        source_path = None if self.source_path is None else Path(self.source_path).resolve()
        object.__setattr__(self, "points_xy", points_xy.copy())
        object.__setattr__(self, "source_path", source_path)
        object.__setattr__(self, "line_groups", line_groups)

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


def meshio_to_mesh_data(
    mesh: Any, *, cell_type: str | None = None, line_names: Mapping[int, str] | None = None
) -> GmshMeshData:
    """Convert one ``meshio`` mesh into a normalized planar mesh payload.

    ``line_names`` gives the name of each one-dimensional physical group by
    tag. Left out, the names come from ``mesh.field_data``, which holds one
    group per name.
    """
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
        line_groups=_line_groups(mesh, line_names),
    )


def _line_groups(mesh: Any, line_names: Mapping[int, str] | None) -> dict[str, np.ndarray]:
    """The two-node lines of each named one-dimensional physical group of a meshio mesh.

    meshio gives the physical tag of every element in
    ``cell_data["gmsh:physical"]``. ``line_names`` names the tags; left out,
    the names come from ``field_data``, as name to ``[tag, dimension]``. The
    lines of every tag of one name are gathered, in file order.
    """
    names = _field_data_line_names(mesh) if line_names is None else dict(line_names)
    physical = (getattr(mesh, "cell_data", None) or {}).get("gmsh:physical")
    if not names or physical is None:
        return {}
    groups: dict[str, list[np.ndarray]] = {}
    for block, tags in zip(mesh.cells, physical, strict=True):
        if str(block.type) != "line":
            continue
        for nodes, tag in zip(np.asarray(block.data), np.asarray(tags).reshape(-1), strict=True):
            name = names.get(int(tag))
            if name is not None:
                groups.setdefault(name, []).append(nodes)
    return {name: np.asarray(rows, dtype=np.int64).reshape(-1, 2) for name, rows in groups.items()}


def _field_data_line_names(mesh: Any) -> dict[int, str]:
    """Names of the one-dimensional physical groups of a meshio mesh, by tag."""
    names: dict[int, str] = {}
    for name, value in (getattr(mesh, "field_data", None) or {}).items():
        tag_and_dim = np.asarray(value).reshape(-1)
        if tag_and_dim.size >= 2 and int(tag_and_dim[1]) == 1:
            names[int(tag_and_dim[0])] = str(name)
    return names


def _msh_line_names(path: Path) -> dict[int, str]:
    """Names of the one-dimensional physical groups of a ``.msh`` file, by tag.

    meshio keeps one group per name in ``field_data``, so two tags that share
    a name, or a name a surface also takes, would lose lines. The
    ``$PhysicalNames`` section is read from the file text instead. It is ASCII
    in a binary file too.
    """
    entries: list[str] = []
    with path.open("rb") as handle:
        for raw in handle:
            if raw.strip() != b"$PhysicalNames":
                continue
            for line in handle:
                text = line.strip().decode("utf-8")
                if text == "$EndPhysicalNames":
                    break
                if text:
                    entries.append(text)
            break
    if not entries:
        return {}
    return _physical_line_names(entries[1 : 1 + int(entries[0])])


def read_gmsh_2d_mesh(path: str | Path, *, cell_type: str | None = None) -> GmshMeshData:
    """Read one planar 2D triangle or quadrilateral mesh from disk.

    The function reads the file through ``meshio``, then falls back to a small
    in-house parser for simple ASCII Gmsh 2.2 files when meshio fails on a
    ``.msh`` file. The projection file next to the mesh, when there is one,
    gives ``crs_wkt``.
    """
    path_obj = Path(path).resolve()
    mesh_data = _read_mesh_data(path_obj, cell_type=cell_type)
    projection = projection_path(path_obj)
    if not projection.is_file():
        return mesh_data
    wkt = projection.read_text(encoding="utf-8").strip()
    return dataclasses.replace(mesh_data, crs_wkt=wkt or None)


def projection_path(path: str | Path) -> Path:
    """Return the projection file of a mesh file: same name, suffix ``.prj``."""
    return Path(path).with_suffix(".prj")


def msh_format(path: str | Path) -> str | None:
    """Return the version line of the ``$MeshFormat`` section of a ``.msh`` file.

    The line reads ``"2.2 0 8"`` for an ASCII file of format 2.2. Only the
    lines up to it are read. ``None`` means the file has no such section.
    """
    with Path(path).open("rb") as handle:
        for raw in handle:
            if raw.strip() != b"$MeshFormat":
                continue
            for line in handle:
                if line.strip():
                    return line.strip().decode("ascii", errors="replace")
            return None
    return None


def _read_mesh_data(path_obj: Path, *, cell_type: str | None) -> GmshMeshData:
    """Read the nodes and cells of one mesh file, through meshio or the ASCII fallback."""
    try:
        mesh = meshio.read(path_obj)
    except (Exception, SystemExit) as exc:
        if path_obj.suffix.lower() == ".msh":
            try:
                return _read_gmsh22_ascii_mesh(path_obj, cell_type=cell_type)
            except Exception as fallback_exc:
                raise ValueError(
                    "Could not read planar mesh "
                    f"'{path_obj}' through meshio or the ASCII Gmsh fallback: {fallback_exc}"
                ) from fallback_exc
        raise ValueError(f"Could not read planar mesh '{path_obj}'.") from exc
    mesh.path = path_obj
    line_names = _msh_line_names(path_obj) if path_obj.suffix.lower() == ".msh" else None
    return meshio_to_mesh_data(mesh, cell_type=cell_type, line_names=line_names)


def mesh_data_to_meshio(mesh_data: GmshMeshData):
    """Convert one normalized planar payload back to a ``meshio`` object."""
    points_xy = np.asarray(mesh_data.points_xy, dtype=float)
    points_xyz = np.column_stack((points_xy, np.zeros(points_xy.shape[0], dtype=float)))
    cells = [
        (
            _MESHIO_CELL_TYPE_BY_INTERNAL[block.cell_type],
            np.asarray(block.connectivity, dtype=int),
        )
        for block in mesh_data.cell_blocks
    ]
    return meshio.Mesh(points=points_xyz, cells=cells)


def write_gmsh_2d_mesh(
    path: str | Path,
    mesh_data: GmshMeshData,
    *,
    file_format: str | None = None,
    crs: Any = None,
) -> Path:
    """Write one planar mesh payload to disk through meshio.

    A path ending in ``.msh`` with no ``file_format`` is written as gmsh 2.2
    ASCII, the format the planner and the fallback reader read; meshio alone
    would write an ANSYS Fluent file there. An explicit ``file_format`` wins.
    ``crs`` (any form ``pyproj.CRS.from_user_input`` takes, ``mesh_data.crs_wkt``
    when left out) is written as WKT to the projection file next to the mesh,
    since the mesh formats meshio writes carry none. No CRS writes no file.
    """
    path_obj = Path(path).resolve()
    crs = mesh_data.crs_wkt if crs is None else crs
    wkt = None
    if crs is not None:
        from pyproj import CRS

        wkt = CRS.from_user_input(crs).to_wkt()
    mesh = mesh_data_to_meshio(mesh_data)
    if file_format is None and path_obj.suffix.lower() == ".msh":
        meshio.write(path_obj, mesh, file_format="gmsh22", binary=False)
    else:
        meshio.write(path_obj, mesh, file_format=file_format)
    if wkt is not None:
        projection_path(path_obj).write_text(wkt + "\n", encoding="utf-8")
    return path_obj


def read_msh(path: str | Path, *, cell_type: str | None = None) -> HydroMesh:
    """Read a planar mesh file into a ``HydroMesh`` of one cell block.

    The nodes and the cells come from :func:`read_gmsh_2d_mesh`, in its order,
    and ``cell_type`` selects one type in a file that mixes them. The projection
    file and the line groups are not part of a ``HydroMesh``; that function
    gives them.
    """
    mesh_data = read_gmsh_2d_mesh(path, cell_type=cell_type)
    return HydroMesh(
        vertices=mesh_data.points_xy,
        cell_blocks=(CellBlock(CellType.from_string(mesh_data.cell_type), mesh_data.connectivity),),
    )


def write_msh(
    path: str | Path,
    hydro_mesh: HydroMesh,
    *,
    file_format: str | None = None,
    crs: Any = None,
) -> Path:
    """Write a planar ``HydroMesh`` of triangles and quadrilaterals to a mesh file.

    The file is written by :func:`write_gmsh_2d_mesh`, so a ``crs`` goes to the
    projection file next to it. A mesh with a z, or with polygon cells, is
    refused.
    """
    if hydro_mesh.ndim != 2:
        raise ValueError("write_msh writes a planar HydroMesh, with x and y vertices only")
    blocks = []
    for block in hydro_mesh.cell_blocks:
        if block.cell_type.meshio_name not in _SUPPORTED_MESHIO_CELL_TYPES:
            raise ValueError(
                f"a .msh file holds triangles and quadrilaterals, not {block.cell_type.value} cells"
            )
        blocks.append(GmshCellBlock(block.cell_type.value, block.connectivity))
    mesh_data = GmshMeshData(points_xy=hydro_mesh.vertices, cell_blocks=tuple(blocks))
    return write_gmsh_2d_mesh(path, mesh_data, file_format=file_format, crs=crs)
