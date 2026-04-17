"""Watershed-facing runtime and descriptors.

This package preserves the historical ``Watershed`` workflow behind a stable
top-level namespace instead of routing through compatibility packages.
"""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "GeologyConfig",
    "Hydraulic",
    "Hydrography",
    "IntermittencyManager",
    "Settings",
    "Watershed",
]

_EXPORTS = {
    "GeologyConfig": ("hydromodpy.data.variables.geology.config", "GeologyConfig"),
    "Hydraulic": ("hydromodpy.watershed.hydraulic", "Hydraulic"),
    "Hydrography": ("hydromodpy.data.variables.hydrography.result", "HydrographyResult"),
    "IntermittencyManager": (
        "hydromodpy.data.variables.intermittency.manager",
        "IntermittencyManager",
    ),
    "Settings": ("hydromodpy.watershed.settings", "Settings"),
    "Watershed": ("hydromodpy.watershed.watershed", "Watershed"),
}


def __getattr__(name: str):
    if name in _EXPORTS:
        module_name, attr_name = _EXPORTS[name]
        module = import_module(module_name)
        return getattr(module, attr_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
