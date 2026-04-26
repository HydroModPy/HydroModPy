"""Public API for HydroModPy data loading and planning.

This package-level facade stays lazy so doc builds and lightweight imports do
not instantiate the full data-manager dependency graph.
"""

from __future__ import annotations

from importlib import import_module

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
    try:
        target = _LAZY_IMPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module_path, attr_name = target.split(":", 1)
    module = import_module(module_path)
    attr = getattr(module, attr_name)
    globals()[name] = attr
    return attr
