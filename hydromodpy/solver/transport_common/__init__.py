"""Shared transport runtime helpers used by concrete solver backends."""

from .runtime_arrays import build_concentration_runtime_overrides, flow_grid_shape

__all__ = ["build_concentration_runtime_overrides", "flow_grid_shape"]
