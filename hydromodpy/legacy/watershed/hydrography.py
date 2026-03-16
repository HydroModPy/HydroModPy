"""Backward-compatible import path for :class:`HydrographyResult`.

Hydrography moved to ``hydromodpy.data_managers.variables.hydrography``.
This module is kept as a thin compatibility layer.
"""

from hydromodpy.data_managers.variables.hydrography.result import HydrographyResult as Hydrography

__all__ = ("Hydrography",)
