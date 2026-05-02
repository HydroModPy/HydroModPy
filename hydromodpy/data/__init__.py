"""Public API for HydroModPy data loading and planning.

This package-level facade stays lazy so doc builds and lightweight imports do
not instantiate the full data-manager dependency graph.
"""

from __future__ import annotations

from importlib import import_module
from importlib.util import find_spec

__all__ = (
    "DataManagers",
    "DataManagersConfig",
    "DataLoadPlan",
    "DataPlanner",
    "DataManagersRuntimeLoader",
)

_LAZY_IMPORTS = {
    "DataManagers": "hydromodpy.data.data_managers:DataManagers",
    "DataManagersConfig": "hydromodpy.data.data_managers_config:DataManagersConfig",
    "DataLoadPlan": "hydromodpy.data.plan:DataLoadPlan",
    "DataPlanner": "hydromodpy.data.planner:DataPlanner",
    "DataManagersRuntimeLoader": "hydromodpy.data.loader:DataManagersRuntimeLoader",
}


def __getattr__(name: str):
    target = _LAZY_IMPORTS.get(name)
    if target is not None:
        module_path, attr_name = target.split(":", 1)
        module = import_module(module_path)
        attr = getattr(module, attr_name)
        globals()[name] = attr
        return attr

    module_name = f"{__name__}.{name}"
    if find_spec(module_name) is not None:
        module = import_module(module_name)
        globals()[name] = module
        return module

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
