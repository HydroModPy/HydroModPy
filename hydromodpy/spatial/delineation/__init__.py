"""Catchment delineation backends.

Runtime entry points:

- ``DelineationBackend`` — high-level Protocol (see :mod:`.base`).
- ``WhiteboxBackend`` — low-level file-based Protocol (legacy contract).
- ``get_backend(name)`` — resolve a registered backend by name with
  graceful fallback when an optional dependency is missing.
"""

from __future__ import annotations

from hydromodpy.spatial.delineation.base import DelineationBackend, WhiteboxBackend
from hydromodpy.spatial.delineation.registry import (
    available_backends,
    get_backend,
    register_backend,
)

__all__ = [
    "DelineationBackend",
    "WhiteboxBackend",
    "available_backends",
    "get_backend",
    "register_backend",
]
