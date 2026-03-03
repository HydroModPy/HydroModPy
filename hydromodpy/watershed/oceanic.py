"""Backward-compatible Oceanic module alias.

This module keeps API compatibility for imports targeting
``hydromodpy.watershed.oceanic`` while the implementation currently lives in
``hydromodpy.watershed.oceanic_old``.
"""

from hydromodpy.watershed.oceanic_old import Oceanic

__all__ = ["Oceanic"]
