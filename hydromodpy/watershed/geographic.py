"""Backward-compatible wrapper for Geographic moved to `hydromodpy.geographic`."""

from hydromodpy.geographic.geographic import DEM_correcflow_analysis, Geographic

__all__ = ["Geographic", "DEM_correcflow_analysis"]
