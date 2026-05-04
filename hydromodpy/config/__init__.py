"""Application-level configuration API.

``HydroModPyConfig`` assembles the full user-facing TOML tree, so it sits above
``core``. The generic config helpers remain under ``hydromodpy.core.config``.
Per-layer sub-section configs live in their own packages (e.g.
``hydromodpy.analysis.config:AnalysisConfig``).
"""

from __future__ import annotations


def __getattr__(name: str):
    if name == "HydroModPyConfig":
        from hydromodpy.config.hydromodpy_config import HydroModPyConfig

        return HydroModPyConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["HydroModPyConfig"]
