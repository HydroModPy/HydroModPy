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
  - vertical layering, through :func:`hydromodpy.spatial.domain.layering.layer_stack`,
    which the unstructured extrusion calls too,
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

from hydromodpy.spatial.domain.layering import (
    assert_bottom_below_top,
    coerce_vertical_config,
    layer_stack,
)
from hydromodpy.spatial.domain.layers_config import VerticalGridConfig
from hydromodpy.spatial.surface import Surface


@dataclass(frozen=True)
class StructuredGridSpec:
    """HydroModPy-native structured-grid descriptor (no FloPy dependency).

    ``xvertices`` and ``yvertices`` follow the MODFLOW convention: row 0 is
    the top of the grid (largest y), row ``nrow`` is the bottom (``yoff``).
    ``idomain`` has the shape of ``botm``: 1 active, 0 outside the domain, -1 a
    pinched cell of a layering by surfaces.
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
    idomain: np.ndarray
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
        base_surfaces: Mapping[str, Surface] | None = None,
    ) -> StructuredGridSpec:
        """
        Build one structured grid from two absolute-elevation surfaces.

        The method intentionally separates three steps:
        1. Validate horizontal/geometric compatibility of inputs.
        2. Build `botm` and `idomain` with :func:`layer_stack`.
        3. Return a `StructuredGridSpec`.

        ``base_surfaces`` holds the layer bases a layering by surfaces reads, on
        the grid of ``top_surface``.
        """
        cfg = coerce_vertical_config(vertical_config)

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

        assert_bottom_below_top(top=top, bot=bot, nodata=nodata)

        # 2) Layer bottoms and idomain from config.
        bases = {}
        for name, surface in (base_surfaces or {}).items():
            values = np.asarray(surface.as_array(), dtype=float)
            if values.shape != top.shape:
                raise ValueError(
                    f"The layer base {name!r} has shape {values.shape}, the top {top.shape}."
                )
            bases[name] = values
        stack = layer_stack(
            top=top, bottom=bot, invalid=invalid, vertical_config=cfg, bases=bases, nodata=nodata
        )

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
            botm=stack.botm,
            xoff=xmin,
            yoff=ymin,
            nlay=int(stack.botm.shape[0]),
            nrow=nrow,
            ncol=ncol,
            xvertices=xvertices,
            yvertices=yvertices,
            idomain=stack.idomain,
            crs=support.crs,
        )


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
