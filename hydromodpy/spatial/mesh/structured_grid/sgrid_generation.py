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
- Horizontal discretization (XY) is handled outside this builder: the planar
  grid comes from the mesh engine, and `Surface.resample_to_shape(...)`
  resamples the surfaces to its shape.
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
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

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
    """The vertical part of a structured grid: top, layer bottoms and ``idomain``.

    ``top`` has the shape of the surfaces, ``botm`` and ``idomain`` one more
    axis for the layers. ``idomain`` is 1 active, 0 outside the domain, -1 a
    pinched cell of a layering by surfaces.
    """

    top: np.ndarray
    botm: np.ndarray
    nlay: int
    idomain: np.ndarray


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

        # The planar grid is the mesh's, the steps of the support are only checked.
        width = float(support.xmax) - float(support.xmin)
        height = float(support.ymax) - float(support.ymin)
        dx = float(support.dx) if support.dx is not None else width / int(support.ncols)
        dy = float(support.dy) if support.dy is not None else height / int(support.nrows)
        if dx <= 0 or dy <= 0:
            raise ValueError(f"Invalid support cell sizes: dx={dx}, dy={dy}.")

        return StructuredGridSpec(
            top=top,
            botm=stack.botm,
            nlay=int(stack.botm.shape[0]),
            idomain=stack.idomain,
        )
