"""3D prism extrusion helpers built from one validated planar 2D mesh."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.solver.utils.mesh.gmsh_grid.gmsh_planar_mesh import GmshPlanarMesh2D

_MESHIO_CELL_TYPE_BY_2D = {
    "triangle": "wedge",
    "quadrilateral": "hexahedron",
}
_INTERNAL_3D_KIND_BY_2D = {
    "triangle": "triangular_prism",
    "quadrilateral": "quadrilateral_prism",
}
_NODES_PER_3D_CELL = {
    "triangle": 6,
    "quadrilateral": 8,
}
_POINT_LAYER_KEY = "hydromodpy_point_layer_index"
_POINT_BASE_KEY = "hydromodpy_point_base_index"
_CELL_LAYER_KEY = "hydromodpy_cell_layer_index"
_CELL_SOURCE_KEY = "hydromodpy_cell_source_index"


def _require_meshio():
    try:
        import meshio  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on environment
        raise ImportError(
            "meshio is required for extruded 3D mesh read/write support. "
            "Install the 'meshio' package to use from_file()/to_file()."
        ) from exc
    return meshio


def _resolve_z_interfaces(
    *,
    z_interfaces,
    top_z: float | None,
    layer_thicknesses,
) -> np.ndarray:
    if z_interfaces is not None:
        if top_z is not None or layer_thicknesses is not None:
            raise ValueError("Pass either z_interfaces or top_z/layer_thicknesses, not both")
        arr = np.asarray(z_interfaces, dtype=float).reshape(-1)
    else:
        if top_z is None or layer_thicknesses is None:
            raise ValueError("top_z and layer_thicknesses are required when z_interfaces is omitted")
        thicknesses = np.asarray(layer_thicknesses, dtype=float).reshape(-1)
        if thicknesses.size == 0 or np.any(~np.isfinite(thicknesses)) or np.any(thicknesses <= 0.0):
            raise ValueError("layer_thicknesses must contain strictly positive finite values")
        arr = np.empty(thicknesses.size + 1, dtype=float)
        arr[0] = float(top_z)
        arr[1:] = float(top_z) - np.cumsum(thicknesses)

    if arr.ndim != 1 or arr.size < 2:
        raise ValueError("z_interfaces must contain at least two vertical interfaces")
    deltas = np.diff(arr)
    if np.any(~np.isfinite(arr)) or np.any(deltas == 0.0):
        raise ValueError("z_interfaces must be finite and strictly monotonic")
    if not (np.all(deltas > 0.0) or np.all(deltas < 0.0)):
        raise ValueError("z_interfaces must be strictly monotonic")
    return arr.astype(float, copy=True)


def _stable_unique(values) -> np.ndarray:
    arr = np.asarray(values, dtype=float).reshape(-1)
    out: list[float] = []
    for value in arr:
        if not out or not np.isclose(value, out[-1], rtol=0.0, atol=1e-9):
            out.append(float(value))
    return np.asarray(out, dtype=float)


@dataclass(frozen=True)
class PrismCell3D:
    """One explicit 3D prism cell."""

    index: int
    kind: str
    node_indices: tuple[int, ...]
    vertices: np.ndarray
    centroid: tuple[float, float, float]
    layer_index: int
    source_cell_index: int


@dataclass(frozen=True)
class ExtrudedPrismMeshData:
    """Raw 3D extrusion payload independent from Field/FieldParam concerns."""

    points_xyz: np.ndarray
    prism_connectivity: np.ndarray
    cell_type_2d: str
    z_interfaces: np.ndarray
    layer_indices: np.ndarray
    source_cell_indices: np.ndarray
    point_layer_indices: np.ndarray
    point_base_indices: np.ndarray
    source_path: Path | None = None

    def __post_init__(self) -> None:
        points_xyz = np.asarray(self.points_xyz, dtype=float)
        if points_xyz.ndim != 2 or points_xyz.shape[1] != 3:
            raise ValueError("points_xyz must have shape (n_nodes, 3)")

        cell_type_2d = str(self.cell_type_2d).strip().lower()
        if cell_type_2d not in _NODES_PER_3D_CELL:
            raise ValueError("cell_type_2d must be 'triangle' or 'quadrilateral'")

        prism_connectivity = np.asarray(self.prism_connectivity, dtype=int)
        expected_width = _NODES_PER_3D_CELL[cell_type_2d]
        if prism_connectivity.ndim != 2 or prism_connectivity.shape[1] != expected_width:
            raise ValueError(
                f"{cell_type_2d} extrusion connectivity must have shape (n_cells, {expected_width})"
            )
        if np.any(prism_connectivity < 0) or np.any(prism_connectivity >= points_xyz.shape[0]):
            raise ValueError("prism connectivity references point indices outside points_xyz")

        z_interfaces = _resolve_z_interfaces(z_interfaces=self.z_interfaces, top_z=None, layer_thicknesses=None)
        n_prisms = int(prism_connectivity.shape[0])
        n_points = int(points_xyz.shape[0])

        layer_indices = np.asarray(self.layer_indices, dtype=int).reshape(-1)
        source_cell_indices = np.asarray(self.source_cell_indices, dtype=int).reshape(-1)
        point_layer_indices = np.asarray(self.point_layer_indices, dtype=int).reshape(-1)
        point_base_indices = np.asarray(self.point_base_indices, dtype=int).reshape(-1)

        if layer_indices.size != n_prisms or source_cell_indices.size != n_prisms:
            raise ValueError("layer_indices and source_cell_indices must match the number of prisms")
        if point_layer_indices.size != n_points or point_base_indices.size != n_points:
            raise ValueError("point metadata must match the number of 3D points")
        if np.any(layer_indices < 0) or np.any(layer_indices >= z_interfaces.size - 1):
            raise ValueError("layer_indices contain invalid layer ids")
        if np.any(source_cell_indices < 0):
            raise ValueError("source_cell_indices must be non-negative")
        if np.any(point_layer_indices < 0) or np.any(point_layer_indices >= z_interfaces.size):
            raise ValueError("point_layer_indices contain invalid vertical ids")
        if np.any(point_base_indices < 0):
            raise ValueError("point_base_indices must be non-negative")

        object.__setattr__(self, "points_xyz", points_xyz.copy())
        object.__setattr__(self, "prism_connectivity", prism_connectivity.copy())
        object.__setattr__(self, "cell_type_2d", cell_type_2d)
        object.__setattr__(self, "z_interfaces", z_interfaces.copy())
        object.__setattr__(self, "layer_indices", layer_indices.copy())
        object.__setattr__(self, "source_cell_indices", source_cell_indices.copy())
        object.__setattr__(self, "point_layer_indices", point_layer_indices.copy())
        object.__setattr__(self, "point_base_indices", point_base_indices.copy())
        object.__setattr__(
            self,
            "source_path",
            None if self.source_path is None else Path(self.source_path).resolve(),
        )

    @property
    def n_nodes(self) -> int:
        return int(self.points_xyz.shape[0])

    @property
    def n_prisms(self) -> int:
        return int(self.prism_connectivity.shape[0])

    @property
    def n_layers(self) -> int:
        return int(self.z_interfaces.size - 1)

    @property
    def cell_type_3d(self) -> str:
        return _INTERNAL_3D_KIND_BY_2D[self.cell_type_2d]


def _build_default_components(
    planar_mesh: GmshPlanarMesh2D,
    z_interfaces: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n_planar_nodes = int(planar_mesh.points_xy.shape[0])
    n_levels = int(z_interfaces.size)
    n_layers = int(n_levels - 1)
    n_planar_cells = int(planar_mesh.n_cells)

    points_xyz = np.vstack(
        [
            np.column_stack((planar_mesh.points_xy, np.full(n_planar_nodes, float(z_value), dtype=float)))
            for z_value in z_interfaces
        ]
    )
    point_layer_indices = np.repeat(np.arange(n_levels, dtype=int), n_planar_nodes)
    point_base_indices = np.tile(np.arange(n_planar_nodes, dtype=int), n_levels)

    prism_connectivity = np.empty(
        (n_layers * n_planar_cells, _NODES_PER_3D_CELL[planar_mesh.cell_type]),
        dtype=int,
    )
    layer_indices = np.empty(n_layers * n_planar_cells, dtype=int)
    source_cell_indices = np.empty(n_layers * n_planar_cells, dtype=int)
    base_connectivity = np.asarray(planar_mesh.connectivity, dtype=int)
    for layer_idx in range(n_layers):
        offset_top = layer_idx * n_planar_nodes
        offset_bot = (layer_idx + 1) * n_planar_nodes
        start = layer_idx * n_planar_cells
        stop = start + n_planar_cells
        prism_connectivity[start:stop, : base_connectivity.shape[1]] = base_connectivity + offset_top
        prism_connectivity[start:stop, base_connectivity.shape[1] :] = base_connectivity + offset_bot
        layer_indices[start:stop] = layer_idx
        source_cell_indices[start:stop] = np.arange(n_planar_cells, dtype=int)
    return (
        points_xyz,
        prism_connectivity,
        layer_indices,
        source_cell_indices,
        point_layer_indices,
        point_base_indices,
    )


def _extract_cell_block(mesh: Any) -> tuple[int, str, np.ndarray]:
    supported: list[tuple[int, str, np.ndarray]] = []
    for idx, block in enumerate(tuple(mesh.cells)):
        block_type = str(block.type).strip().lower()
        if block_type == "wedge":
            supported.append((idx, "triangle", np.asarray(block.data, dtype=int)))
        elif block_type == "hexahedron":
            supported.append((idx, "quadrilateral", np.asarray(block.data, dtype=int)))
    if not supported:
        raise ValueError("Mesh does not contain supported 3D wedge/hexahedron cell blocks")
    if len(supported) > 1:
        raise ValueError("Mixed 3D extruded cell blocks are not supported in one mesh")
    return supported[0]


def _extract_one_cell_data(mesh: Any, *, key: str, block_index: int) -> np.ndarray | None:
    cell_data = getattr(mesh, "cell_data", {})
    values = cell_data.get(key)
    if values is None:
        return None
    if block_index >= len(values):
        raise ValueError(f"Mesh cell_data['{key}'] is inconsistent with cell blocks")
    return np.asarray(values[block_index], dtype=int).reshape(-1)


def _build_planar_mesh_from_data(mesh_data: ExtrudedPrismMeshData) -> GmshPlanarMesh2D:
    point_mask = np.asarray(mesh_data.point_layer_indices == 0, dtype=bool)
    base_points = np.asarray(mesh_data.points_xyz[point_mask, :2], dtype=float)
    base_order = np.asarray(mesh_data.point_base_indices[point_mask], dtype=int)
    if base_points.shape[0] == 0:
        raise ValueError("Extruded mesh does not expose any node on layer interface 0")
    order = np.argsort(base_order)
    base_points = base_points[order]
    base_connectivity = np.empty(
        (int(np.max(mesh_data.source_cell_indices)) + 1, 3 if mesh_data.cell_type_2d == "triangle" else 4),
        dtype=int,
    )
    point_base_by_node = np.asarray(mesh_data.point_base_indices, dtype=int)
    layer0_mask = np.asarray(mesh_data.layer_indices == 0, dtype=bool)
    if not np.any(layer0_mask):
        raise ValueError("Extruded mesh does not expose any prism on layer 0")
    first_half_width = base_connectivity.shape[1]
    layer0_conn = np.asarray(mesh_data.prism_connectivity[layer0_mask, :first_half_width], dtype=int)
    layer0_source = np.asarray(mesh_data.source_cell_indices[layer0_mask], dtype=int)
    sort_order = np.argsort(layer0_source)
    for idx, source_cell in enumerate(layer0_source[sort_order]):
        base_connectivity[source_cell] = point_base_by_node[layer0_conn[sort_order[idx]]]
    return GmshPlanarMesh2D(
        points_xy=base_points,
        connectivity=base_connectivity,
        cell_type=mesh_data.cell_type_2d,
        target_n_cells=base_connectivity.shape[0],
    )


def _infer_mesh_data(mesh: Any) -> ExtrudedPrismMeshData:
    points_xyz = np.asarray(mesh.points, dtype=float)
    if points_xyz.ndim != 2 or points_xyz.shape[1] < 3:
        raise ValueError("Extruded mesh points must expose x, y and z coordinates")
    points_xyz = points_xyz[:, :3]

    block_index, cell_type_2d, prism_connectivity = _extract_cell_block(mesh)
    point_data = getattr(mesh, "point_data", {})
    point_layer_indices = point_data.get(_POINT_LAYER_KEY)
    point_base_indices = point_data.get(_POINT_BASE_KEY)
    layer_indices = _extract_one_cell_data(mesh, key=_CELL_LAYER_KEY, block_index=block_index)
    source_cell_indices = _extract_one_cell_data(mesh, key=_CELL_SOURCE_KEY, block_index=block_index)

    if point_layer_indices is not None and point_base_indices is not None:
        point_layer_indices = np.asarray(point_layer_indices, dtype=int).reshape(-1)
        point_base_indices = np.asarray(point_base_indices, dtype=int).reshape(-1)
        if point_layer_indices.size != points_xyz.shape[0] or point_base_indices.size != points_xyz.shape[0]:
            raise ValueError("Point extrusion metadata does not match the number of points")
        level_ids = np.unique(point_layer_indices)
        z_interfaces = np.array(
            [float(np.mean(points_xyz[point_layer_indices == level_idx, 2])) for level_idx in np.sort(level_ids)],
            dtype=float,
        )
    else:
        z_interfaces = _stable_unique(points_xyz[:, 2])
        counts = [int(np.count_nonzero(np.isclose(points_xyz[:, 2], z_value, rtol=0.0, atol=1e-9))) for z_value in z_interfaces]
        if len(set(counts)) != 1:
            raise ValueError("Cannot infer layered point layout from the 3D mesh without hydromodpy metadata")
        n_base_nodes = counts[0]
        if n_base_nodes * z_interfaces.size != points_xyz.shape[0]:
            raise ValueError("Cannot infer layered point layout from the 3D mesh without hydromodpy metadata")
        point_layer_indices = np.repeat(np.arange(z_interfaces.size, dtype=int), n_base_nodes)
        point_base_indices = np.tile(np.arange(n_base_nodes, dtype=int), z_interfaces.size)

    n_layers = int(z_interfaces.size - 1)
    if n_layers <= 0:
        raise ValueError("Extruded mesh requires at least one vertical layer")

    if layer_indices is None or source_cell_indices is None:
        if prism_connectivity.shape[0] % n_layers != 0:
            raise ValueError("Cannot infer prism ordering from the 3D mesh without hydromodpy metadata")
        n_base_cells = prism_connectivity.shape[0] // n_layers
        layer_indices = np.repeat(np.arange(n_layers, dtype=int), n_base_cells)
        source_cell_indices = np.tile(np.arange(n_base_cells, dtype=int), n_layers)

    return ExtrudedPrismMeshData(
        points_xyz=points_xyz,
        prism_connectivity=prism_connectivity,
        cell_type_2d=cell_type_2d,
        z_interfaces=z_interfaces,
        layer_indices=layer_indices,
        source_cell_indices=source_cell_indices,
        point_layer_indices=point_layer_indices,
        point_base_indices=point_base_indices,
        source_path=None if getattr(mesh, "path", None) is None else Path(mesh.path),
    )


def extruded_mesh_data_to_meshio(mesh_data: ExtrudedPrismMeshData):
    meshio = _require_meshio()
    cell_type = _MESHIO_CELL_TYPE_BY_2D[mesh_data.cell_type_2d]
    return meshio.Mesh(
        points=np.asarray(mesh_data.points_xyz, dtype=float),
        cells=[(cell_type, np.asarray(mesh_data.prism_connectivity, dtype=int))],
        point_data={
            _POINT_LAYER_KEY: np.asarray(mesh_data.point_layer_indices, dtype=int),
            _POINT_BASE_KEY: np.asarray(mesh_data.point_base_indices, dtype=int),
        },
        cell_data={
            _CELL_LAYER_KEY: [np.asarray(mesh_data.layer_indices, dtype=int)],
            _CELL_SOURCE_KEY: [np.asarray(mesh_data.source_cell_indices, dtype=int)],
        },
    )


def meshio_to_extruded_mesh_data(mesh: Any) -> ExtrudedPrismMeshData:
    return _infer_mesh_data(mesh)


def read_extruded_prism_mesh(path: str | Path) -> ExtrudedPrismMeshData:
    meshio = _require_meshio()
    path_obj = Path(path).resolve()
    mesh = meshio.read(path_obj)
    mesh.path = path_obj
    return meshio_to_extruded_mesh_data(mesh)


def write_extruded_prism_mesh(
    path: str | Path,
    mesh_data: ExtrudedPrismMeshData,
    *,
    file_format: str | None = None,
) -> Path:
    meshio = _require_meshio()
    path_obj = Path(path).resolve()
    meshio.write(path_obj, extruded_mesh_data_to_meshio(mesh_data), file_format=file_format)
    return path_obj


class ExtrudedPrismMesh3D:
    """3D prism mesh built by vertical extrusion of one planar 2D mesh."""

    _kind = "extruded_prism_3d"

    def __init__(
        self,
        *,
        planar_mesh: GmshPlanarMesh2D,
        z_interfaces,
        points_xyz=None,
        prism_connectivity=None,
        layer_indices=None,
        source_cell_indices=None,
        point_layer_indices=None,
        point_base_indices=None,
        source_path: str | Path | None = None,
    ) -> None:
        if not isinstance(planar_mesh, GmshPlanarMesh2D):
            raise TypeError("planar_mesh must be a GmshPlanarMesh2D instance")
        z_arr = _resolve_z_interfaces(z_interfaces=z_interfaces, top_z=None, layer_thicknesses=None)

        if points_xyz is None:
            (
                points_xyz,
                prism_connectivity,
                layer_indices,
                source_cell_indices,
                point_layer_indices,
                point_base_indices,
            ) = _build_default_components(planar_mesh, z_arr)
        elif any(v is None for v in (prism_connectivity, layer_indices, source_cell_indices, point_layer_indices, point_base_indices)):
            raise ValueError("Explicit 3D components must be passed together")

        mesh_data = ExtrudedPrismMeshData(
            points_xyz=np.asarray(points_xyz, dtype=float),
            prism_connectivity=np.asarray(prism_connectivity, dtype=int),
            cell_type_2d=planar_mesh.cell_type,
            z_interfaces=z_arr,
            layer_indices=np.asarray(layer_indices, dtype=int),
            source_cell_indices=np.asarray(source_cell_indices, dtype=int),
            point_layer_indices=np.asarray(point_layer_indices, dtype=int),
            point_base_indices=np.asarray(point_base_indices, dtype=int),
            source_path=None if source_path is None else Path(source_path),
        )
        self.planar_mesh = planar_mesh
        self.z_interfaces = np.asarray(mesh_data.z_interfaces, dtype=float)
        self.points_xyz = np.asarray(mesh_data.points_xyz, dtype=float)
        self.prism_connectivity = np.asarray(mesh_data.prism_connectivity, dtype=int)
        self.layer_indices = np.asarray(mesh_data.layer_indices, dtype=int)
        self.source_cell_indices = np.asarray(mesh_data.source_cell_indices, dtype=int)
        self.point_layer_indices = np.asarray(mesh_data.point_layer_indices, dtype=int)
        self.point_base_indices = np.asarray(mesh_data.point_base_indices, dtype=int)
        self.source_path = None if mesh_data.source_path is None else Path(mesh_data.source_path).resolve()
        self._prisms_cache: tuple[PrismCell3D, ...] | None = None

    @classmethod
    def from_planar_mesh(
        cls,
        planar_mesh: GmshPlanarMesh2D,
        *,
        z_interfaces,
    ) -> "ExtrudedPrismMesh3D":
        return cls(planar_mesh=planar_mesh, z_interfaces=z_interfaces)

    @classmethod
    def from_layer_thicknesses(
        cls,
        planar_mesh: GmshPlanarMesh2D,
        *,
        top_z: float,
        layer_thicknesses,
    ) -> "ExtrudedPrismMesh3D":
        z_interfaces = _resolve_z_interfaces(
            z_interfaces=None,
            top_z=top_z,
            layer_thicknesses=layer_thicknesses,
        )
        return cls(planar_mesh=planar_mesh, z_interfaces=z_interfaces)

    @classmethod
    def from_mesh_data(cls, mesh_data: ExtrudedPrismMeshData) -> "ExtrudedPrismMesh3D":
        planar_mesh = _build_planar_mesh_from_data(mesh_data)
        return cls(
            planar_mesh=planar_mesh,
            z_interfaces=mesh_data.z_interfaces,
            points_xyz=mesh_data.points_xyz,
            prism_connectivity=mesh_data.prism_connectivity,
            layer_indices=mesh_data.layer_indices,
            source_cell_indices=mesh_data.source_cell_indices,
            point_layer_indices=mesh_data.point_layer_indices,
            point_base_indices=mesh_data.point_base_indices,
            source_path=mesh_data.source_path,
        )

    @classmethod
    def from_meshio(cls, mesh) -> "ExtrudedPrismMesh3D":
        return cls.from_mesh_data(meshio_to_extruded_mesh_data(mesh))

    @classmethod
    def from_file(cls, path: str | Path) -> "ExtrudedPrismMesh3D":
        return cls.from_mesh_data(read_extruded_prism_mesh(path))

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def cell_type_2d(self) -> str:
        return str(self.planar_mesh.cell_type)

    @property
    def cell_type_3d(self) -> str:
        return _INTERNAL_3D_KIND_BY_2D[self.cell_type_2d]

    @property
    def n_layers(self) -> int:
        return int(self.z_interfaces.size - 1)

    @property
    def n_nodes(self) -> int:
        return int(self.points_xyz.shape[0])

    @property
    def n_prisms(self) -> int:
        return int(self.prism_connectivity.shape[0])

    @property
    def n_cells(self) -> int:
        return self.n_prisms

    @property
    def shape(self) -> tuple[int, int]:
        return (int(self.n_layers), int(self.planar_mesh.n_cells))

    @property
    def bounds(self) -> tuple[float, float, float, float, float, float]:
        x = np.asarray(self.points_xyz[:, 0], dtype=float)
        y = np.asarray(self.points_xyz[:, 1], dtype=float)
        z = np.asarray(self.points_xyz[:, 2], dtype=float)
        return (
            float(np.nanmin(x)),
            float(np.nanmin(y)),
            float(np.nanmin(z)),
            float(np.nanmax(x)),
            float(np.nanmax(y)),
            float(np.nanmax(z)),
        )

    @property
    def layer_centers_z(self) -> np.ndarray:
        return 0.5 * (self.z_interfaces[:-1] + self.z_interfaces[1:])

    @property
    def prisms(self) -> tuple[PrismCell3D, ...]:
        if self._prisms_cache is None:
            self._prisms_cache = tuple(self.iter_prisms())
        return self._prisms_cache

    def iter_prisms(self):
        for prism_idx, node_ids in enumerate(np.asarray(self.prism_connectivity, dtype=int)):
            vertices = np.asarray(self.points_xyz[node_ids], dtype=float)
            centroid = (
                float(np.mean(vertices[:, 0])),
                float(np.mean(vertices[:, 1])),
                float(np.mean(vertices[:, 2])),
            )
            yield PrismCell3D(
                index=int(prism_idx),
                kind=self.cell_type_3d,
                node_indices=tuple(int(v) for v in node_ids),
                vertices=vertices,
                centroid=centroid,
                layer_index=int(self.layer_indices[prism_idx]),
                source_cell_index=int(self.source_cell_indices[prism_idx]),
            )

    def prism_centroids(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        centroids = np.array([cell.centroid for cell in self.prisms], dtype=float)
        return centroids[:, 0], centroids[:, 1], centroids[:, 2]

    def to_prism_values(self, values):
        arr = np.asarray(values)
        expected_shape = (self.n_layers, self.planar_mesh.n_cells)
        if arr.ndim == 2:
            if arr.shape != expected_shape:
                raise ValueError("3D prism values must match shape (n_layers, n_cells_2d)")
            return arr
        flat = arr.reshape(-1)
        if flat.size != self.n_prisms:
            raise ValueError("3D prism values must contain exactly one value per prism")
        return flat.reshape(expected_shape)

    def to_mesh_data(self) -> ExtrudedPrismMeshData:
        return ExtrudedPrismMeshData(
            points_xyz=self.points_xyz,
            prism_connectivity=self.prism_connectivity,
            cell_type_2d=self.cell_type_2d,
            z_interfaces=self.z_interfaces,
            layer_indices=self.layer_indices,
            source_cell_indices=self.source_cell_indices,
            point_layer_indices=self.point_layer_indices,
            point_base_indices=self.point_base_indices,
            source_path=self.source_path,
        )

    def to_meshio(self):
        return extruded_mesh_data_to_meshio(self.to_mesh_data())

    def to_file(self, path: str | Path, *, file_format: str | None = None) -> Path:
        return write_extruded_prism_mesh(path, self.to_mesh_data(), file_format=file_format)

    def as_dict(self):
        return {
            "kind": self.kind,
            "cell_type_2d": self.cell_type_2d,
            "cell_type_3d": self.cell_type_3d,
            "n_layers": int(self.n_layers),
            "n_nodes_2d": int(self.planar_mesh.n_nodes),
            "n_cells_2d": int(self.planar_mesh.n_cells),
            "n_nodes_3d": int(self.n_nodes),
            "n_cells_3d": int(self.n_prisms),
            "shape": tuple(int(v) for v in self.shape),
            "bounds": tuple(float(v) for v in self.bounds),
            "z_interfaces": [float(v) for v in self.z_interfaces],
            "source_path": None if self.source_path is None else str(self.source_path),
        }
