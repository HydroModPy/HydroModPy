"""Shared solver utilities with lazy imports.

Only temporal-mesh helpers live here. The spatial mesh utilities that used to
live under ``solver.utils.mesh`` moved to ``hydromodpy.spatial.mesh`` — import
them from there directly.
"""

from __future__ import annotations

from importlib import import_module

_TEMPORAL_EXPORTS = {
    "TMeshConfig",
    "TMesh_Generation",
    "load_tmesh_toml",
    "validate_tmesh_config_data",
}

__all__ = [
    "TMeshConfig",
    "TMesh_Generation",
    "load_tmesh_toml",
    "validate_tmesh_config_data",
]


def __getattr__(name: str):
    if name in _TEMPORAL_EXPORTS:
        module = import_module("hydromodpy.solver.utils.temporal")
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
