"""Backward-compatible import path for :class:`Hydrography`.

Hydrography moved to ``hydromodpy.data_managers.hydrography``.
This module is kept as a thin compatibility layer.
"""

from hydromodpy.data_managers.hydrography.hydrography import Hydrography

__all__ = ("Hydrography",)
