"""Layer base variable: elevation rasters of layer bases from the user's files."""

from __future__ import annotations

from hydromodpy.data.families.files import RasterFileVariable


class LayerBaseVariable(RasterFileVariable):
    VARIABLE_NAME = "layer_base"
