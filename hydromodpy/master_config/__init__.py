"""HydroModPy configuration module."""

from hydromodpy.master_config.base import HydroModelBase
from hydromodpy.master_config.profile import Profile


def __getattr__(name: str):
    if name == "HydroModPyConfig":
        from hydromodpy.master_config.hydromodpy_config import HydroModPyConfig

        return HydroModPyConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["HydroModPyConfig", "HydroModelBase", "Profile"]
