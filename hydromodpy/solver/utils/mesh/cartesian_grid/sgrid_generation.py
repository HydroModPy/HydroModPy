# -*- coding: utf-8 -*-
"""
Surface-driven structured-grid generation for FloPy.

Overview
--------
This module builds a FloPy ``StructuredGrid`` from two absolute-elevation
surfaces:
- one topographic surface (`top_surface`),
- one bottom surface (`bottom_surface`).

Design responsibilities
-----------------------
- Horizontal discretization (XY) is handled outside this builder, typically in
  `Surface` (`resample_to_shape(...)`).
- This builder handles only:
  - geometric consistency checks for vertical construction,
  - vertical layering (`constant`, `decay`, `list`),
  - assembly of FloPy `StructuredGrid`.

Important convention
--------------------
`top_surface` and `bottom_surface` are absolute altitudes in the same datum.
No additive combination is done between the two surfaces.
"""

from __future__ import annotations

from collections.abc import Mapping
import warnings

import numpy as np
from flopy.discretization import StructuredGrid

from hydromodpy.domain.raster_support import RasterSupport
from hydromodpy.domain.surface import Surface

try:
    from .utils.raster_grid_reader import RasterGridReader
    from .sgrid_config import SGridConfig
    from .sgrid_config import VerticalGridConfig
except ImportError:
    from utils.raster_grid_reader import RasterGridReader
    from sgrid_config import SGridConfig
    from sgrid_config import VerticalGridConfig


def _support_from_bounds_shape(
    *,
    bounds: tuple[float, float, float, float],
    shape: tuple[int, int],
    crs: str | None,
    nodata: float,
) -> RasterSupport:
    """
    Build one RasterSupport from raster bounds and shape metadata.
    """
    xmin, ymin, xmax, ymax = (float(v) for v in bounds)
    nrows, ncols = int(shape[0]), int(shape[1])
    return RasterSupport(
        crs=crs,
        dx=(xmax - xmin) / ncols,
        dy=(ymax - ymin) / nrows,
        xmin=xmin,
        xmax=xmax,
        ymin=ymin,
        ymax=ymax,
        nrows=nrows,
        ncols=ncols,
        nodata=float(nodata),
    )


def _select_resampling_mode(
    src_shape: tuple[int, int],
    dst_shape: tuple[int, int],
) -> str:
    """
    Choose a simple resampling mode from source and target shapes.
    """
    src_pixels = int(src_shape[0]) * int(src_shape[1])
    dst_pixels = int(dst_shape[0]) * int(dst_shape[1])
    return "bilinear" if dst_pixels >= src_pixels else "average"


