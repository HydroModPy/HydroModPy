"""Plain geometric description of a solver grid (kernel-level POPO)."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt


@dataclass(frozen=True, slots=True)
class GridReference:
    """Minimal geometric description of one solver grid.

    Works for both structured and unstructured grids.  Structured grids
    set ``structured_shape`` to ``(nrow, ncol)`` which enables raster
    exports and DIS package construction.
    """

    n_cells: int
    bounds: tuple[float, float, float, float]  # xmin, ymin, xmax, ymax
    crs: str | None
    nodata: float = -9999.0
    structured_shape: tuple[int, int] | None = None
    cell_size_hint: float | None = None

    @property
    def is_structured(self) -> bool:
        return self.structured_shape is not None

    @property
    def nrow(self) -> int:
        if self.structured_shape is None:
            raise ValueError("nrow is only available for structured grids")
        return self.structured_shape[0]

    @property
    def ncol(self) -> int:
        if self.structured_shape is None:
            raise ValueError("ncol is only available for structured grids")
        return self.structured_shape[1]

    @property
    def shape(self) -> tuple[int, int]:
        return (self.nrow, self.ncol)

    @property
    def xmin(self) -> float:
        return self.bounds[0]

    @property
    def ymin(self) -> float:
        return self.bounds[1]

    @property
    def xmax(self) -> float:
        return self.bounds[2]

    @property
    def ymax(self) -> float:
        return self.bounds[3]

    @property
    def dx(self) -> float:
        if self.structured_shape is None:
            if self.cell_size_hint is not None:
                return self.cell_size_hint
            raise ValueError("dx is only available for structured grids")
        return (self.xmax - self.xmin) / self.ncol

    @property
    def dy(self) -> float:
        if self.structured_shape is None:
            if self.cell_size_hint is not None:
                return self.cell_size_hint
            raise ValueError("dy is only available for structured grids")
        return (self.ymax - self.ymin) / self.nrow

    @property
    def cell_area(self) -> float:
        return float(self.dx) * float(self.dy)

    @property
    def characteristic_length(self) -> float:
        return sqrt(self.cell_area)
