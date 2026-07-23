"""Sample per-face fields along an arbitrary straight line on the mesh.

Cross-sections used to be expressed as "row 12 of the structured grid",
which only exists on a MODFLOW DIS run. Sampling by geometry instead makes
the same section definition valid on a DISV Voronoi mesh, on a Boussinesq
triangulation and on a structured grid, and lets a config express a section
in map coordinates rather than in solver indices.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import numpy as np

if TYPE_CHECKING:
    from hydromodpy.results.run import Run


TransectOrientation = Literal["we", "sn"]


@dataclass(frozen=True, slots=True)
class Transect:
    """One sampled line across the mesh.

    ``distance`` is the curvilinear abscissa in metres from the first point.
    ``faces`` holds the mesh face index under each sample, ``-1`` where the
    line leaves the mesh.
    """

    x: np.ndarray
    y: np.ndarray
    distance: np.ndarray
    faces: np.ndarray

    @property
    def inside(self) -> np.ndarray:
        """Boolean mask of the samples that landed on a mesh face."""
        return self.faces >= 0

    def sample(self, values: np.ndarray) -> np.ndarray:
        """Project one per-face array onto the transect, NaN outside the mesh."""
        flat = np.asarray(values, dtype="float64").ravel()
        out = np.full(self.faces.shape, np.nan, dtype="float64")
        inside = self.inside
        out[inside] = flat[self.faces[inside]]
        return out


def mesh_bounds(sim: Run) -> tuple[float, float, float, float]:
    """Return the ``(xmin, ymin, xmax, ymax)`` envelope of the mesh nodes."""
    vertices = np.asarray(sim.mesh.vertices)[:, :2]
    return (
        float(vertices[:, 0].min()),
        float(vertices[:, 1].min()),
        float(vertices[:, 0].max()),
        float(vertices[:, 1].max()),
    )


def default_line(
    sim: Run,
    orientation: TransectOrientation = "we",
    *,
    through: tuple[float, float] | None = None,
) -> tuple[float, float, float, float]:
    """Return a full-width line across the mesh in the requested direction.

    The line passes through ``through`` when given, else through the
    catchment outlet when the run has one, else through the mesh centre.
    """
    xmin, ymin, xmax, ymax = mesh_bounds(sim)
    if through is None:
        try:
            through = sim.outlet
        except Exception:
            through = ((xmin + xmax) / 2.0, (ymin + ymax) / 2.0)
    px, py = float(through[0]), float(through[1])
    if orientation == "we":
        return (xmin, py, xmax, py)
    return (px, ymin, px, ymax)


def build_transect(
    sim: Run,
    *,
    line: tuple[float, float, float, float] | None = None,
    orientation: TransectOrientation = "we",
    through: tuple[float, float] | None = None,
    n_samples: int | None = None,
) -> Transect:
    """Sample the mesh along ``line`` (x0, y0, x1, y1) in projected units.

    ``n_samples`` defaults to roughly two samples per mesh cell crossed, so
    the profile resolves every cell without oversampling a coarse grid.
    """
    from hydromodpy.results.spatial_index import point_in_cell

    if line is None:
        line = default_line(sim, orientation, through=through)
    x0, y0, x1, y1 = (float(v) for v in line)
    length = float(np.hypot(x1 - x0, y1 - y0))
    if length <= 0.0:
        raise ValueError("transect line has zero length")

    if n_samples is None:
        n_faces = int(np.asarray(sim.mesh.face_node_connectivity).shape[0])
        xmin, ymin, xmax, ymax = mesh_bounds(sim)
        area = max((xmax - xmin) * (ymax - ymin), 1.0)
        typical_cell = float(np.sqrt(area / max(n_faces, 1)))
        n_samples = int(np.clip(round(2.0 * length / max(typical_cell, 1e-6)), 32, 4000))

    t = np.linspace(0.0, 1.0, n_samples)
    xs = x0 + t * (x1 - x0)
    ys = y0 + t * (y1 - y0)
    points = {str(i): (float(xs[i]), float(ys[i])) for i in range(n_samples)}
    lookup = point_in_cell(
        np.asarray(sim.mesh.vertices),
        np.asarray(sim.mesh.face_node_connectivity),
        points,
        # A full-width section legitimately starts and ends outside the mesh.
        warn_outside=False,
    )
    faces = np.array(
        [(-1 if lookup.get(str(i)) is None else int(lookup[str(i)])) for i in range(n_samples)],
        dtype="int64",
    )
    return Transect(x=xs, y=ys, distance=t * length, faces=faces)


def layer_interfaces(sim: Run) -> np.ndarray | None:
    """Return the ``(n_layers + 1, n_faces)`` vertical interfaces of the model.

    Built from the per-face topography and ``mesh/layer_thickness``. Returns
    None when the run did not persist a per-face thickness, in which case a
    caller should fall back to drawing only the top surface.
    """
    if not sim.has_field("layer_thickness"):
        return None
    topography = np.asarray(sim.field("topography"), dtype="float64").ravel()
    thickness = np.atleast_2d(np.asarray(sim.field("layer_thickness"), dtype="float64"))
    if thickness.shape[-1] != topography.size:
        return None
    interfaces = np.empty((thickness.shape[0] + 1, topography.size), dtype="float64")
    interfaces[0] = topography
    interfaces[1:] = topography[None, :] - np.cumsum(thickness, axis=0)
    return interfaces


__all__ = [
    "build_transect",
    "default_line",
    "layer_interfaces",
    "mesh_bounds",
    "Transect",
    "TransectOrientation",
]
