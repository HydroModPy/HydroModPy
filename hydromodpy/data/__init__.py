"""Public API for HydroModPy data loading and planning."""

from hydromodpy.data.data_managers import DataManagers
from hydromodpy.data.data_managers_config import DataManagersConfig
from hydromodpy.data.plan import DataLoadPlan
from hydromodpy.data.planner import DataManagersPlanner

__all__ = (
    "DataManagers",
    "DataManagersConfig",
    "DataLoadPlan",
    "DataManagersPlanner",
    "DataManagersRuntimeLoader",
)


def __getattr__(name: str):
    if name == "DataManagersRuntimeLoader":
        from hydromodpy.data.runtime_loader import DataManagersRuntimeLoader

        return DataManagersRuntimeLoader
    raise AttributeError(f"module 'hydromodpy.data' has no attribute {name!r}")
