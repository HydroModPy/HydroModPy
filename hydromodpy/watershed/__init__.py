"""Watershed-facing descriptor exports.

This namespace keeps high-level watershed descriptors under a stable import
path while their implementations progressively move to dedicated
``hydromodpy.data_managers`` packages.
"""

from hydromodpy.data_managers.climatic.driasclimat import Driasclimat
from hydromodpy.data_managers.climatic.driaseau import Driaseau
from hydromodpy.watershed.geology_config import GeologyConfig
from hydromodpy.watershed.hydraulic import Hydraulic
from hydromodpy.watershed.hydrography import Hydrography
from hydromodpy.data_managers.hydrometry.hydrometry_legacy import Hydrometry
from hydromodpy.data_managers.intermittency import Intermittency
from hydromodpy.data_managers.piezometry.piezometry_legacy import Piezometry
from hydromodpy.watershed.settings import Settings
from hydromodpy.data_managers.climatic.safransurfex import SafranSurfex

__all__ = ['Driasclimat', 'Driaseau', 'GeologyConfig', 'Hydraulic', 'Hydrography', 'Hydrometry', 'Intermittency', 'Piezometry', 'Settings', 'SafranSurfex']
