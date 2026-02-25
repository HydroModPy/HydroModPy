# -*- coding: utf-8 -*-
"""
Structured grid construction primitives.

Copyright
---------
Copyright (c) 2023 Alexandre Gauvain, Ronan Abherve, Jean-Raynald de Dreuzy
Licensed under EPL-2.0 OR Apache-2.0.

Architecture choices
--------------------
- Validation is intentionally not implemented in this module.
- ``SGridConfig`` (Pydantic, in ``sgrid_config.py``) is the single source of
  truth for configuration rules and cross-field constraints.
- Raster I/O is extracted into ``RasterGridReader`` to isolate ``rasterio``
  and keep this module focused on geometry construction.
- Planar re-discretization (``nx``/``ny``) is delegated to
  ``PlanarDiscretizer`` to keep interpolation policy explicit and testable.
- ``StructuredGridBuilder`` is a pure transformation:
  validated config -> new FloPy ``StructuredGrid``.
- No cache and no hidden mutable state are kept inside the builder.
"""

from __future__ import annotations

import numpy as np
from flopy.discretization import StructuredGrid

try:
    from .planar_discretizer import PlanarDiscretizer
    from .raster_grid_reader import RasterGridReader
    from .raster_grid_reader import TopRasterGrid
    from .sgrid_config import SGridConfig
except ImportError:
    from planar_discretizer import PlanarDiscretizer
    from raster_grid_reader import RasterGridReader
    from raster_grid_reader import TopRasterGrid
    from sgrid_config import SGridConfig


