"""Load the sealed share: the user's raster, a url, or a provider asked over the watershed."""

from __future__ import annotations

from hydromodpy.data.families.files import ProviderRasterVariable


class ImperviousVariable(ProviderRasterVariable):
    """The sealed share, one raster 0 to 1 per pixel."""

    VARIABLE_NAME = "impervious"
    INTERNAL_UNIT = "-"


__all__ = ["ImperviousVariable"]
