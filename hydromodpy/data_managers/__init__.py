"""Public API for HydroModPy data-manager orchestration.

Root-level contract
-------------------
This package-level module exposes the small set of root primitives used by
launcher/runtime code:

- ``DataManagersConfig``: validated declarative configuration from ``[data]``,
- ``DataManagersPlanner``: deterministic inference of active manager families,
- ``DataLoadPlan``: immutable resolved view (explicit + inferred).
- ``DataManagersRuntimeLoader``: runtime loader dispatch driven by ``DataLoadPlan``.

The implementation details of each thematic manager remain in subpackages
(``geology/``, ``hydrometry/``, etc.); this root API only handles activation
and planning concerns.
"""

from hydromodpy.data_managers.data_managers_config import DataManagersConfig
from hydromodpy.data_managers.data_managers import DataManagers
from hydromodpy.data_managers.plan import DataLoadPlan
from hydromodpy.data_managers.planner import DataManagersPlanner

# Keep __all__ explicit so import surfaces stay stable for callers and docs.
__all__ = (
    "DataManagers",
    "DataManagersConfig",
    "DataLoadPlan",
    "DataManagersPlanner",
    "DataManagersRuntimeLoader",
)


def __getattr__(name: str):
    if name == "DataManagersRuntimeLoader":
        from hydromodpy.data_managers.runtime_loader import DataManagersRuntimeLoader

        return DataManagersRuntimeLoader
    raise AttributeError(f"module 'hydromodpy.data_managers' has no attribute {name!r}")
