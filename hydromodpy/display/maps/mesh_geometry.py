"""Mesh geometry helpers shared by the spatial figures and overlays.

All of them read the UGRID face/vertex arrays persisted by every backend, so
they behave identically on a structured MODFLOW DIS grid, a MODFLOW 6 DISV
Voronoi or triangular mesh, and a Boussinesq triangulation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from hydromodpy.results.run import Run


def face_polygons(sim: Run) -> list[np.ndarray]:
    """Return one ``(n_vertices, 2)`` corner array per mesh face."""
    mesh = sim.mesh
    vertices = np.asarray(mesh.vertices)[:, :2]
    fnc = np.asarray(mesh.face_node_connectivity)
    polygons = []
    for row in fnc:
        nodes = row[row >= 0] if row.dtype.kind in "iu" else row[~np.isnan(row)]
        polygons.append(vertices[nodes.astype(int)])
    return polygons


def face_centroids(sim: Run) -> np.ndarray:
    """Return the ``(n_faces, 2)`` centroid of every mesh face."""
    return np.array([polygon.mean(axis=0) for polygon in face_polygons(sim)], dtype="float64")


def face_areas(sim: Run) -> np.ndarray:
    """Return the ``(n_faces,)`` planar area of every mesh face, in m2.

    Uses the shoelace formula, which is exact for the convex cells both
    structured grids and Voronoi/triangular meshes produce.
    """
    areas = np.empty(len(face_polygons(sim)), dtype="float64")
    for index, polygon in enumerate(face_polygons(sim)):
        x, y = polygon[:, 0], polygon[:, 1]
        areas[index] = 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
    return areas


def domain_area_m2(sim: Run) -> float:
    """Return the total planar area of the model domain, in m2.

    This is the denominator a domain water balance must use to convert a
    volumetric flux into a depth: the catchment area would be wrong whenever
    the active grid extends past the catchment (a buffered box, an
    inter-basin buffer ring).
    """
    return float(face_areas(sim).sum())


__all__ = ["domain_area_m2", "face_areas", "face_centroids", "face_polygons"]
