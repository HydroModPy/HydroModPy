"""Raw payload dataclasses and constants for 3D prism extrusions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

MESHIO_CELL_TYPE_BY_2D = {
    "triangle": "wedge",
    "quadrilateral": "hexahedron",
}
INTERNAL_3D_KIND_BY_2D = {
    "triangle": "triangular_prism",
    "quadrilateral": "quadrilateral_prism",
}
NODES_PER_3D_CELL = {
    "triangle": 6,
    "quadrilateral": 8,
}


def resolve_z_interfaces(
    *,
    z_interfaces,
    top_z: float | None,
    layer_thicknesses,
) -> np.ndarray:
    """Normalize vertical interfaces to one strictly monotonic 1D float array."""
    if z_interfaces is not None:
        if top_z is not None or layer_thicknesses is not None:
            raise ValueError("Pass either z_interfaces or top_z/layer_thicknesses, not both")
        arr = np.asarray(z_interfaces, dtype=float).reshape(-1)
    else:
        if top_z is None or layer_thicknesses is None:
            raise ValueError(
                "top_z and layer_thicknesses are required when z_interfaces is omitted"
            )
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


def stable_unique(values) -> np.ndarray:
    """Return unique values while preserving the original layered ordering."""
    arr = np.asarray(values, dtype=float).reshape(-1)
    out: list[float] = []
    for value in arr:
        if not out or not np.isclose(value, out[-1], rtol=0.0, atol=1e-9):
            out.append(float(value))
    return np.asarray(out, dtype=float)


@dataclass(frozen=True)
class PrismCell3D:
    """One explicit 3D prism cell with cached geometry metadata."""

    index: int
    kind: str
    node_indices: tuple[int, ...]
    vertices: np.ndarray
    centroid: tuple[float, float, float]
    layer_index: int
    source_cell_index: int


@dataclass(frozen=True)
class ExtrudedPrismMeshData:
    """Raw 3D extrusion payload independent from Field/FieldParam concerns.

    This is the serialization-friendly form used by the reader/writer helpers.
    """

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
        if cell_type_2d not in NODES_PER_3D_CELL:
            raise ValueError("cell_type_2d must be 'triangle' or 'quadrilateral'")

        prism_connectivity = np.asarray(self.prism_connectivity, dtype=int)
        expected_width = NODES_PER_3D_CELL[cell_type_2d]
        if prism_connectivity.ndim != 2 or prism_connectivity.shape[1] != expected_width:
            raise ValueError(
                f"{cell_type_2d} extrusion connectivity must have shape (n_cells, {expected_width})"
            )
        if np.any(prism_connectivity < 0) or np.any(prism_connectivity >= points_xyz.shape[0]):
            raise ValueError("prism connectivity references point indices outside points_xyz")

        z_interfaces = resolve_z_interfaces(
            z_interfaces=self.z_interfaces, top_z=None, layer_thicknesses=None
        )
        n_prisms = int(prism_connectivity.shape[0])
        n_points = int(points_xyz.shape[0])

        layer_indices = np.asarray(self.layer_indices, dtype=int).reshape(-1)
        source_cell_indices = np.asarray(self.source_cell_indices, dtype=int).reshape(-1)
        point_layer_indices = np.asarray(self.point_layer_indices, dtype=int).reshape(-1)
        point_base_indices = np.asarray(self.point_base_indices, dtype=int).reshape(-1)

        if layer_indices.size != n_prisms or source_cell_indices.size != n_prisms:
            raise ValueError(
                "layer_indices and source_cell_indices must match the number of prisms"
            )
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
        return INTERNAL_3D_KIND_BY_2D[self.cell_type_2d]
