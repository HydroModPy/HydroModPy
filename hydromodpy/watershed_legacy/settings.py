"""Backward-compatible import path for :class:`Settings`.

Settings moved to ``hydromodpy.simulation.settings``.
This module is kept as a thin compatibility layer.
"""

from hydromodpy.simulation.settings import Settings

__all__ = ("Settings",)
