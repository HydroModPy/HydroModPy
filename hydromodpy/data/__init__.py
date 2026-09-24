"""Public API for HydroModPy data loading and planning.

This package-level facade stays lazy so doc builds and lightweight imports do
not instantiate the full data-manager dependency graph. A name resolved here is
cached in this module: a test that replaces one patches ``hydromodpy.data.<Name>``,
not the module that defines it.
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
    "DataRequest",
    "DataStore",
    "run_request",
)

_LAZY_IMPORTS = {
    "DataManagers": "hydromodpy.data.loading.container:DataManagers",
    "DataManagersConfig": "hydromodpy.data.loading.config_schema:DataManagersConfig",
    "DataLoadPlan": "hydromodpy.data.loading.plan:DataLoadPlan",
    "DataPlanner": "hydromodpy.data.loading.planner:DataPlanner",
    "DataManagersRuntimeLoader": "hydromodpy.data.loading.loader:DataManagersRuntimeLoader",
    "DataRequest": "hydromodpy.data.request.model:DataRequest",
    "DataStore": "hydromodpy.data.loading.store:DataStore",
    "run_request": "hydromodpy.data.request.engine:run_request",
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
