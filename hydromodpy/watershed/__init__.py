"""Compatibility namespace for legacy watershed descriptors.

This package keeps ``from hydromodpy.watershed import ...`` working while
legacy module paths (for example ``hydromodpy.watershed.climatic``) remain
removed.
"""

from hydromodpy.watershed_legacy import (
    Driasclimat,
    Driaseau,
    GeologyConfig,
    Hydraulic,
    Hydrography,
    Hydrometry,
    Intermittency,
    Piezometry,
    SafranSurfex,
    Settings,
)

__all__ = [
    "Driasclimat",
    "Driaseau",
    "GeologyConfig",
    "Hydraulic",
    "Hydrography",
    "Hydrometry",
    "Intermittency",
    "Piezometry",
    "SafranSurfex",
    "Settings",
]
