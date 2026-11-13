"""Quality of the stored mesh, one value per cell, rebuilt on read and never stored.

Eight static fields describe how good the cells of a run are: ``mesh_cell_area``,
``mesh_neighbour_ratio``, ``mesh_center_offset``, ``mesh_nonorthogonality``,
``mesh_bisection_offset``, ``mesh_min_angle``, ``mesh_max_angle`` and
``mesh_concavity``. They use the
formulas of :mod:`hydromodpy.mesh.planar.quality`, by cell, on the geometry
derived from the stored vertices and connectivity.

The area, the neighbor ratio, the two angles and the concavity need geometry
only, so every run serves them. The offset, the non-orthogonality and the bisection
offset need the cell centers of the mesh, which a run stores since the cell-mesh
layout (``mesh/face_x``, ``mesh/face_y``). A store without them has the vertex mean
at best, not the center the solver used: those three fields are refused with the
reason rather than computed on a guess.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

from hydromodpy.mesh.planar.geometry import DerivedGeometry, derive_geometry_from_rows
from hydromodpy.mesh.planar.quality import (
    RELATIVE_FACE_TOLERANCE,
    STRAIGHT_CORNER_DEG,
    cell_angle_range,
    cell_edge_max,
    edge_bisection_offset,
    edge_nonorthogonality,
    edge_size_ratio,
)
from hydromodpy.results.field_registry import SHAPE_FACE, FieldDescriptor

__all__ = [
    "MESH_QUALITY_DESCRIPTORS",
    "mesh_quality_unavailable_reason",
    "mesh_quality_values",
]


def _descriptor(
    name: str, label: str, quantity: str, long_name: str, units: str, cell_methods: str
) -> FieldDescriptor:
    return FieldDescriptor(
        public_name=name,
        zarr_path=f"mesh/{name}",
        standard_name="",
        quantity=quantity,
        label=label,
        long_name=long_name,
        units=units,
        shape=SHAPE_FACE,
        cell_methods=cell_methods,
        derived_by="core",
    )


MESH_QUALITY_DESCRIPTORS: dict[str, FieldDescriptor] = {
    descriptor.public_name: descriptor
    for descriptor in (
        _descriptor(
            "mesh_cell_area",
            "Mesh cell area",
            "area",
            "Plan area of the mesh cell",
            "m2",
            "area: sum",
        ),
        _descriptor(
            "mesh_neighbour_ratio",
            "Neighbour size ratio",
            "ratio",
            "Largest ratio of the side of the cell to the side of a neighbour, or the inverse",
            "1",
            "area: maximum",
        ),
        _descriptor(
            "mesh_center_offset",
            "Centre offset",
            "fraction",
            "Distance of the cell centre to the area centroid, over the side of the cell",
            "1",
            "area: point",
        ),
        _descriptor(
            "mesh_nonorthogonality",
            "Non-orthogonality",
            "angle",
            "Largest angle between the line joining two cell centres and the normal of "
            "the face they share",
            "degree",
            "area: maximum",
        ),
        _descriptor(
            "mesh_bisection_offset",
            "Bisection offset",
            "fraction",
            "Largest distance from the middle of a face of the cell to where the line "
            "joining the two cell centres crosses it, over the face length",
            "1",
            "area: maximum",
        ),
        _descriptor(
            "mesh_min_angle",
            "Minimum cell angle",
            "angle",
            "Smallest interior angle at a corner of the cell",
            "degree",
            "area: minimum",
        ),
        _descriptor(
            "mesh_max_angle",
            "Maximum cell angle",
            "angle",
            "Largest interior angle at a corner of the cell",
            "degree",
            "area: maximum",
        ),
        _descriptor(
            "mesh_concavity",
            "Cell concavity",
            "angle",
            "Largest excess over 180 degrees of an interior angle of the cell, 0 for a convex cell",
            "degree",
            "area: maximum",
        ),
    )
}
"""The descriptors of the quality fields, kept out of the field registry.

