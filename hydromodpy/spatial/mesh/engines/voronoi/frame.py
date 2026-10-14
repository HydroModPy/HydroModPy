"""The local frame of the Voronoi generator and the size field sampled in it.

Qhull and GEOS lose digits on Lambert-93 coordinates (1e5 to 1e6 m): two seeds
a few metres apart can give two identical cells. Every step of the generator
therefore works in a frame centred on a fixed origin, a multiple of 1 km near
the centre of the domain bounding box. The origin does not depend on the order
of the domain vertices, and a coordinate moved there and back is the same
float (the subtraction of a nearby multiple of 1 km is exact).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TypeVar, overload

import numpy as np
import shapely
from shapely.geometry.base import BaseGeometry

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh.request import MeshRequest, SizeField
from hydromodpy.spatial.mesh.sizing.size_field import sample_size_field

__all__ = ["ORIGIN_STEP_M", "LocalFrame", "SizeSampler", "local_frame"]

ORIGIN_STEP_M = 1000.0
"""The origin of the local frame is a multiple of this length [m]."""

_Geometry = TypeVar("_Geometry", bound=BaseGeometry)


@dataclass(frozen=True)
class LocalFrame:
    """A translation of the world frame: ``local = world - origin``."""

    origin: tuple[float, float]

    def __post_init__(self) -> None:
        """Refuse a non-finite origin."""
        if len(self.origin) != 2 or not all(math.isfinite(v) for v in self.origin):
            raise MeshRequestError(f"a local frame needs a finite (x, y) origin, got {self.origin}")
        object.__setattr__(self, "origin", (float(self.origin[0]), float(self.origin[1])))

    @property
    def offset(self) -> np.ndarray:
        """The origin as a float64 ``(2,)`` array."""
        return np.asarray(self.origin, dtype=np.float64)

    @overload
    def to_local(self, value: np.ndarray) -> np.ndarray: ...
    @overload
    def to_local(self, value: _Geometry) -> _Geometry: ...
    def to_local(self, value: np.ndarray | BaseGeometry) -> np.ndarray | BaseGeometry:
        """Move points ``(n, 2)`` or a shapely geometry from the world to the local frame."""
        return self._shift(value, -self.offset)

    @overload
    def to_world(self, value: np.ndarray) -> np.ndarray: ...
    @overload
    def to_world(self, value: _Geometry) -> _Geometry: ...
    def to_world(self, value: np.ndarray | BaseGeometry) -> np.ndarray | BaseGeometry:
        """Move points ``(n, 2)`` or a shapely geometry from the local to the world frame."""
        return self._shift(value, self.offset)

    @staticmethod
    def _shift(value: np.ndarray | BaseGeometry, delta: np.ndarray) -> np.ndarray | BaseGeometry:
        """Translate *value* by *delta*, keeping its kind."""
        if isinstance(value, BaseGeometry):
            return shapely.transform(value, lambda xy: xy + delta)
        points = np.asarray(value, dtype=np.float64)
        if points.ndim != 2 or points.shape[1] != 2:
            raise ValueError(f"points must have shape (n, 2), got {points.shape}")
        return points + delta


def local_frame(domain: BaseGeometry) -> LocalFrame:
    """The frame centred on the multiple of 1 km nearest the centre of the domain bounding box."""
    if domain.is_empty:
        raise MeshRequestError("a local frame needs a non-empty domain")
    xmin, ymin, xmax, ymax = domain.bounds
    x = round(0.5 * (xmin + xmax) / ORIGIN_STEP_M) * ORIGIN_STEP_M
    y = round(0.5 * (ymin + ymax) / ORIGIN_STEP_M) * ORIGIN_STEP_M
    return LocalFrame((float(x), float(y)))


class SizeSampler:
    """The target cell size ``h`` [m] at local points, bilinear on the size field grid.

    Past the edge of the grid the size is held at its edge value. A request
    without a size field gets a constant field at its nominal size, on its grid.
    """

    def __init__(self, field: SizeField, frame: LocalFrame) -> None:
        """Sample *field* at points given in *frame*."""
        self.field = field
        self.frame = frame
        self.h_min = float(field.values.min())
        self.h_max = float(field.values.max())

    @classmethod
    def of_request(cls, request: MeshRequest, frame: LocalFrame) -> SizeSampler:
        """The sampler of the request size field, or of its nominal size when it has none."""
        if request.size_field is not None:
            return cls(request.size_field, frame)
        grid = request.grid
        values = np.full((grid.nrow, grid.ncol), float(request.nominal_size_m))
        return cls(SizeField(values=values, grid=grid), frame)

    def __call__(self, xy: np.ndarray) -> np.ndarray:
        """Size [m] at local points ``(n, 2)``."""
        return sample_size_field(self.field, self.frame.to_world(np.reshape(xy, (-1, 2))))

    def pixel_centres(self) -> tuple[np.ndarray, float]:
        """Local centres ``(nrow * ncol, 2)`` of the field pixels, row 0 north, and one pixel area."""
        grid = self.field.grid
        x = grid.xmin + (np.arange(grid.ncol) + 0.5) * grid.dx
        y = grid.ymax - (np.arange(grid.nrow) + 0.5) * grid.dy
        gx, gy = np.meshgrid(x, y)
        world = np.column_stack([gx.ravel(), gy.ravel()])
        return self.frame.to_local(world), grid.dx * grid.dy
