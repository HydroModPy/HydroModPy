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

from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.raster_support import RasterSupport

logger = get_logger(__name__)


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
    ) -> Surface:
        """
        Build one surface from explicit DEM values.

        This constructor does not read from ``CatchmentDelineation`` directly. The caller
        must provide:
        - the already-extracted DEM values,
        - and, when available, the matching ``RasterSupport``.
        """
        values = np.asarray(dem_values, dtype=float)
        return cls(name=name, values=values, support=support)

    @classmethod
    def from_raster(
        cls,
        path: str | Path,
        *,
        name: str,
        default_crs: str | None = None,
    ) -> Surface:
        """Read band 1 of a raster file into a surface on the file's own grid.

        The bounds come from the affine transform, and the nodata sentinel of
        the file is kept in the values and on the support. *default_crs* is
        used only when the file declares no CRS.
        """
        import rasterio

        raster_path = Path(path)
        if not raster_path.exists():
            raise FileNotFoundError(f"Raster not found: {raster_path}")

        with rasterio.open(str(raster_path)) as src:
            values = np.asarray(src.read(1), dtype=float)
            transform = src.transform
            nodata = src.nodata
            declared_crs = src.crs.to_string() if src.crs is not None else None
        crs = declared_crs if declared_crs is not None else default_crs
        if declared_crs is None and default_crs is not None:
            logger.warning("Raster %s declares no CRS; it is read as %s.", raster_path, default_crs)

        resolution_x = float(transform.a)
        resolution_y = float(transform.e)
        xmin = float(transform.c)
        ymax = float(transform.f)
        xmax = xmin + values.shape[1] * resolution_x
        ymin = ymax + values.shape[0] * resolution_y
        support = RasterSupport.from_georeferencing(
            {
                "crs": crs,
                "dx": abs(resolution_x),
                "dy": abs(resolution_y),
                "xmin": xmin,
                "xmax": xmax,
                "ymin": ymin,
                "ymax": ymax,
            },
            shape=values.shape,
            nodata=nodata,
        )
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
                f"Surface '{self.name}' shape {arr.shape} does not match support shape {expected}."
            )

    def assert_same_geographic_domain(
        self,
        other: Surface,
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
    ) -> Surface:
        """
        Return one new surface re-discretized to ``(nrows, ncols)``.

        Geographic extent and CRS are preserved; only raster resolution changes.
        """
        if self.support is None:
            raise ValueError(f"Surface '{self.name}' has no RasterSupport and cannot be resampled.")
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
    ) -> Surface:
        """
        Return a new surface shifted downward by one constant offset.

        The returned surface:
        - keeps the same raster support as the current one,
        - uses a new 2D array equal to ``self - offset``,
        - leaves a NODATA cell AT the sentinel instead of shifting it.

        The sentinel must not move. The support is shared by reference, so it keeps
        advertising the same ``nodata`` value, and every consumer recognises a
        no-data cell by exact equality with it (``surface_sampling``, the
        discretization guard, the zonal statistics). Shifting ``-9999`` to
        ``-9999 - offset`` silently turns the sentinel into an ordinary elevation:
        it is then interpolated as if it were terrain, and a mesh cell whose stencil
        straddles the mask edge inherits a bottom dragged toward it. Such a cell has
        no idomain signature either, because the top of that same cell is clean: it
        stays active and carries a column kilometres thick, with the transmissivity
        and the storage that go with it.

        Example
        -------
        If ``self`` stores the topography and ``offset=50``, the returned
        surface is ``topography - 50`` on every cell carrying data.
        """
        top = self.as_array()
        bottom = top - float(offset)
        nodata = getattr(self.support, "nodata", None)
        if nodata is not None:
            bottom = np.where(top == float(nodata), float(nodata), bottom)
        return Surface(name=name, values=bottom, support=self.support)

    def flat_like(
        self,
        value: float,
        *,
        name: str = "substratum",
        min_gap: float = 1.0,
    ) -> Surface:
        """
        Return a flat (constant-elevation) substratum below this surface.

        The returned surface is ``value`` on every cell whose top sits strictly
        above ``value + min_gap``. Where the top drops to or below that level the
        cell has no aquifer (basement outcrop, or a NODATA sentinel left by a
        watershed-masked / out-of-DEM cell): the bottom is clamped to
        ``top - min_gap`` so the column stays a thin degenerate cell that the
        mesh masks out, instead of inverting (bottom above top). This mirrors
        ``shifted_down_by`` on those cells, so a flat substratum behaves like a
        constant thickness there and never trips the strict-ordering guard.

        Example
        -------
        If ``value=20`` and the terrain is 56..83 m, every cell gets a flat
        bottom at 20 m. A NODATA cell (top ``-9999``) is clamped to ``-10000``.
        """
        top = self.as_array()
        flat = float(value)
        gap = float(min_gap)
        finite = np.isfinite(top)
        if np.any(finite) and not np.any(top[finite] > flat + gap):
            raise ValueError(
                f"Flat substratum {flat} m sits at or above the top on every finite "
                "cell; no aquifer would remain. Lower substratum_elevation."
            )
        bottom = np.where(top > flat + gap, flat, top - gap)
        return Surface(name=name, values=bottom, support=self.support)

    def assert_strictly_below(self, upper_surface: Surface) -> None:
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
    ) -> Surface:
        """
        Internal raster resampling helper on the same geographic domain.

        Only raster shape changes. Geographic domain (CRS + extent) remains the
        one carried by ``self.support``.
        """
        if self.support is None:
            raise ValueError(f"Surface '{self.name}' has no RasterSupport.")
        self.support.assert_complete_domain()

        src = self.support
        target_nrows_int = int(target_nrows)
        target_ncols_int = int(target_ncols)
        if target_nrows_int < 1 or target_ncols_int < 1:
            raise ValueError("target_nrows and target_ncols must be >= 1.")

        nodata_value: float
        if nodata is not None:
            nodata_value = float(nodata)
        elif src.nodata is not None:
            nodata_value = float(src.nodata)
        else:
            nodata_value = -9999.0

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
        destination = _warp(
            np.asarray(self.as_array(), dtype=float),
            src=src,
            dst=out_support,
            resampling=resampling,
            nodata=nodata_value,
        )
        return Surface(
            name=(self.name if name is None else name),
            values=destination,
            support=out_support,
        )

    def reprojected_onto(
        self,
        support: RasterSupport,
        *,
        resampling: str | None = None,
        name: str | None = None,
    ) -> Surface:
        """Return this surface on *support*, whatever its CRS, extent and shape.

        The values of the returned surface are NaN on every cell this surface
        carries no data for: outside its extent, or on its nodata sentinel.
        The returned surface takes *support* by reference, so a caller aligns
        it cell by cell with the surface *support* came from.

        A surface already on the grid of *support* is copied, not resampled.
        Otherwise *resampling* defaults to ``average`` when this surface is
        finer than the target in the same CRS, and to ``bilinear`` otherwise.
        """
        if self.support is None:
            raise ValueError(
                f"Surface '{self.name}' has no RasterSupport and cannot be reprojected."
            )
        self.support.assert_complete_domain()
        support.assert_complete_domain()
        self.assert_support_matches_values()

        source = self.as_array().copy()
        if self.support.nodata is not None:
            source[source == float(self.support.nodata)] = np.nan
        out_name = self.name if name is None else name
        if _same_grid(self.support, support):
            return Surface(name=out_name, values=source, support=support)

        method = resampling
        if method is None:
            method = "average" if _is_finer(self.support, support) else "bilinear"
        destination = _warp(source, src=self.support, dst=support, resampling=method, nodata=np.nan)
        return Surface(name=out_name, values=destination, support=support)


