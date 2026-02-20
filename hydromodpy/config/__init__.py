"""
HydroModPy configuration module.

Generate TOML templates:
    python -m hydromodpy.config --profile user --modules geographic
    python -m hydromodpy.config --profile expert
"""
from hydromodpy.config.hydromodpy_config import HydroModPyConfig

__all__ = ["HydroModPyConfig"]