The registry lists what a store can hold; these fields are only ever computed."""

_NEEDS_CENTRES = frozenset({"mesh_center_offset", "mesh_nonorthogonality", "mesh_bisection_offset"})


def mesh_quality_unavailable_reason(root: Any, name: str) -> str | None:
    """Say why a quality field cannot be served from this store, ``None`` when it can."""
    if name not in MESH_QUALITY_DESCRIPTORS:
        raise KeyError(f"'{name}' is not a mesh quality field")
    mesh = root.get("mesh")
    if mesh is None or "vertices" not in mesh or "face_node_connectivity" not in mesh:
        return "the run stored no mesh geometry"
    if name in _NEEDS_CENTRES and not ("face_x" in mesh and "face_y" in mesh):
        return "the run stored no cell centres, only the vertices"
    return None


def mesh_quality_values(root: Any, name: str) -> np.ndarray:
    """Return the quality field ``name`` of the stored mesh, one value per cell.

    Raises
    ------
    KeyError
        The store cannot serve the field (see :func:`mesh_quality_unavailable_reason`).
    """
    reason = mesh_quality_unavailable_reason(root, name)
    if reason is not None:
        raise KeyError(f"{name} is not available for this run: {reason}")
    mesh = root["mesh"]
    geometry = derive_geometry_from_rows(
        np.asarray(mesh["vertices"][:], dtype=np.float64),
        np.asarray(mesh["face_node_connectivity"][:]),
    )
    return _COMPUTE[name](mesh, geometry)


def _cell_area(mesh: Any, geometry: DerivedGeometry) -> np.ndarray:
    return geometry.areas.copy()


def _neighbour_ratio(mesh: Any, geometry: DerivedGeometry) -> np.ndarray:
    return cell_edge_max(geometry, edge_size_ratio(geometry))


def _centres(mesh: Any) -> np.ndarray:
    return np.column_stack(
        (
            np.asarray(mesh["face_x"][:], dtype=np.float64),
            np.asarray(mesh["face_y"][:], dtype=np.float64),
        )
    )


def _center_offset(mesh: Any, geometry: DerivedGeometry) -> np.ndarray:
    gap = _centres(mesh) - geometry.area_centroids
    return np.hypot(gap[:, 0], gap[:, 1]) / np.sqrt(geometry.areas)


def _shortest_measured_face(mesh: Any, geometry: DerivedGeometry) -> float:
    """Return the length [m] under which a face is too short for an angle to mean anything.

    The threshold the QA of the run measured with when it stored one, else the
    QA default: a thousandth of the median face length.
    """
    qa = mesh.attrs.get("qa")
    if isinstance(qa, dict) and qa.get("min_face_length_m") is not None:
        return float(qa["min_face_length_m"])
    return RELATIVE_FACE_TOLERANCE * float(np.median(geometry.edge_length))


def _measured_faces(mesh: Any, geometry: DerivedGeometry) -> np.ndarray:
    """Return the interior faces long enough for an angle or an offset to mean anything."""
    interior = geometry.edge_cells[:, 1] >= 0
    return interior & (geometry.edge_length > _shortest_measured_face(mesh, geometry))


def _vertices(mesh: Any) -> np.ndarray:
    return np.asarray(mesh["vertices"][:], dtype=np.float64)[:, :2]


def _nonorthogonality(mesh: Any, geometry: DerivedGeometry) -> np.ndarray:
    keep = _measured_faces(mesh, geometry)
    return cell_edge_max(
        geometry, edge_nonorthogonality(_centres(mesh), _vertices(mesh), geometry, keep)
    )


def _bisection_offset(mesh: Any, geometry: DerivedGeometry) -> np.ndarray:
    keep = _measured_faces(mesh, geometry)
    return cell_edge_max(
        geometry, edge_bisection_offset(_centres(mesh), _vertices(mesh), geometry, keep)
    )


def _min_angle(mesh: Any, geometry: DerivedGeometry) -> np.ndarray:
    return cell_angle_range(geometry.padded_connectivity, _vertices(mesh))[0]


def _max_angle(mesh: Any, geometry: DerivedGeometry) -> np.ndarray:
    return cell_angle_range(geometry.padded_connectivity, _vertices(mesh))[1]


def _concavity(mesh: Any, geometry: DerivedGeometry) -> np.ndarray:
    """Return the largest reflex excess of each cell; a corner within the tolerance is straight."""
    excess = _max_angle(mesh, geometry) - 180.0
    return np.where(np.isnan(excess) | (excess > STRAIGHT_CORNER_DEG), excess, 0.0)


_COMPUTE: dict[str, Callable[[Any, DerivedGeometry], np.ndarray]] = {
    "mesh_cell_area": _cell_area,
    "mesh_neighbour_ratio": _neighbour_ratio,
    "mesh_center_offset": _center_offset,
    "mesh_nonorthogonality": _nonorthogonality,
    "mesh_bisection_offset": _bisection_offset,
    "mesh_min_angle": _min_angle,
    "mesh_max_angle": _max_angle,
    "mesh_concavity": _concavity,
}
