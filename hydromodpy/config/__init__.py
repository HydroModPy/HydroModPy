"""
HydroModPy configuration module.

Generate TOML templates:
    python -m hydromodpy.config --profile user --modules geographic
    python -m hydromodpy.config --profile expert
"""


def __getattr__(name: str):
    if name == "HydroModPyConfig":
        from hydromodpy.config.hydromodpy_config import HydroModPyConfig
        return HydroModPyConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["HydroModPyConfig"]
