"""Load the curve number: a raster read as it is, or one built from land cover."""

from __future__ import annotations

from hydromodpy.data.families.files import ProviderRasterVariable


class CurveNumberVariable(ProviderRasterVariable):
    """The SCS curve number, AMC II, one raster per run."""

    VARIABLE_NAME = "curve_number"
    INTERNAL_UNIT = "-"


__all__ = ["CurveNumberVariable"]
