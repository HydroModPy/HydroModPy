"""The target cell size ``h(x)`` of a graded mesh, on the DEM grid.

Each refinement target is a term: a size on a region, then a ramp outward
whose slope never exceeds ``max_slope``. The field is the minimum of the
background and of every term, clipped between the DEM pixel and the outside
size. Distances come from an exact Euclidean distance transform between
pixel centres, so each term is Lipschitz with its own slope, and so is the
minimum: the size of two neighbouring cells never differs by more than
``max_slope`` times their distance. A region is a geometry, burnt with every
pixel it touches, or a :class:`PixelRegion`, the pixels of the grid a
criterion selected.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from rasterio.features import rasterize
from rasterio.transform import Affine
from scipy.ndimage import distance_transform_edt
from shapely.geometry.base import BaseGeometry

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.mesh.request import RasterGridSpec, SizeField

logger = get_logger(__name__)

__all__ = [
    "MAX_SIZE_FIELD_PIXELS",
    "OutsideCoarsening",
    "PixelRegion",
    "SizeTerm",
    "build_size_field",
]

MAX_SIZE_FIELD_PIXELS = 4_000_000
"""Above this pixel count the field is reduced by an integer factor, minimum per block."""


@dataclass(frozen=True, eq=False)
class PixelRegion:
    """The pixels of *grid* a criterion selected, as a boolean array, row 0 north."""

    mask: np.ndarray
    grid: RasterGridSpec

    def __post_init__(self) -> None:
        """Freeze the mask and refuse a shape other than the grid's."""
        mask = np.array(self.mask, dtype=bool, copy=True)
        if mask.shape != (self.grid.nrow, self.grid.ncol):
            raise MeshRequestError(
                f"a pixel region has shape {mask.shape}, the grid is "
                f"{(self.grid.nrow, self.grid.ncol)}"
            )
        mask.setflags(write=False)
        object.__setattr__(self, "mask", mask)

    @property
    def is_empty(self) -> bool:
        """Whether no pixel is selected."""
        return not bool(self.mask.any())


@dataclass(frozen=True)
class SizeTerm:
    """A size on a region, growing back to the background outside it.

    A geometry ``region`` is burnt with every pixel it touches, a
    :class:`PixelRegion` is taken as it is. Outside, the size grows by
    ``(h0 - size_m) / ramp_m`` per metre, never faster than ``max_slope``.
    """

    name: str
    region: BaseGeometry | PixelRegion
    size_m: float
    ramp_m: float

    def __post_init__(self) -> None:
        """Refuse an empty region, a size <= 0 or a negative ramp."""
        if self.region is None or self.region.is_empty:
            raise MeshRequestError(f"size term {self.name!r} has an empty region")
        if not math.isfinite(self.size_m) or self.size_m <= 0.0:
            raise MeshRequestError(
                f"size term {self.name!r}: size must be > 0 m, got {self.size_m}"
            )
        if not math.isfinite(self.ramp_m) or self.ramp_m < 0.0:
            raise MeshRequestError(
                f"size term {self.name!r}: ramp must be >= 0 m, got {self.ramp_m}"
            )


@dataclass(frozen=True)
class OutsideCoarsening:
    """Coarser cells outside the catchment: ``factor`` times ``h0`` past the transition."""

    region: BaseGeometry
    factor: float
    transition_m: float

    def __post_init__(self) -> None:
        """Refuse an empty catchment, a factor below 1 or a negative transition."""
        if self.region is None or self.region.is_empty:
            raise MeshRequestError("the outside coarsening needs a non-empty catchment region")
        if not math.isfinite(self.factor) or self.factor < 1.0:
            raise MeshRequestError(f"outside factor must be >= 1, got {self.factor}")
        if not math.isfinite(self.transition_m) or self.transition_m < 0.0:
            raise MeshRequestError(f"transition distance must be >= 0 m, got {self.transition_m}")


