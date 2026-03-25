import warnings

warnings.warn(
    "The 'hydromodpy.data.climatic' module is deprecated. "
    "Use the new variable-specific data managers instead "
    "(recharge/, precipitation/, etp/, etc.).",
    DeprecationWarning,
    stacklevel=2,
)

from hydromodpy.data.climatic.climatic import Climatic
from hydromodpy.data.climatic.driasclimat import Driasclimat
from hydromodpy.data.climatic.driaseau import Driaseau
from hydromodpy.data.climatic.safransurfex import Merge, SafranSurfex
from hydromodpy.data.climatic.sim2 import Sim2
from hydromodpy.data.climatic.sim2_API import Sim2_API

__all__ = ["Climatic", "Driasclimat", "Driaseau", "Merge", "SafranSurfex", "Sim2", "Sim2_API"]
