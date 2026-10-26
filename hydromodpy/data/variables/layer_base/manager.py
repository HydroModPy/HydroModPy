"""Layer base manager: elevation rasters of layer bases from the user's files."""

from __future__ import annotations

from hydromodpy.data.managers.base_manager_file import RasterFileManager


class LayerBaseManager(RasterFileManager):
    VARIABLE_NAME = "layer_base"