class StructuredGridBuilder:
    """
    Build FloPy `StructuredGrid` objects from explicit top/bottom surfaces.
    """

    def __init__(self):
        # No hidden state: deterministic transformations only.
        pass

    def build_from_surfaces(
        self,
        top_surface: Surface,
        bottom_surface: Surface,
        vertical_config: VerticalGridConfig | Mapping[str, object] | None = None,
    ) -> StructuredGrid:
        """
        Build one structured grid from two absolute-elevation surfaces.

        The method intentionally separates three steps:
        1. Validate horizontal/geometric compatibility of inputs.
        2. Compute vertical layer proportions.
        3. Build `botm` and return a FloPy `StructuredGrid`.
        """
        cfg = _coerce_vertical_config(vertical_config)

        # 1) Horizontal compatibility checks.
        #    "Same geographic domain" means same CRS + same spatial extent.
        top_surface.assert_same_geographic_domain(bottom_surface)

        support = top_surface.support
        if support is None:
            raise ValueError("Top surface must carry a RasterSupport.")
        support.assert_complete_domain()

        top = np.asarray(top_surface.as_array(), dtype=float)
        bot = np.asarray(bottom_surface.as_array(), dtype=float)
        if top.shape != bot.shape:
            raise ValueError(
                "top_surface and bottom_surface must have the same discretization "
                f"before vertical grid construction: top{top.shape} != bottom{bot.shape}. "
                "Use Surface.resample_to_shape(...) beforehand."
            )

        nodata = float(cfg.nodata)

        # Mask invalid cells consistently in both surfaces.
        invalid = (
            ~np.isfinite(top)
            | ~np.isfinite(bot)
            | (top <= nodata)
            | (bot <= nodata)
        )
        top = np.array(top, dtype=float, copy=True)
        bot = np.array(bot, dtype=float, copy=True)
        top[invalid] = nodata
        bot[invalid] = nodata

        self._assert_bottom_below_top(top=top, bot=bot, nodata=nodata)

        # 2) Vertical proportions from config.
        allp, nlay = self._compute_layer_proportions(
            genmtd_lay=cfg.genmtd_lay,
            nlay=cfg.nlay,
            lay_decay=cfg.lay_decay,
            lay_proportions=cfg.lay_proportions,
        )

        # 3) Build layer bottoms and FloPy grid.
        botm = self._build_botm(top=top, bot=bot, nodata=nodata, allp=allp)

        nrow = int(support.nrows)
        ncol = int(support.ncols)
        xmin = float(support.xmin)
        ymin = float(support.ymin)
        xmax = float(support.xmax)
        ymax = float(support.ymax)

        dx = float(support.dx) if support.dx is not None else (xmax - xmin) / ncol
        dy = float(support.dy) if support.dy is not None else (ymax - ymin) / nrow
        if dx <= 0 or dy <= 0:
            raise ValueError(f"Invalid support cell sizes: dx={dx}, dy={dy}.")

        delr = np.full(ncol, dx, dtype=float)
        delc = np.full(nrow, dy, dtype=float)

        return StructuredGrid(
            delc=delc,
            delr=delr,
            top=top,
            botm=botm,
            xoff=xmin,
            yoff=ymin,
            nlay=nlay,
            nrow=nrow,
            ncol=ncol,
            crs=support.crs,
            lenuni=cfg.lenuni,
        )

    def build(self, config: SGridConfig) -> StructuredGrid:
        """
        Legacy compatibility wrapper from `SGridConfig`.

        New call sites should use `build_from_surfaces(...)`.
        """
        warnings.warn(
            "StructuredGridBuilder.build(SGridConfig) is deprecated. "
            "Use build_from_surfaces(top_surface, bottom_surface, vertical_config).",
            DeprecationWarning,
            stacklevel=2,
        )

        top_surface, bottom_surface = self._legacy_surfaces_from_config(config)
        vertical_cfg = VerticalGridConfig(
            genmtd_lay=config.genmtd_lay,
            nlay=(None if config.genmtd_lay == "list" else config.nlay),
            lay_decay=config.lay_decay,
            lay_proportions=(
                tuple(float(v) for v in config.lay_proportions)
                if config.lay_proportions is not None
                else None
            ),
            nodata=float(config.nodata),
            lenuni=str(config.lenuni),
        )
        return self.build_from_surfaces(
            top_surface=top_surface,
            bottom_surface=bottom_surface,
            vertical_config=vertical_cfg,
        )

    def _legacy_surfaces_from_config(self, config: SGridConfig) -> tuple[Surface, Surface]:
        """
        Legacy bridge: convert one `SGridConfig` payload into two `Surface` objects.

        This keeps backward compatibility while routing the final construction
        through `build_from_surfaces(...)`.
        """
        reader = RasterGridReader()
        top_grid = reader.read_top_grid(str(config.top_path))
        top_crs = str(top_grid.crs) if top_grid.crs is not None else config.crs
        source_top_support = _support_from_bounds_shape(
            bounds=top_grid.bounds,
            shape=np.asarray(top_grid.top, dtype=float).shape,
            crs=top_crs,
            nodata=float(config.nodata),
        )
        source_top_surface = Surface(
            name="top_surface",
            values=np.asarray(top_grid.top, dtype=float),
            support=source_top_support,
        )

        if config.plan_discretization_mode == "shape":
            target_nrows = int(config.ny)
            target_ncols = int(config.nx)
            top_surface = source_top_surface.resample_to_shape(
                target_nrows,
                target_ncols,
                nodata=float(config.nodata),
                resampling=_select_resampling_mode(
                    src_shape=np.asarray(source_top_surface.as_array(), dtype=float).shape,
                    dst_shape=(target_nrows, target_ncols),
                ),
            )
        else:
            top_surface = source_top_surface

        top_values = np.asarray(top_surface.as_array(), dtype=float)

        if config.genmtd_bot == "constant_thickness":
            bottom_values = top_values - float(config.thick)
            bottom_surface = Surface(
                name="bottom_surface",
                values=bottom_values,
                support=top_surface.support,
            )
        elif config.genmtd_bot == "constant_altitude":
            bottom_values = np.full_like(top_values, float(config.zbot), dtype=float)
            bottom_surface = Surface(
                name="bottom_surface",
                values=bottom_values,
                support=top_surface.support,
            )
        elif config.genmtd_bot == "filepath":
            bot_values, _, bot_crs, bot_bounds = reader.read_band1_with_metadata(str(config.bot_path))
            bot_surface = Surface(
                name="bottom_surface",
                values=np.asarray(bot_values, dtype=float),
                support=_support_from_bounds_shape(
                    bounds=bot_bounds,
                    shape=np.asarray(bot_values, dtype=float).shape,
                    crs=(str(bot_crs) if bot_crs is not None else top_crs),
                    nodata=float(config.nodata),
                ),
            )
            if config.plan_discretization_mode == "shape":
                target_shape = np.asarray(top_surface.as_array(), dtype=float).shape
                bot_surface = bot_surface.resample_to_shape(
                    int(target_shape[0]),
                    int(target_shape[1]),
                    nodata=float(config.nodata),
                    resampling=_select_resampling_mode(
                        src_shape=np.asarray(bot_surface.as_array(), dtype=float).shape,
                        dst_shape=(int(target_shape[0]), int(target_shape[1])),
                    ),
                )
            bottom_surface = bot_surface
        else:
            # genmtd_bot == "raster" (validated by SGridConfig)
            raw_bot = np.asarray(config.bot_raster, dtype=float)
            source_shape = np.asarray(source_top_surface.as_array(), dtype=float).shape
            target_shape = np.asarray(top_surface.as_array(), dtype=float).shape

            if raw_bot.shape == target_shape:
                bottom_surface = Surface(
                    name="bottom_surface",
                    values=raw_bot,
                    support=top_surface.support,
                )
            elif raw_bot.shape == source_shape:
                bot_surface = Surface(
                    name="bottom_surface",
                    values=raw_bot,
                    support=source_top_surface.support,
                )
                if config.plan_discretization_mode == "shape":
                    bot_surface = bot_surface.resample_to_shape(
                        int(target_shape[0]),
                        int(target_shape[1]),
                        nodata=float(config.nodata),
                        resampling=_select_resampling_mode(
                            src_shape=source_shape,
                            dst_shape=target_shape,
                        ),
                    )
                bottom_surface = bot_surface
            else:
                raise ValueError(
                    "bot_raster shape must match top source shape or top target shape. "
                    f"Got bot{raw_bot.shape}, source_top{source_shape}, target_top{target_shape}."
                )

        bot_arr = np.asarray(bottom_surface.as_array(), dtype=float)
        bot_arr[top_values <= float(config.nodata)] = float(config.nodata)
        bottom_surface = Surface(
            name=bottom_surface.name,
            values=bot_arr,
            support=bottom_surface.support,
        )
        return top_surface, bottom_surface

    @staticmethod
    def _compute_bottom_surface(
        *,
        top,
        nodata,
        genmtd_bot,
        bot_path=None,
        bot_raster=None,
        thick=None,
        zbot=None,
        raster_reader=None,
    ):
        """
        Legacy helper kept for backward compatibility in unit tests.

        This function computes one absolute-elevation bottom surface from a top
        array and one bottom-generation mode. New code paths should instead
        prepare a dedicated ``bottom_surface`` and call ``build_from_surfaces``.
        """
        top_arr = np.asarray(top, dtype=float)
        nodata_value = float(nodata)

        if genmtd_bot == "filepath":
            if raster_reader is None:
                raster_reader = RasterGridReader()
            bottom, _, _, _ = raster_reader.read_band1_with_metadata(str(bot_path))
            bottom = np.asarray(bottom, dtype=float)
            if bottom.shape != top_arr.shape:
                raise ValueError(
                    f"shape mismatch between top {top_arr.shape} and bottom {bottom.shape}"
                )
            bottom[top_arr <= nodata_value] = nodata_value
            return bottom

        if genmtd_bot == "raster":
            bottom = np.asarray(bot_raster, dtype=float)
            if bottom.shape != top_arr.shape:
                raise ValueError(
                    f"shape mismatch between top {top_arr.shape} and bottom {bottom.shape}"
                )
            bottom = np.array(bottom, copy=True, dtype=float)
            bottom[top_arr <= nodata_value] = nodata_value
            return bottom

        if genmtd_bot == "constant_thickness":
            bottom = top_arr - float(thick)
            bottom[top_arr <= nodata_value] = nodata_value
            return bottom

        if genmtd_bot == "constant_altitude":
            bottom = np.full_like(top_arr, float(zbot), dtype=float)
            bottom[top_arr <= nodata_value] = nodata_value
            return bottom

        raise ValueError(
            "Unsupported genmtd_bot "
            f"'{genmtd_bot}'. Allowed: filepath, raster, constant_thickness, constant_altitude."
        )

    @staticmethod
    def _assert_bottom_below_top(top, bot, nodata):
        """
        Ensure vertical order is physically consistent: bottom < top on valid cells.
        """
        top = np.asarray(top, dtype=float)
        bot = np.asarray(bot, dtype=float)
        nodata_value = float(nodata)

        valid = (
            np.isfinite(top)
            & np.isfinite(bot)
            & (top > nodata_value)
            & (bot > nodata_value)
        )
        if not np.any(valid):
            raise ValueError("No finite overlapping valid cells found between top and bottom surfaces.")

        violations = bot[valid] >= top[valid]
        if np.any(violations):
            n_bad = int(np.count_nonzero(violations))
            total = int(violations.size)
            max_delta = float(np.max(bot[valid] - top[valid]))
            raise ValueError(
                "Bottom surface must be strictly below top surface on valid cells "
                f"({n_bad}/{total} violations, max(bot-top)={max_delta:.6g})."
            )

    @staticmethod
    def _compute_layer_proportions(genmtd_lay, nlay=None, lay_decay=None, lay_proportions=None):
        """
        Compute cumulative vertical proportions (`allp`) and layer count (`nlay`).

        Returned convention
        -------------------
        - `allp` is a 1D cumulative array in ]0, 1], one value per model layer.
        - `allp[k]` is the fraction of total vertical distance `(top - bottom)`
          reached at the bottom of layer `k`.
        - The last value is always ~1.0, so the last computed layer bottom
          matches the provided bottom surface.

        Examples
        --------
        - `constant, nlay=4` -> `[0.25, 0.50, 0.75, 1.00]`
        - `list, [0.1, 0.2, 0.3, 0.4]` -> cumulative `[0.1, 0.3, 0.6, 1.0]`
        - `decay` -> increasing thickness with depth (for `lay_decay > 1`)
        """
        if genmtd_lay == "list":
            # User provides explicit per-layer fractions that sum to 1.
            # We convert them to cumulative proportions expected by `_build_botm`.
            arr = np.asarray(lay_proportions, dtype=float)
            return np.cumsum(arr), int(arr.size)

        if genmtd_lay == "constant":
            # Uniform layer thickness: each layer spans 1/nlay of total thickness.
            nlay_int = int(nlay)
            return np.arange(1, nlay_int + 1, dtype=float) / nlay_int, nlay_int

        if genmtd_lay == "decay":
            # Geometric-like cumulative profile:
            # upper layers thinner, deeper layers thicker when `decay > 1`.
            nlay_int = int(nlay)
            decay = float(lay_decay)
            idx = np.arange(1, nlay_int + 1, dtype=float)
            allp = (1 - decay**idx) / (1 - decay**nlay_int)
            return allp, nlay_int

        raise ValueError(f"Unsupported genmtd_lay '{genmtd_lay}'. Allowed: list, constant, decay.")

    @staticmethod
    def _build_botm(top, bot, nodata, allp):
        """
        Build layer-bottom array `botm` from top and bottom absolute surfaces.

        Pedagogical formulation
        -----------------------
        For each layer `k`, the cumulative proportion `allp[k]` is in [0, 1]:
        - 0 means at top elevation,
        - 1 means at bottom elevation.

        The interpolation formula is:
            z_k = top - (top - bot) * allp[k]

        Then nodata is propagated so invalid cells stay invalid in all layers.
        """
        top = np.asarray(top, dtype=float)
        bot = np.asarray(bot, dtype=float)
        allp = np.asarray(allp, dtype=float)
        if allp.ndim != 1 or allp.size == 0:
            raise ValueError("allp must be a non-empty 1D array.")

        # Broadcast `top` and `bot` over all layers and apply cumulative
        # interpolation fractions (`allp`) to obtain each layer bottom surface.
        botm = top[None, :, :] - ((top - bot)[None, :, :] * allp[:, None, None])

        # Keep nodata mask consistent for all layers.
        botm[:, bot <= nodata] = nodata
        return botm


def _coerce_vertical_config(
    vertical_config: VerticalGridConfig | Mapping[str, object] | None,
) -> VerticalGridConfig:
    if vertical_config is None:
        return VerticalGridConfig()
    if isinstance(vertical_config, VerticalGridConfig):
        return vertical_config
    if isinstance(vertical_config, Mapping):
        return VerticalGridConfig.from_mapping(vertical_config)
    raise TypeError(
        "vertical_config must be None, VerticalGridConfig, or a mapping of values."
    )
