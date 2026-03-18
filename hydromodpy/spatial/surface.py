from __future__ import annotations
"""
Surface abstractions for domain topography and derived vertical supports.

This module intentionally keeps all surface-level operations in one place:
- store one 2D raster-like array,
- carry its optional ``RasterSupport``,
- derive new surfaces from an existing one,
- validate vertical ordering between surfaces.

The goal is to keep ``Domain`` focused on orchestration while all array-level
transformations that conceptually belong to a surface remain implemented here.
"""

from dataclasses import dataclass
from typing import Any

import numpy as np

from hydromodpy.spatial.raster_support import RasterSupport


@dataclass
class Surface:
    """
    One raster-like surface plus its optional spatial support.

    Parameters
    ----------
    name : str
        Human-readable surface name (for example ``"surface_topo"`` or
        ``"substratum"``).
    values : Any
        2D array-like values of the surface.
    support : RasterSupport | None
        Optional spatial support describing where this 2D array is located in
        space. The values remain usable without it, but any georeferenced use
        case should attach one.
    """

    name: str
    values: Any
    support: RasterSupport | None = None

    @classmethod
    def from_geographic_dem(
        cls,
        dem_values: Any,
        *,
        support: RasterSupport | None = None,
        name: str = "surface_topo",
    ) -> "Surface":
        """
        Build one surface from explicit DEM values.

        This constructor does not read from ``Geographic`` directly. The caller
        must provide:
        - the already-extracted DEM values,
        - and, when available, the matching ``RasterSupport``.
        """
        values = np.asarray(dem_values, dtype=float)
        return cls(name=name, values=values, support=support)

    def as_array(self) -> np.ndarray:
        """
        Return the surface values as a float NumPy array.

        This is the canonical internal representation used by all numerical
        operations in this module.
        """
        return np.asarray(self.values, dtype=float)

    def assert_support_matches_values(self) -> None:
        """
        Ensure the internal array shape is consistent with attached support.

        This is intentionally lightweight and only validates local coherence.
        Pairwise domain consistency between two surfaces is handled by
        ``assert_same_geographic_domain``.
        """
        if self.support is None:
            return
        arr = self.as_array()
        if self.support.nrows is None or self.support.ncols is None:
            return
        expected = (int(self.support.nrows), int(self.support.ncols))
        if arr.shape != expected:
            raise ValueError(
                f"Surface '{self.name}' shape {arr.shape} does not match "
                f"support shape {expected}."
            )

    def assert_same_geographic_domain(
        self,
        other: "Surface",
        *,
        atol: float = 1.0e-9,
    ) -> None:
        """
        Validate that two surfaces are defined on the exact same geographic domain.

        The check is delegated to ``RasterSupport.assert_same_geographic_domain``
        and also verifies that each surface values-array is coherent with its own
        support dimensions.
        """
        if not isinstance(other, Surface):
            raise TypeError(f"Expected Surface, got {type(other)!r}.")
        if self.support is None or other.support is None:
            raise ValueError("Both surfaces must carry a RasterSupport to compare domains.")

        self.assert_support_matches_values()
        other.assert_support_matches_values()
        self.support.assert_same_geographic_domain(other.support, atol=atol)

    def resample_to_shape(
        self,
        nrows: int,
        ncols: int,
        *,
        resampling: str = "bilinear",
        nodata: float | None = None,
        name: str | None = None,
    ) -> "Surface":
        """
        Return one new surface re-discretized to ``(nrows, ncols)``.

        Geographic extent and CRS are preserved; only raster resolution changes.
        """
        if self.support is None:
            raise ValueError(
                f"Surface '{self.name}' has no RasterSupport and cannot be resampled."
            )
        self.support.assert_complete_domain()
        self.assert_support_matches_values()

        nrows_int = int(nrows)
        ncols_int = int(ncols)
        if nrows_int < 1 or ncols_int < 1:
            raise ValueError("nrows and ncols must be >= 1.")

        return self._resample_to_support(
            target_nrows=nrows_int,
            target_ncols=ncols_int,
            resampling=resampling,
            nodata=nodata,
            name=name,
        )

    def shifted_down_by(
        self,
        offset: float,
        *,
        name: str = "substratum",
    ) -> "Surface":
        """
        Return a new surface shifted downward by one constant offset.

        The returned surface:
        - keeps the same raster support as the current one,
        - uses a new 2D array equal to ``self - offset``.

        Example
        -------
        If ``self`` stores the topography and ``offset=50``, the returned
        surface is ``topography - 50`` on every cell.
        """
        bottom = self.as_array() - float(offset)
        return Surface(name=name, values=bottom, support=self.support)

    def flat_like(
        self,
        value: float,
        *,
        name: str = "substratum",
    ) -> "Surface":
        """
        Return a flat surface with one constant value on the same support.

        The returned surface:
        - keeps the same raster support as the current one,
        - is filled with one constant scalar value,
        - is validated to remain strictly below the current surface.

        Example
        -------
        If ``value=-20``, the returned surface is a constant 2D
        array equal to ``-20`` and it must remain strictly below the current
        surface on all finite cells.
        """
        bottom = np.full_like(self.as_array(), float(value))
        surface = Surface(name=name, values=bottom, support=self.support)
        surface.assert_strictly_below(self)
        return surface

    def assert_strictly_below(self, upper_surface: "Surface") -> None:
        """
        Validate that this surface is strictly lower than ``upper_surface``.

        Validation rules
        ----------------
        - both surfaces must have the same 2D shape,
        - only finite overlapping cells are checked,
        - at every checked cell, ``self < upper_surface`` must hold.

        A ``ValueError`` is raised when:
        - shapes are incompatible,
        - there is no finite overlap,
        - or at least one cell violates the strict ordering.
        """
        lower = self.as_array()
        upper = upper_surface.as_array()

        if lower.shape != upper.shape:
            raise ValueError(
                f"Cannot compare surfaces with different shapes: "
                f"{self.name}={lower.shape}, {upper_surface.name}={upper.shape}"
            )

        finite_mask = np.isfinite(lower) & np.isfinite(upper)
        if not np.any(finite_mask):
            raise ValueError(
                f"Cannot compare '{self.name}' and '{upper_surface.name}': "
                "no finite overlapping DEM cells."
            )

        violations = lower[finite_mask] >= upper[finite_mask]
        if np.any(violations):
            n_bad = int(np.count_nonzero(violations))
            total = int(violations.size)
            max_delta = float(np.max(lower[finite_mask] - upper[finite_mask]))
            raise ValueError(
                f"Surface '{self.name}' must be strictly below '{upper_surface.name}' "
                f"on all cells ({n_bad}/{total} violations, max(delta)={max_delta:.6g})."
            )

    def _resample_to_support(
        self,
        *,
        target_nrows: int,
        target_ncols: int,
        resampling: str,
        nodata: float | None,
        name: str | None,
    ) -> "Surface":
        """
        Internal raster resampling helper on the same geographic domain.

        Only raster shape changes. Geographic domain (CRS + extent) remains the
        one carried by ``self.support``.
        """
        from rasterio.enums import Resampling
        from rasterio.transform import from_bounds
        from rasterio.warp import reproject

        if self.support is None:
            raise ValueError(f"Surface '{self.name}' has no RasterSupport.")
        self.support.assert_complete_domain()

        source = np.asarray(self.as_array(), dtype=float)
        src = self.support

        src_transform = from_bounds(
            float(src.xmin),
            float(src.ymin),
            float(src.xmax),
            float(src.ymax),
            int(src.ncols),
            int(src.nrows),
        )
        target_nrows_int = int(target_nrows)
        target_ncols_int = int(target_ncols)
        if target_nrows_int < 1 or target_ncols_int < 1:
            raise ValueError("target_nrows and target_ncols must be >= 1.")

        dst_transform = from_bounds(
            float(src.xmin),
            float(src.ymin),
            float(src.xmax),
            float(src.ymax),
            target_ncols_int,
            target_nrows_int,
        )

        method = str(resampling).strip().lower()
        if method == "bilinear":
            rs = Resampling.bilinear
        elif method == "average":
            rs = Resampling.average
        elif method == "nearest":
            rs = Resampling.nearest
        else:
            raise ValueError(
                f"Unsupported resampling='{resampling}'. Allowed: bilinear, average, nearest."
            )

        nodata_value: float
        if nodata is not None:
            nodata_value = float(nodata)
        elif src.nodata is not None:
            nodata_value = float(src.nodata)
        else:
            nodata_value = -9999.0

        destination = np.full(
            (target_nrows_int, target_ncols_int),
            nodata_value,
            dtype=float,
        )
        reproject(
            source=source,
            destination=destination,
            src_transform=src_transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs=src.crs,
            src_nodata=nodata_value,
            dst_nodata=nodata_value,
            resampling=rs,
        )
        xmin = float(src.xmin)
        xmax = float(src.xmax)
        ymin = float(src.ymin)
        ymax = float(src.ymax)
        out_support = RasterSupport(
            crs=src.crs,
            dx=(xmax - xmin) / target_ncols_int,
            dy=(ymax - ymin) / target_nrows_int,
            xmin=xmin,
            xmax=xmax,
            ymin=ymin,
            ymax=ymax,
            nrows=target_nrows_int,
            ncols=target_ncols_int,
            nodata=nodata_value,
        )
        return Surface(
            name=(self.name if name is None else name),
            values=destination,
            support=out_support,
        )
