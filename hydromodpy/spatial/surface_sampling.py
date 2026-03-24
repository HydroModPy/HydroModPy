"""Prepared samplers for repeated georeferenced surface sampling.

The bundle export and several runtime solvers repeatedly sample the same
topography/substratum rasters at many coordinates. Re-extracting the raw array
and raster-support metadata on every call is expensive on large domains.

This module centralizes the "prepare once, sample many times" pattern:
- normalize one ``Surface`` (or surface-like object) to a NumPy array,
- replace nodata sentinels with ``NaN`` once,
- cache the scalar raster-support metadata needed for interpolation,
- expose vectorized sampling helpers that operate on whole coordinate arrays.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class PreparedSurfaceSampler:
    """One ready-to-use raster sampler built from a surface-like object."""

    values: np.ndarray
    support: object | None
    xmin: float | None
    xmax: float | None
    ymin: float | None
    ymax: float | None
    dx: float | None
    dy: float | None
    nrows: int | None
    ncols: int | None

    @classmethod
    def from_surface(cls, surface: object) -> "PreparedSurfaceSampler":
        """Build one sampler from a HydroModPy ``Surface``-like object."""
        if surface is None:
            raise ValueError("surface is required for georeferenced sampling")
        as_array = getattr(surface, "as_array", None)
        if callable(as_array):
            values = np.asarray(as_array(), dtype=float)
        else:
            values = np.asarray(getattr(surface, "values"), dtype=float)
        support = getattr(surface, "support", None)
        nodata = None if support is None else getattr(support, "nodata", None)
        if nodata is not None:
            values = np.where(values == float(nodata), np.nan, values)
        if support is None:
            return cls(
                values=values,
                support=None,
                xmin=None,
                xmax=None,
                ymin=None,
                ymax=None,
                dx=None,
                dy=None,
                nrows=None,
                ncols=None,
            )
        return cls(
            values=values,
            support=support,
            xmin=_optional_float(getattr(support, "xmin", None)),
            xmax=_optional_float(getattr(support, "xmax", None)),
            ymin=_optional_float(getattr(support, "ymin", None)),
            ymax=_optional_float(getattr(support, "ymax", None)),
            dx=_optional_float(getattr(support, "dx", None)),
            dy=_optional_float(getattr(support, "dy", None)),
            nrows=_optional_int(getattr(support, "nrows", None)),
            ncols=_optional_int(getattr(support, "ncols", None)),
        )

    @property
    def has_complete_support(self) -> bool:
        """Return whether bilinear sampling can be evaluated on this sampler."""
        return (
            self.support is not None
            and self.xmin is not None
            and self.xmax is not None
            and self.ymin is not None
            and self.ymax is not None
            and self.dx is not None
            and self.dy is not None
            and self.nrows is not None
            and self.ncols is not None
        )

    def sample(self, x_values: Any, y_values: Any) -> np.ndarray:
        """Sample the prepared surface at one scalar or array of XY coordinates."""
        x_arr = np.asarray(x_values, dtype=float)
        y_arr = np.asarray(y_values, dtype=float)
        if x_arr.shape != y_arr.shape:
            raise ValueError("x_values and y_values must have the same shape")
        if not self.has_complete_support:
            return np.full(x_arr.shape, np.nan, dtype=float)

        flat_x = x_arr.reshape(-1)
        flat_y = y_arr.reshape(-1)
        xmin = float(self.xmin)
        xmax = float(self.xmax)
        ymin = float(self.ymin)
        ymax = float(self.ymax)
        dx = float(self.dx)
        dy = float(self.dy)
        nrows = int(self.nrows)
        ncols = int(self.ncols)
        if dx <= 0.0 or dy <= 0.0 or nrows < 1 or ncols < 1:
            return np.full(x_arr.shape, np.nan, dtype=float)

        inside = (
            (flat_x >= xmin)
            & (flat_x <= xmax)
            & (flat_y >= ymin)
            & (flat_y <= ymax)
        )
        col_float = (flat_x - xmin) / dx - 0.5
        row_float = (ymax - flat_y) / dy - 0.5

        col0 = np.floor(col_float).astype(int)
        row0 = np.floor(row_float).astype(int)
        col1 = col0 + 1
        row1 = row0 + 1

        wc = col_float - np.floor(col_float)
        wr = row_float - np.floor(row_float)

        row0_clamped = np.clip(row0, 0, nrows - 1)
        row1_clamped = np.clip(row1, 0, nrows - 1)
        col0_clamped = np.clip(col0, 0, ncols - 1)
        col1_clamped = np.clip(col1, 0, ncols - 1)

        values = self.values
        v00 = values[row0_clamped, col0_clamped]
        v01 = values[row0_clamped, col1_clamped]
        v10 = values[row1_clamped, col0_clamped]
        v11 = values[row1_clamped, col1_clamped]

        w00 = (1.0 - wr) * (1.0 - wc)
        w01 = (1.0 - wr) * wc
        w10 = wr * (1.0 - wc)
        w11 = wr * wc

        values_stack = np.vstack((v00, v01, v10, v11))
        weights_stack = np.vstack((w00, w01, w10, w11))
        valid = np.isfinite(values_stack)
        weights_stack = np.where(valid, weights_stack, 0.0)
        numerators = np.nansum(values_stack * weights_stack, axis=0)
        denominators = np.sum(weights_stack, axis=0)
        sampled = np.full(flat_x.shape, np.nan, dtype=float)
        np.divide(
            numerators,
            denominators,
            out=sampled,
            where=denominators > 0.0,
        )
        sampled = np.where(inside, sampled, np.nan)
        return sampled.reshape(x_arr.shape)

    def sample_points_xy(self, points_xy: Any) -> np.ndarray:
        """Sample an ``(n_points, 2)`` coordinate array."""
        coords = np.asarray(points_xy, dtype=float)
        if coords.ndim != 2 or coords.shape[1] != 2:
            raise ValueError("points_xy must have shape (n_points, 2)")
        return self.sample(coords[:, 0], coords[:, 1]).reshape(-1)


def _optional_float(value: object | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_int(value: object | None) -> int | None:
    if value is None:
        return None
    return int(value)


__all__ = ["PreparedSurfaceSampler"]
