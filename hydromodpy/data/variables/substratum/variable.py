"""Substratum variable: aquifer-bottom rasters from the user's files."""

from __future__ import annotations

from hydromodpy.data.families.files import RasterFileVariable


class SubstratumVariable(RasterFileVariable):
    VARIABLE_NAME = "substratum"
