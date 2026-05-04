"""Application-level configuration API.

``HydroModPyConfig`` assembles the full user-facing TOML tree, so it sits above
``core``. The generic config helpers remain under ``hydromodpy.core.config``.
"""

from __future__ import annotations


def __getattr__(name: str):
    if name == "HydroModPyConfig":
        from hydromodpy.config.hydromodpy_config import HydroModPyConfig

        return HydroModPyConfig
    if name == "AnalysisConfig":
        from hydromodpy.config.analysis import AnalysisConfig

        return AnalysisConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["AnalysisConfig", "HydroModPyConfig"]
