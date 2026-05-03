"""
Surface-driven structured-grid generation.

Overview
--------
This module builds a HydroModPy-native ``StructuredGridSpec`` from two
absolute-elevation surfaces:
- one topographic surface (`top_surface`),
- one bottom surface (`bottom_surface`).

Design responsibilities
-----------------------
- Horizontal discretization (XY) is handled outside this builder, typically in
  `Surface` (`resample_to_shape(...)`).
- This builder handles only:
  - geometric consistency checks for vertical construction,
  - vertical layering (`constant`, `decay`, `list`),
  - assembly of a `StructuredGridSpec` POPO.

Important convention
--------------------
`top_surface` and `bottom_surface` are absolute altitudes in the same datum.
No additive combination is done between the two surfaces.
HydroModPy assumes metric geometry throughout this workflow.

FloPy is intentionally not imported here. Translation to a
``flopy.discretization.StructuredGrid`` is performed at the solver boundary by
``hydromodpy.solver.modflow_common.sgrid_to_flopy.translate``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from hydromodpy.spatial.surface import Surface

from .sgrid_config import VerticalGridConfig


@dataclass(frozen=True)
class StructuredGridSpec:
    """HydroModPy-native structured-grid descriptor (no FloPy dependency).

    ``xvertices`` and ``yvertices`` follow the MODFLOW convention: row 0 is
    the top of the grid (largest y), row ``nrow`` is the bottom (``yoff``).
    """

    delc: np.ndarray
    delr: np.ndarray
    top: np.ndarray
    botm: np.ndarray
    xoff: float
    yoff: float
    nlay: int
    nrow: int
    ncol: int
    xvertices: np.ndarray
    yvertices: np.ndarray
    crs: Any = None


class StructuredGridBuilder:
    """
    Build `StructuredGridSpec` objects from explicit top/bottom surfaces.
    """

    def __init__(self):
        # No hidden state: deterministic transformations only.
        pass

    def build_from_surfaces(
        self,
        top_surface: Surface,
        bottom_surface: Surface,
        vertical_config: VerticalGridConfig | Mapping[str, object] | None = None,
    ) -> StructuredGridSpec:
        """
        Build one structured grid from two absolute-elevation surfaces.

        The method intentionally separates three steps:
        1. Validate horizontal/geometric compatibility of inputs.
        2. Compute vertical layer proportions.
        3. Build `botm` and return a `StructuredGridSpec`.
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
        invalid = ~np.isfinite(top) | ~np.isfinite(bot) | (top <= nodata) | (bot <= nodata)
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

        # 3) Build layer bottoms and assemble the StructuredGridSpec.
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
        xvertices, yvertices = _structured_vertices(delr=delr, delc=delc, xoff=xmin, yoff=ymin)

        return StructuredGridSpec(
            delc=delc,
            delr=delr,
            top=top,
            botm=botm,
            xoff=xmin,
            yoff=ymin,
            nlay=int(nlay),
            nrow=nrow,
            ncol=ncol,
            xvertices=xvertices,
            yvertices=yvertices,
            crs=support.crs,
        )

    @staticmethod
    def _assert_bottom_below_top(top, bot, nodata):
        """
        Ensure vertical order is physically consistent: bottom < top on valid cells.
        """
        top = np.asarray(top, dtype=float)
        bot = np.asarray(bot, dtype=float)
        nodata_value = float(nodata)

        valid = np.isfinite(top) & np.isfinite(bot) & (top > nodata_value) & (bot > nodata_value)
        if not np.any(valid):
            raise ValueError(
                "No finite overlapping valid cells found between top and bottom surfaces."
            )

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
    raise TypeError("vertical_config must be None, VerticalGridConfig, or a mapping of values.")


def _structured_vertices(
    *,
    delr: np.ndarray,
    delc: np.ndarray,
    xoff: float,
    yoff: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Build (xvertices, yvertices) following the MODFLOW convention.

    Row 0 of ``yvertices`` carries the top of the grid (largest y); row
    ``nrow`` carries ``yoff``. Shapes are (nrow + 1, ncol + 1).
    """
    delr_arr = np.asarray(delr, dtype=float).reshape(-1)
    delc_arr = np.asarray(delc, dtype=float).reshape(-1)
    x_edges = float(xoff) + np.concatenate(([0.0], np.cumsum(delr_arr)))
    total_dy = float(np.sum(delc_arr))
    y_edges = (float(yoff) + total_dy) - np.concatenate(([0.0], np.cumsum(delc_arr)))
    xvertices, yvertices = np.meshgrid(x_edges, y_edges, indexing="xy")
    return np.asarray(xvertices, dtype=float), np.asarray(yvertices, dtype=float)
