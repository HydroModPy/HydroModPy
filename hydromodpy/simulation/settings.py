"""Deprecated alias for the legacy watershed settings payload."""

from __future__ import annotations

import warnings

warnings.warn(
    "The 'hydromodpy.simulation.settings' module is deprecated. "
    "Use 'hydromodpy.watershed.settings' for the preserved Watershed workflow.",
    DeprecationWarning,
    stacklevel=2,
)

from hydromodpy.watershed.settings import Settings

__all__ = ("Settings",)
