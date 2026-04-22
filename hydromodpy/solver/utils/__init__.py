"""Shared solver utilities with lazy imports.

Keeping this package lightweight matters because some callers only need a very
small reader module under ``solver.utils.mesh`` and should not pay the import
cost of the full solver utility stack.
"""

from __future__ import annotations

from importlib import import_module

_CARTESIAN_EXPORTS = {
    "build_field_mesh_from_sgrid",
    "extract_structured_vertices",
}
_TEMPORAL_EXPORTS = {
    "TMeshConfig",
    "TMeshConfigModel",
    "TMesh_Generation",
    "load_tmesh_toml",
    "validate_tmesh_config_data",
}

__all__ = [
    "build_field_mesh_from_sgrid",
    "extract_structured_vertices",
    "TMeshConfig",
    "TMeshConfigModel",
    "TMesh_Generation",
    "validate_tmesh_config_data",
    "load_tmesh_toml",
]


def __getattr__(name: str):
    if name in _CARTESIAN_EXPORTS:
        module = import_module("hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_mesh_adapter")
        value = getattr(module, name)
        globals()[name] = value
        return value
    if name in _TEMPORAL_EXPORTS:
        module = import_module("hydromodpy.solver.utils.temporal")
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
