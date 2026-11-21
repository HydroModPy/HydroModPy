"""Load the infiltration ratio: the user's raster, a url, or OCS GE over the watershed."""

from __future__ import annotations

from hydromodpy.data.families.files import ProviderRasterVariable


class InfiltrationRatioVariable(ProviderRasterVariable):
    """The infiltration ratio, one raster 0 to 1 per pixel."""

    VARIABLE_NAME = "infiltration_ratio"
    INTERNAL_UNIT = "-"


__all__ = ["InfiltrationRatioVariable"]
