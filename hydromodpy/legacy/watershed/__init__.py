"""Legacy watershed-facing descriptor exports.

This namespace preserves legacy watershed descriptors while their
implementations progressively move to dedicated ``hydromodpy.data_managers``
packages.
"""

from hydromodpy.legacy.watershed.geology_config import GeologyConfig
from hydromodpy.legacy.watershed.hydraulic import Hydraulic
from hydromodpy.data_managers.hydrography import Hydrography
from hydromodpy.data_managers.intermittency import Intermittency
from hydromodpy.simulation.settings import Settings

__all__ = ['GeologyConfig', 'Hydraulic', 'Hydrography', 'Intermittency', 'Settings']
