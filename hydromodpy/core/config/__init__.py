"""HydroModPy configuration module."""

from hydromodpy.core.config.base import HydroModelBase


def __getattr__(name: str):
    if name == "HydroModPyConfig":
        from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig
        return HydroModPyConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["HydroModPyConfig", "HydroModelBase"]
