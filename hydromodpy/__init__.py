"""Public entry points for HydroModPy."""

from __future__ import annotations

import importlib

from hydromodpy._api import (
    batch,
    calibrate,
    catalog,
    compare_methods,
    compare_pair,
    doctor,
    mesh,
    open,
    overview,
    report,
    run,
    testbed,
)
from hydromodpy._bootstrap import bootstrap
from hydromodpy._lazy import LAZY_IMPORTS as _LAZY_IMPORTS
from hydromodpy._lazy import MODULE_EXPORTS as _MODULE_EXPORTS
from hydromodpy.core.io.proj_bootstrap import bootstrap_proj
from hydromodpy.core.logging import LogManager
from hydromodpy.core.version import __version__

__author__ = "Alexandre Gauvain, Ronan Abherve, Jean-Raynald de Dreuzy"
__email__ = (
    "alexandre.gauvain.ag@gmail.com, ronan.abherve@gmail.com, jean-raynald.de-dreuzy@univ-rennes.fr"
)

_log_manager = LogManager(mode="verbose", log_dir=None, overwrite=False)
# Public access to log manager for users
log_manager = _log_manager


def __getattr__(name: str):
    if name in _MODULE_EXPORTS:
        module = importlib.import_module(_MODULE_EXPORTS[name])
        globals()[name] = module
        return module
    if name in _LAZY_IMPORTS:
        target = _LAZY_IMPORTS[name]
        if ":" in target:
            module_path, attr_name = target.split(":", 1)
        else:
            module_path, attr_name = target, name
        module = importlib.import_module(module_path)
        attr = getattr(module, attr_name)
        globals()[name] = attr
        return attr
    raise AttributeError(f"module 'hydromodpy' has no attribute {name!r}")


__all__ = [
    # Entry points
    "open",
    "run",
    "calibrate",
    "catalog",
    "overview",
    "batch",
    "compare_pair",
    "compare_methods",
    "mesh",
    "testbed",
    "report",
    "bootstrap_proj",
    "doctor",
    # Core infrastructure
    "Workspace",
    "WorkspaceConfig",
    "HydroModPyConfig",
    # Spatial / physics
    "CatchmentDelineation",
    "GeographicConfig",
    "HydroMesh",
    "DomainConfig",
    "Subbasin",
    "FlowConfig",
    "FlowProcess",
    "TransportConfig",
    "TransportProcess",
    # Solvers
    "ModflowNwt",
    "Modflow6",
    "Modpath",
    "Mt3dms",
    "Boussinesq",
    # Project / run / catalog API
    "Project",
    "Run",
    "SimulationConfig",
    "SimulationPlan",
    "SimulationCatalog",
    "CatalogIndex",
    "SimulationGroup",
    # Data variables
    "DataManagersConfig",
    "DemConfig",
    "GeologyConfig",
    "HydrometryConfig",
    "PiezometryConfig",
    "RechargeConfig",
    "HydrographyConfig",
    "HydrographyManager",
    "HydrographyResult",
    "IntermittencyConfig",
    "IntermittencyManager",
    "OceanicConfig",
    "OceanicManager",
    # Sub-modules
    "analysis",
    "calibration",
    "core",
    "data",
    "master_config",
    "physics",
    "results",
    "simulation",
    "solver",
    "spatial",
    # Misc
    "log_manager",
    "__version__",
]