def build_size_field(
    grid: RasterGridSpec,
    *,
    h0: float,
    h_floor: float,
    terms: Sequence[SizeTerm],
    outside: OutsideCoarsening | None,
    max_slope: float,
) -> SizeField:
    """Return ``h = clip(min(background, terms), h_floor, factor * h0)`` on *grid*.

    The background is ``h0`` inside the catchment and ramps to ``factor * h0``
    outside it over ``max(transition, (factor - 1) h0 / max_slope)``. A term
    whose size is not finer than ``h0`` refines nothing and is skipped. Above
    :data:`MAX_SIZE_FIELD_PIXELS` the field is reduced by an integer factor,
    each coarse pixel taking the minimum of its block.
    """
    if not math.isfinite(max_slope) or max_slope <= 0.0:
        raise MeshRequestError(f"max_slope must be > 0, got {max_slope}")
    if not math.isfinite(h_floor) or h_floor <= 0.0:
        raise MeshRequestError(f"the size floor must be > 0 m, got {h_floor}")
    if not math.isfinite(h0) or h0 < h_floor:
        raise MeshRequestError(f"the background size {h0} m is finer than the floor {h_floor} m")
    factor = 1.0 if outside is None else float(outside.factor)
    values = np.full((grid.nrow, grid.ncol), float(h0))
    if outside is not None and factor > 1.0:
        transition = max(outside.transition_m, (factor - 1.0) * h0 / max_slope)
        distance = _distance_to(outside.region, grid)
        if distance is not None:
            values = h0 * (1.0 + (factor - 1.0) * np.clip(distance / transition, 0.0, 1.0))
    for term in terms:
        if term.size_m >= h0:
            continue
        if term.size_m < h_floor:
            # The floor is the DEM pixel: a finer request is clipped, so say it.
            logger.warning(
                "mesh size term %r asks for %.2f m, finer than the %.2f m floor "
                "(DEM pixel); cells there are %.2f m at best",
                term.name,
                term.size_m,
                h_floor,
                h_floor,
            )
        distance = _distance_to(term.region, grid)
        if distance is None:
            continue
        slope = (
            max_slope if term.ramp_m == 0.0 else min((h0 - term.size_m) / term.ramp_m, max_slope)
        )
        np.minimum(values, term.size_m + slope * distance, out=values)
    np.clip(values, h_floor, factor * h0, out=values)
    return _reduced(SizeField(values=values, grid=grid))


def _distance_to(region: BaseGeometry | PixelRegion, grid: RasterGridSpec) -> np.ndarray | None:
    """Distance in metres from each pixel centre to the pixels *region* touches, or None."""
    if isinstance(region, PixelRegion):
        if region.grid != grid:
            raise MeshRequestError("a pixel region lies on another grid than the size field")
        if region.is_empty:
            return None
        return distance_transform_edt(~region.mask, sampling=(grid.dy, grid.dx))
    mask = rasterize(
        [(region, 1)],
        out_shape=(grid.nrow, grid.ncol),
        transform=Affine(grid.dx, 0.0, grid.xmin, 0.0, -grid.dy, grid.ymax),
        fill=0,
        all_touched=True,
        dtype="uint8",
    ).astype(bool)
    if not mask.any():
        return None
    return distance_transform_edt(~mask, sampling=(grid.dy, grid.dx))


def _reduced(field: SizeField) -> SizeField:
    """The field itself, or its block minimum when it holds too many pixels."""
    grid = field.grid
    if grid.nrow * grid.ncol <= MAX_SIZE_FIELD_PIXELS:
        return field
    block = math.ceil(math.sqrt(grid.nrow * grid.ncol / MAX_SIZE_FIELD_PIXELS))
    while math.ceil(grid.nrow / block) * math.ceil(grid.ncol / block) > MAX_SIZE_FIELD_PIXELS:
        block += 1
    nrow = math.ceil(grid.nrow / block)
    ncol = math.ceil(grid.ncol / block)
    # Edge padding keeps the block minimum Lipschitz: a padded pixel copies its
    # nearest pixel, which is never farther from a neighbouring block.
    padded = np.pad(
        field.values,
        ((0, nrow * block - grid.nrow), (0, ncol * block - grid.ncol)),
        mode="edge",
    )
    values = padded.reshape(nrow, block, ncol, block).min(axis=(1, 3))
    coarse = RasterGridSpec(
        xmin=grid.xmin,
        xmax=grid.xmin + ncol * block * grid.dx,
        ymin=grid.ymax - nrow * block * grid.dy,
        ymax=grid.ymax,
        dx=block * grid.dx,
        dy=block * grid.dy,
        nrow=nrow,
        ncol=ncol,
        crs_wkt=grid.crs_wkt,
    )
    return SizeField(values=values, grid=coarse)
