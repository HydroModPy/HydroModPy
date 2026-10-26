"""A field of an earlier run of the project, as the mesh planner reads it.

The planner reads no store: the mesh step reads the field of the earlier run
and hands its extremes over time, per cell of that run's mesh, as a
:class:`RunFieldEnvelope`. The minimum over time says whether a field ever
went below a threshold, the maximum whether it ever went above one, so the
seepage front of a wet winter counts even when the run ends in a dry summer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import shapely
from rasterio.features import rasterize
from rasterio.transform import Affine

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh.ops.vector_cell_mask import cell_polygons
from hydromodpy.spatial.mesh.request import RasterGridSpec

__all__ = ["RunFieldEnvelope", "cells_on_grid"]


@dataclass(frozen=True, eq=False)
class RunFieldEnvelope:
    """The extremes over time of one field of an earlier run, per cell of its mesh.

    ``minimum`` and ``maximum`` are NaN where the field was never defined
    (a dry cell has no water table). ``unit`` is the unit of both.
    """

    sim_id: str
    run: str
    field: str
    unit: str
    vertices: np.ndarray
    connectivity: np.ndarray | Sequence[np.ndarray]
    minimum: np.ndarray
    maximum: np.ndarray

    def __post_init__(self) -> None:
        """Refuse extremes that do not hold one value per cell."""
        minimum = np.asarray(self.minimum, dtype=float).reshape(-1)
        maximum = np.asarray(self.maximum, dtype=float).reshape(-1)
        if minimum.shape != maximum.shape or minimum.size != len(self.connectivity):
            raise MeshRequestError(
                f"the {self.field} of run {self.run!r} holds {minimum.size} minima and "
                f"{maximum.size} maxima for {len(self.connectivity)} cells"
            )
        object.__setattr__(self, "minimum", minimum)
        object.__setattr__(self, "maximum", maximum)

    def passing(self, *, below: float | None, above: float | None) -> np.ndarray:
        """The cells whose field went below *below*, or above *above*, at some time step."""
        if (below is None) == (above is None):
            raise MeshRequestError("a threshold is either below or above, and one of them")
        with np.errstate(invalid="ignore"):
            if below is not None:
                return np.isfinite(self.minimum) & (self.minimum < below)
            return np.isfinite(self.maximum) & (self.maximum > above)


def cells_on_grid(
    vertices: np.ndarray,
    connectivity: np.ndarray | Sequence[np.ndarray],
    selected: np.ndarray,
    grid: RasterGridSpec,
) -> np.ndarray:
    """The pixels of *grid* inside the *selected* cells, row 0 north.

    A pixel is inside a cell when its centre is. The pixel under the centroid
    of each selected cell is taken too, so a cell smaller than a pixel still
    marks one.
    """
    polygons = cell_polygons(vertices, connectivity)
    chosen = [
        polygon
        for polygon, keep in zip(polygons, np.asarray(selected, dtype=bool), strict=True)
        if keep and polygon is not None
    ]
    mask = np.zeros((grid.nrow, grid.ncol), dtype=bool)
    if not chosen:
        return mask
    mask |= rasterize(
        [(polygon, 1) for polygon in chosen],
        out_shape=(grid.nrow, grid.ncol),
        transform=Affine(grid.dx, 0.0, grid.xmin, 0.0, -grid.dy, grid.ymax),
        fill=0,
        all_touched=False,
        dtype="uint8",
    ).astype(bool)
    centres = shapely.get_coordinates(shapely.centroid(np.asarray(chosen, dtype=object)))
    cols = np.floor((centres[:, 0] - grid.xmin) / grid.dx).astype(np.int64)
    rows = np.floor((grid.ymax - centres[:, 1]) / grid.dy).astype(np.int64)
    inside = (rows >= 0) & (rows < grid.nrow) & (cols >= 0) & (cols < grid.ncol)
    mask[rows[inside], cols[inside]] = True
    return mask
