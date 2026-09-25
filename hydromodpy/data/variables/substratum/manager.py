"""Substratum manager: aquifer-bottom rasters from the user's files."""

from __future__ import annotations

from hydromodpy.data.managers.base_manager_file import RasterFileManager


class SubstratumManager(RasterFileManager):
    VARIABLE_NAME = "substratum"
