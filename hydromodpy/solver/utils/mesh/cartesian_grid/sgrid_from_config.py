"""Build one structured grid from validated ``SGridConfig`` payloads.

This module is the config-to-surface bridge:
- ``SGridConfig`` validates user payloads,
- this adapter resolves top/bottom surfaces from that config,
- ``StructuredGridBuilder.build_from_surfaces(...)`` performs final grid build.

The split keeps geometry construction explicit while preserving a practical
entry point for TOML/mapping-based workflows.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from hydromodpy.domain.raster_support import RasterSupport
from hydromodpy.domain.surface import Surface

from .sgrid_config import SGridConfig, VerticalGridConfig
from .sgrid_generation import StructuredGridBuilder
from .utils.planar_discretizer import PlanarDiscretizer
from .utils.raster_grid_reader import RasterGridReader, TopRasterGrid


def _surface_from_top_grid(
    top_grid: TopRasterGrid,
    *,
    nodata: float,
    name: str,
) -> Surface:
    values = np.asarray(top_grid.top, dtype=float)
    nrows, ncols = values.shape
    xmin, ymin, xmax, ymax = (float(v) for v in top_grid.bounds)
    dx = (xmax - xmin) / float(ncols)
    dy = (ymax - ymin) / float(nrows)
    support = RasterSupport(
        crs=(None if top_grid.crs is None else str(top_grid.crs)),
        dx=dx,
        dy=dy,
        xmin=xmin,
        xmax=xmax,
        ymin=ymin,
        ymax=ymax,
        nrows=nrows,
        ncols=ncols,
        nodata=float(nodata),
    )
    return Surface(name=name, values=values, support=support)


def _surface_from_band_metadata(
    *,
    values,
    bounds: tuple[float, float, float, float],
    crs: object,
    nodata: float,
    name: str,
) -> Surface:
    arr = np.asarray(values, dtype=float)
    nrows, ncols = arr.shape
    xmin, ymin, xmax, ymax = (float(v) for v in bounds)
    dx = (xmax - xmin) / float(ncols)
    dy = (ymax - ymin) / float(nrows)
    support = RasterSupport(
        crs=(None if crs is None else str(crs)),
        dx=dx,
        dy=dy,
        xmin=xmin,
        xmax=xmax,
        ymin=ymin,
        ymax=ymax,
        nrows=nrows,
        ncols=ncols,
        nodata=float(nodata),
    )
    return Surface(name=name, values=arr, support=support)


def _resampling_name(
    src_shape: tuple[int, int],
    dst_shape: tuple[int, int],
) -> str:
    src_pixels = int(src_shape[0]) * int(src_shape[1])
    dst_pixels = int(dst_shape[0]) * int(dst_shape[1])
    return "bilinear" if dst_pixels >= src_pixels else "average"


def _coerce_sgrid_config(config: SGridConfig | Mapping[str, object]) -> SGridConfig:
    if isinstance(config, SGridConfig):
        return config
    if isinstance(config, Mapping):
        return SGridConfig.from_mapping(config)
    raise TypeError("config must be a SGridConfig instance or mapping payload")


def _build_top_surface(
    cfg: SGridConfig,
    *,
    reader: RasterGridReader,
    discretizer: PlanarDiscretizer,
) -> tuple[Surface, tuple[int, int]]:
    source_top_grid = reader.read_top_grid(str(cfg.top_path))
    source_shape = (int(source_top_grid.nrow), int(source_top_grid.ncol))

    target_top_grid = discretizer.discretize_top(
        source_top_grid=source_top_grid,
        mode=str(cfg.plan_discretization_mode),
        nx=cfg.nx,
        ny=cfg.ny,
        nodata=float(cfg.nodata),
        fallback_crs=cfg.crs,
    )
    top_surface = _surface_from_top_grid(
        target_top_grid,
        nodata=float(cfg.nodata),
        name="top_surface",
    )
    return top_surface, source_shape


def _build_bottom_surface(
    cfg: SGridConfig,
    *,
    top_surface: Surface,
    source_top_shape: tuple[int, int],
    reader: RasterGridReader,
) -> Surface:
    top = np.asarray(top_surface.as_array(), dtype=float)
    nodata = float(cfg.nodata)

    if cfg.genmtd_bot == "constant_thickness":
        bottom_values = top - float(cfg.thick)
        bottom_surface = Surface(
            name="bottom_surface",
            values=bottom_values,
            support=top_surface.support,
        )
    elif cfg.genmtd_bot == "constant_altitude":
        bottom_values = np.full_like(top, float(cfg.zbot), dtype=float)
        bottom_surface = Surface(
            name="bottom_surface",
            values=bottom_values,
            support=top_surface.support,
        )
    elif cfg.genmtd_bot == "filepath":
        values, _, crs, bounds = reader.read_band1_with_metadata(str(cfg.bot_path))
        source_bottom = _surface_from_band_metadata(
            values=values,
            bounds=bounds,
            crs=crs,
            nodata=nodata,
            name="bottom_surface",
        )
        if cfg.plan_discretization_mode == "resample_to_shape":
            target_shape = np.asarray(top_surface.as_array(), dtype=float).shape
            src_shape = np.asarray(source_bottom.as_array(), dtype=float).shape
            source_bottom = source_bottom.resample_to_shape(
                int(target_shape[0]),
                int(target_shape[1]),
                nodata=nodata,
                resampling=_resampling_name(src_shape=src_shape, dst_shape=target_shape),
            )
        bottom_surface = source_bottom
    else:
        raw_bot = np.asarray(cfg.bot_raster, dtype=float)
        target_shape = np.asarray(top_surface.as_array(), dtype=float).shape
        if raw_bot.shape == target_shape:
            bottom_surface = Surface(
                name="bottom_surface",
                values=raw_bot,
                support=top_surface.support,
            )
        elif raw_bot.shape == tuple(source_top_shape):
            source_support = top_surface.support
            if (
                source_support is None
                or int(source_support.nrows) != int(source_top_shape[0])
                or int(source_support.ncols) != int(source_top_shape[1])
            ):
                # Rebuild support for native top shape from target support extent.
                xmin = float(top_surface.support.xmin)
                ymin = float(top_surface.support.ymin)
                xmax = float(top_surface.support.xmax)
                ymax = float(top_surface.support.ymax)
                source_support = RasterSupport(
                    crs=top_surface.support.crs,
                    dx=(xmax - xmin) / float(source_top_shape[1]),
                    dy=(ymax - ymin) / float(source_top_shape[0]),
                    xmin=xmin,
                    xmax=xmax,
                    ymin=ymin,
                    ymax=ymax,
                    nrows=int(source_top_shape[0]),
                    ncols=int(source_top_shape[1]),
                    nodata=nodata,
                )
            source_bottom = Surface(
                name="bottom_surface",
                values=raw_bot,
                support=source_support,
            )
            if cfg.plan_discretization_mode == "resample_to_shape":
                source_bottom = source_bottom.resample_to_shape(
                    int(target_shape[0]),
                    int(target_shape[1]),
                    nodata=nodata,
                    resampling=_resampling_name(
                        src_shape=tuple(source_top_shape),
                        dst_shape=target_shape,
                    ),
                )
            bottom_surface = source_bottom
        else:
            raise ValueError(
                "bot_raster shape must match top source shape or top target shape. "
                f"Got bot{raw_bot.shape}, source_top{tuple(source_top_shape)}, "
                f"target_top{target_shape}."
            )

    bot_arr = np.asarray(bottom_surface.as_array(), dtype=float)
    bot_arr[top <= nodata] = nodata
    return Surface(
        name=bottom_surface.name,
        values=bot_arr,
        support=bottom_surface.support,
    )


def build_sgrid_from_config(config: SGridConfig | Mapping[str, object]):
    """Build one FloPy structured grid from validated SGrid config payload."""
    cfg = _coerce_sgrid_config(config)
    reader = RasterGridReader()
    discretizer = PlanarDiscretizer()

    top_surface, source_top_shape = _build_top_surface(
        cfg,
        reader=reader,
        discretizer=discretizer,
    )
    bottom_surface = _build_bottom_surface(
        cfg,
        top_surface=top_surface,
        source_top_shape=source_top_shape,
        reader=reader,
    )

    vertical_cfg = VerticalGridConfig(
        genmtd_lay=cfg.genmtd_lay,
        nlay=(None if cfg.genmtd_lay == "list" else cfg.nlay),
        lay_decay=cfg.lay_decay,
        lay_proportions=(
            tuple(float(v) for v in cfg.lay_proportions)
            if cfg.lay_proportions is not None
            else None
        ),
        nodata=float(cfg.nodata),
    )
    return StructuredGridBuilder().build_from_surfaces(
        top_surface=top_surface,
        bottom_surface=bottom_surface,
        vertical_config=vertical_cfg,
    )
