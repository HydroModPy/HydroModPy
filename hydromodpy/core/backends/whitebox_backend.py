"""Deprecated: moved to ``hydromodpy.spatial.delineation.base``."""

from __future__ import annotations

import warnings

warnings.warn(
    "hydromodpy.core.backends.whitebox_backend is deprecated; "
    "import WhiteboxBackend from hydromodpy.spatial.delineation instead.",
    DeprecationWarning,
    stacklevel=2,
)

from hydromodpy.spatial.delineation.base import WhiteboxBackend

__all__ = ["WhiteboxBackend"]
