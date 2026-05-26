"""DEM data source APIs."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType

_API_MODULES = frozenset(
    {
        "geoplateforme_download",
        "ign_dem_fr",
    }
)


def __getattr__(name: str) -> ModuleType:
    if name in _API_MODULES:
        module = import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = tuple(sorted(_API_MODULES))
