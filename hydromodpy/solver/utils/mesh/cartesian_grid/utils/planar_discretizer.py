# -*- coding: utf-8 -*-
"""
Planar discretization and raster regridding utilities for structured grids.

This module transforms source rasters to the target planar grid requested by
``SGridConfig``:
- keep native support (``keep_native``),
- explicit target shape (``resample_to_shape`` with ``ny`` rows and ``nx`` columns).
"""

from __future__ import annotations

from typing import Any

import numpy as np
from rasterio.enums import Resampling
from rasterio.transform import Affine, from_bounds
from rasterio.warp import reproject

from .raster_grid_reader import TopRasterGrid


class PlanarDiscretizer:
    """Discretize topography and aligned rasters onto a target planar grid."""

    def discretize_top(
        self,
        source_top_grid: TopRasterGrid,
        *,
        mode: str,
        nx: int | None,
        ny: int | None,
        nodata: float,
        fallback_crs: str | None = None,
    ) -> TopRasterGrid:
        """Return top raster metadata on the requested planar discretization."""
        if mode == "keep_native":
            return source_top_grid

        if mode != "resample_to_shape":
            raise ValueError(
                "Unsupported plan_discretization_mode "
                f"'{mode}'. Allowed: keep_native, resample_to_shape."
            )

        if nx is None or ny is None:
            raise ValueError(
                "nx and ny are required when plan_discretization_mode='resample_to_shape'"
            )

        target_crs = source_top_grid.crs or fallback_crs
        if target_crs is None:
            raise ValueError(
                "Cannot resample raster: missing CRS. Provide raster CRS or set config.crs."
            )

        dst_shape = (int(ny), int(nx))
        dst_transform = from_bounds(*source_top_grid.bounds, int(nx), int(ny))
        dst_top = self.resample_to_target(
            source=np.asarray(source_top_grid.top, dtype=float),
            src_transform=source_top_grid.transform,
            src_crs=target_crs,
            dst_shape=dst_shape,
            dst_transform=dst_transform,
            dst_crs=target_crs,
            nodata=nodata,
            resampling=self.select_resampling(
                src_shape=(source_top_grid.nrow, source_top_grid.ncol),
                dst_shape=dst_shape,
            ),
        )

        delc = np.array([dst_transform[0]] * int(ny))
        delr = np.array([-dst_transform[4]] * int(nx))
        return TopRasterGrid(
            top=dst_top,
            delc=delc,
            delr=delr,
            xoff=source_top_grid.bounds[0],
            yoff=source_top_grid.bounds[1],
            nrow=int(ny),
            ncol=int(nx),
            transform=dst_transform,
            crs=target_crs,
            bounds=source_top_grid.bounds,
        )

    @staticmethod
    def select_resampling(src_shape: tuple[int, int], dst_shape: tuple[int, int]) -> Resampling:
        """
        Choose resampling rule from source and destination shape.

        - ``bilinear`` for upsampling (or equal resolution),
        - ``average`` for downsampling.
        """
        src_pixels = int(src_shape[0]) * int(src_shape[1])
        dst_pixels = int(dst_shape[0]) * int(dst_shape[1])
        if dst_pixels >= src_pixels:
            return Resampling.bilinear
        return Resampling.average

    @staticmethod
    def resample_to_target(
        *,
        source: np.ndarray,
        src_transform: Affine,
        src_crs: Any,
        dst_shape: tuple[int, int],
        dst_transform: Affine,
        dst_crs: Any,
        nodata: float,
        resampling: Resampling,
    ) -> np.ndarray:
        """Resample one 2D raster to a target grid definition."""
        if src_crs is None or dst_crs is None:
            raise ValueError("Both src_crs and dst_crs are required for resampling.")

        destination = np.full(dst_shape, float(nodata), dtype=float)
        reproject(
            source=np.asarray(source, dtype=float),
            destination=destination,
            src_transform=src_transform,
            src_crs=src_crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            src_nodata=float(nodata),
            dst_nodata=float(nodata),
            resampling=resampling,
        )
        return destination
