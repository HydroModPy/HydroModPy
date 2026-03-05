"""Legacy watershed-facing descriptor exports.

This namespace preserves legacy watershed descriptors while their
implementations progressively move to dedicated ``hydromodpy.data_managers``
packages.
"""

from hydromodpy.data_managers.climatic.driasclimat import Driasclimat
from hydromodpy.data_managers.climatic.driaseau import Driaseau
from hydromodpy.watershed_legacy.geology_config import GeologyConfig
from hydromodpy.watershed_legacy.hydraulic import Hydraulic
from hydromodpy.watershed_legacy.hydrography import Hydrography
from hydromodpy.data_managers.hydrometry.hydrometry_legacy import Hydrometry
from hydromodpy.data_managers.intermittency import Intermittency
from hydromodpy.data_managers.piezometry.piezometry_legacy import Piezometry
from hydromodpy.watershed_legacy.settings import Settings
from hydromodpy.data_managers.climatic.safransurfex import SafranSurfex

__all__ = ['Driasclimat', 'Driaseau', 'GeologyConfig', 'Hydraulic', 'Hydrography', 'Hydrometry', 'Intermittency', 'Piezometry', 'Settings', 'SafranSurfex']