_RESAMPLING_NAMES = ("bilinear", "average", "nearest")


def _warp(
    source: np.ndarray,
    *,
    src: RasterSupport,
    dst: RasterSupport,
    resampling: str,
    nodata: float,
) -> np.ndarray:
    """Resample *source* from the grid of *src* onto the grid of *dst*.

    Both grids are north-up and described by their bounds and shape. Cells of
    *dst* that no source cell reaches keep *nodata*.
    """
    from rasterio.enums import Resampling
    from rasterio.transform import from_bounds
    from rasterio.warp import reproject

    method = str(resampling).strip().lower()
    if method not in _RESAMPLING_NAMES:
        raise ValueError(
            f"Unsupported resampling='{resampling}'. Allowed: {', '.join(_RESAMPLING_NAMES)}."
        )

    def _transform(support: RasterSupport) -> Any:
        return from_bounds(
            float(support.xmin),
            float(support.ymin),
            float(support.xmax),
            float(support.ymax),
            int(support.ncols),
            int(support.nrows),
        )

    destination = np.full((int(dst.nrows), int(dst.ncols)), nodata, dtype=float)
    reproject(
        source=source,
        destination=destination,
        src_transform=_transform(src),
        src_crs=src.crs,
        dst_transform=_transform(dst),
        dst_crs=dst.crs,
        src_nodata=nodata,
        dst_nodata=nodata,
        resampling=getattr(Resampling, method),
    )
    return destination


def _same_grid(a: RasterSupport, b: RasterSupport, *, atol: float = 1.0e-9) -> bool:
    """Return True when two supports place the same cells at the same place."""
    if (int(a.nrows), int(a.ncols)) != (int(b.nrows), int(b.ncols)):
        return False
    if str(a.crs).strip().lower() != str(b.crs).strip().lower():
        return False
    return all(
        isclose(float(getattr(a, key)), float(getattr(b, key)), rel_tol=0.0, abs_tol=atol)
        for key in ("xmin", "xmax", "ymin", "ymax")
    )


def _is_finer(a: RasterSupport, b: RasterSupport) -> bool:
    """Return True when the cells of *a* are smaller than those of *b* in one CRS.

    Across two CRSs the cell sizes are not comparable, and the answer is False.
    """
    if str(a.crs).strip().lower() != str(b.crs).strip().lower():
        return False
    area_a = (float(a.xmax) - float(a.xmin)) * (float(a.ymax) - float(a.ymin))
    area_b = (float(b.xmax) - float(b.xmin)) * (float(b.ymax) - float(b.ymin))
    cell_a = area_a / (int(a.nrows) * int(a.ncols))
    cell_b = area_b / (int(b.nrows) * int(b.ncols))
    return cell_a < cell_b
