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


def basin_area_m2(sim: Run) -> float:
    """Return the area of the whole faces of the basin of D, in m2.

    This is the support of the ``catchment`` row of the budget, so it is the
    denominator that row needs to become a depth. It is not the area of the
    delineated polygon: the row counts each face whole. Raises ``ValueError``
    when the run stores no basin of D, because a guessed area would put a wrong
    depth on the axis.
    """
    stored = sim.descent.stored_basin()
    if stored is None:
        raise ValueError(
            f"Run {sim.sim_id} stores no basin of D, so the area of its catchment budget "
            "row is unknown. Draw the fluxes in m3/s."
        )
    return float(face_areas(sim)[np.asarray(stored[0], dtype=bool)].sum())


__all__ = ["basin_area_m2", "domain_area_m2", "face_areas", "face_centroids", "face_polygons"]