class StructuredGridBuilder:
    """Pure, deterministic builder from validated ``SGridConfig``."""

    def __init__(
        self,
        raster_reader: RasterGridReader | None = None,
        planar_discretizer: PlanarDiscretizer | None = None,
    ):
        self._raster_reader = raster_reader or RasterGridReader()
        self._planar_discretizer = planar_discretizer or PlanarDiscretizer()

    def build(self, config: SGridConfig) -> StructuredGrid:
        """Create and return one new FloPy ``StructuredGrid``."""
        source_top_grid, target_top_grid = self._create_hgrid_structured(config)
        botm, nlay = self._create_vgrid_structured(
            top=target_top_grid.top,
            config=config,
            source_top_grid=source_top_grid,
            target_top_grid=target_top_grid,
        )
        return StructuredGrid(
            delc=target_top_grid.delc,
            delr=target_top_grid.delr,
            top=target_top_grid.top,
            botm=botm,
            xoff=target_top_grid.xoff,
            yoff=target_top_grid.yoff,
            nlay=nlay,
            nrow=target_top_grid.nrow,
            ncol=target_top_grid.ncol,
            crs=config.crs,
            lenuni=config.lenuni,
        )

    def _create_hgrid_structured(
        self, config: SGridConfig
    ) -> tuple[TopRasterGrid, TopRasterGrid]:
        source_top_grid = self._raster_reader.read_top_grid(str(config.top_path))
        target_top_grid = self._planar_discretizer.discretize_top(
            source_top_grid=source_top_grid,
            mode=config.plan_discretization_mode,
            nx=config.nx,
            ny=config.ny,
            nodata=config.nodata,
            fallback_crs=config.crs,
        )
        top = np.asarray(target_top_grid.top, dtype=float)
        top[top <= config.nodata] = config.nodata
        target_top_grid = TopRasterGrid(
            top,
            target_top_grid.delc,
            target_top_grid.delr,
            target_top_grid.xoff,
            target_top_grid.yoff,
            target_top_grid.nrow,
            target_top_grid.ncol,
            target_top_grid.transform,
            target_top_grid.crs,
            target_top_grid.bounds,
        )
        return source_top_grid, target_top_grid

    def _create_vgrid_structured(
        self,
        top,
        config: SGridConfig,
        source_top_grid: TopRasterGrid,
        target_top_grid: TopRasterGrid,
    ):
        bot = self._compute_bottom_surface(
            top=top,
            nodata=config.nodata,
            genmtd_bot=config.genmtd_bot,
            bot_path=config.bot_path,
            bot_raster=config.bot_raster,
            thick=config.thick,
            zbot=config.zbot,
            plan_mode=config.plan_discretization_mode,
            source_top_grid=source_top_grid,
            target_top_grid=target_top_grid,
            fallback_crs=config.crs,
            raster_reader=self._raster_reader,
            planar_discretizer=self._planar_discretizer,
        )
        allp, nlay = self._compute_layer_proportions(
            genmtd_lay=config.genmtd_lay,
            nlay=config.nlay,
            lay_decay=config.lay_decay,
            lay_proportions=config.lay_proportions,
        )
        botm = self._build_botm(top=top, bot=bot, nodata=config.nodata, allp=allp)
        return botm, nlay

    @staticmethod
    def _compute_bottom_surface(
        top,
        nodata,
        genmtd_bot,
        bot_path=None,
        bot_raster=None,
        thick=None,
        zbot=None,
        plan_mode="raster_native",
        source_top_grid: TopRasterGrid | None = None,
        target_top_grid: TopRasterGrid | None = None,
        fallback_crs: str | None = None,
        raster_reader: RasterGridReader | None = None,
        planar_discretizer: PlanarDiscretizer | None = None,
    ):
        """Compute bottom surface according to selected generation method."""
        if genmtd_bot == "filepath":
            reader = raster_reader or RasterGridReader()
            if plan_mode == "shape":
                if target_top_grid is None:
                    raise ValueError("target_top_grid is required in shape discretization mode")
                bot, bot_transform, bot_crs, _ = reader.read_band1_with_metadata(str(bot_path))
                target_shape = (target_top_grid.nrow, target_top_grid.ncol)
                discretizer = planar_discretizer or PlanarDiscretizer()
                src_crs = bot_crs or (source_top_grid.crs if source_top_grid else None) or fallback_crs
                dst_crs = target_top_grid.crs or fallback_crs
                bot = discretizer.resample_to_target(
                    source=np.asarray(bot, dtype=float),
                    src_transform=bot_transform,
                    src_crs=src_crs,
                    dst_shape=target_shape,
                    dst_transform=target_top_grid.transform,
                    dst_crs=dst_crs,
                    nodata=float(nodata),
                    resampling=discretizer.select_resampling(
                        src_shape=np.asarray(bot).shape,
                        dst_shape=target_shape,
                    ),
                )
            else:
                bot = reader.read_band1(str(bot_path))
        elif genmtd_bot == "raster":
            bot = np.asarray(bot_raster, dtype=float)
            if plan_mode == "shape" and target_top_grid is not None:
                target_shape = (target_top_grid.nrow, target_top_grid.ncol)
                if bot.shape != target_shape:
                    if source_top_grid is None:
                        raise ValueError(
                            "source_top_grid is required to resample bot_raster in shape mode"
                        )
                    source_shape = (source_top_grid.nrow, source_top_grid.ncol)
                    if bot.shape != source_shape:
                        raise ValueError(
                            "bot_raster shape must match source top shape or target shape in shape mode."
                        )
                    src_crs = source_top_grid.crs or fallback_crs
                    dst_crs = target_top_grid.crs or fallback_crs
                    discretizer = planar_discretizer or PlanarDiscretizer()
                    bot = discretizer.resample_to_target(
                        source=bot,
                        src_transform=source_top_grid.transform,
                        src_crs=src_crs,
                        dst_shape=target_shape,
                        dst_transform=target_top_grid.transform,
                        dst_crs=dst_crs,
                        nodata=float(nodata),
                        resampling=discretizer.select_resampling(
                            src_shape=source_shape,
                            dst_shape=target_shape,
                        ),
                    )
        elif genmtd_bot == "constant_thickness":
            bot = np.asarray(top, dtype=float) - float(thick)
        elif genmtd_bot == "constant_altitude":
            bot = np.zeros_like(top, dtype=float) + float(zbot)
        else:
            # Should be unreachable: method is validated in SGridConfig.
            raise ValueError(
                f"Unsupported genmtd_bot '{genmtd_bot}'. "
                "Allowed: filepath, raster, constant_thickness, constant_altitude."
            )

        bot = np.asarray(bot, dtype=float)
        if bot.shape != np.asarray(top).shape:
            raise ValueError(
                f"Bottom surface shape mismatch: bot{bot.shape} != top{np.asarray(top).shape}."
            )
        bot[np.asarray(top) <= nodata] = nodata
        return bot

    @staticmethod
    def _compute_layer_proportions(genmtd_lay, nlay=None, lay_decay=None, lay_proportions=None):
        """Compute cumulative layer proportions and number of layers."""
        if genmtd_lay == "list":
            arr = np.asarray(lay_proportions, dtype=float)
            return np.cumsum(arr), int(arr.size)
        if genmtd_lay == "constant":
            nlay_int = int(nlay)
            return np.arange(1, nlay_int + 1, dtype=float) / nlay_int, nlay_int
        if genmtd_lay == "decay":
            nlay_int = int(nlay)
            decay = float(lay_decay)
            idx = np.arange(1, nlay_int + 1, dtype=float)
            allp = (1 - decay**idx) / (1 - decay**nlay_int)
            return allp, nlay_int
        # Should be unreachable: method is validated in SGridConfig.
        raise ValueError(f"Unsupported genmtd_lay '{genmtd_lay}'. Allowed: list, constant, decay.")

    @staticmethod
    def _build_botm(top, bot, nodata, allp):
        """Build layer bottom elevations from top, bottom and cumulative proportions."""
        top = np.asarray(top, dtype=float)
        bot = np.asarray(bot, dtype=float)
        allp = np.asarray(allp, dtype=float)
        if allp.ndim != 1 or allp.size == 0:
            raise ValueError("allp must be a non-empty 1D array.")

        botm = top[None, :, :] - ((top - bot)[None, :, :] * allp[:, None, None])
        botm[:, bot <= nodata] = nodata
        return botm


# TODO: DEM crs and length unit (as imported from .tif file) should be checked
# and reprojected if necessary.
