"""Legacy compatibility packages kept during the package reorganization."""

from __future__ import annotations

import importlib

_MODULES = {
    "geographic": "hydromodpy.legacy.geographic",
    "watershed": "hydromodpy.legacy.watershed",
}


def __getattr__(name: str):
    if name in _MODULES:
        module = importlib.import_module(_MODULES[name])
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["geographic", "watershed"]
