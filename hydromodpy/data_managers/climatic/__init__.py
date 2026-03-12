import warnings

warnings.warn(
    "The 'hydromodpy.data_managers.climatic' module is deprecated. "
    "Use the new variable-specific data managers instead "
    "(recharge/, precipitation/, etp/, etc.).",
    DeprecationWarning,
    stacklevel=2,
)

from hydromodpy.data_managers.climatic.climatic import Climatic
from hydromodpy.data_managers.climatic.driasclimat import Driasclimat
from hydromodpy.data_managers.climatic.driaseau import Driaseau
from hydromodpy.data_managers.climatic.safransurfex import Merge, SafranSurfex
from hydromodpy.data_managers.climatic.sim2 import Sim2
from hydromodpy.data_managers.climatic.sim2_API import Sim2_API

__all__ = ["Climatic", "Driasclimat", "Driaseau", "Merge", "SafranSurfex", "Sim2", "Sim2_API"]
