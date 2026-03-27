"""Watershed-facing runtime and descriptors.

This package preserves the historical ``Watershed`` workflow behind a stable
top-level namespace instead of routing through compatibility packages.
"""

from hydromodpy.data.variables.geology.config import GeologyConfig
from hydromodpy.data.variables.hydrography.result import HydrographyResult as Hydrography
from hydromodpy.data.variables.intermittency.manager import IntermittencyManager
from hydromodpy.simulation.settings import Settings
from hydromodpy.watershed.hydraulic import Hydraulic
from hydromodpy.watershed.watershed import Watershed

__all__ = [
    "GeologyConfig",
    "Hydraulic",
    "Hydrography",
    "IntermittencyManager",
    "Settings",
    "Watershed",
]
