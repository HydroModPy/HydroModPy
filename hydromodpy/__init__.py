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

log_manager = LogManager(mode="verbose", log_dir=None, overwrite=False)

_log_manager = LogManager(mode="verbose", log_dir=None, overwrite=False)
# Public access to log manager for users
log_manager = _log_manager

_MODULE_EXPORTS = {
    "analysis": "hydromodpy.analysis",
    "calibration": "hydromodpy.calibration",
    "core": "hydromodpy.core",
    "data": "hydromodpy.data",
    "physics": "hydromodpy.physics",
    "results": "hydromodpy.results",
    "simulation": "hydromodpy.simulation",
    "solver": "hydromodpy.solver",
    "spatial": "hydromodpy.spatial",
}

_LAZY_IMPORTS = {
    # Spatial / geographic
    "CatchmentDelineation": "hydromodpy.spatial.geographic.catchment_delineation",
    "GeographicConfig": "hydromodpy.spatial.geographic.geographic_config",
    "Geographic": "hydromodpy.spatial.geographic.geographic_config:GeographicConfig",
    "Subbasin": "hydromodpy.spatial.geographic.subbasin",
    "HydroMesh": "hydromodpy.spatial.mesh.hydro_mesh",
    "DomainConfig": "hydromodpy.spatial.domain.domain_config",
    "Domain": "hydromodpy.spatial.domain.domain_config:DomainConfig",
    # Processes (factories expose FlowConfig/TransportConfig)
    "FlowConfig": "hydromodpy.physics.flow.flow_config",
    "Flow": "hydromodpy.physics.flow.flow_config:FlowConfig",
    "FlowProcess": "hydromodpy.physics.flow.flow:Flow",
    "TransportConfig": "hydromodpy.physics.transport.transport_config",
    "Transport": "hydromodpy.physics.transport.transport_config:TransportConfig",
    "TransportProcess": "hydromodpy.physics.transport.transport:Transport",
    # Solvers
    "Modflow": "hydromodpy.solver.modflow_nwt",
    "Modflow6": "hydromodpy.solver.modflow6.modflow6",
    "Modpath": "hydromodpy.solver.modflow_nwt",
    "Modpath7": "hydromodpy.solver.modflow_nwt",
    "Mt3dms": "hydromodpy.solver.modflow_nwt",
    "Boussinesq": "hydromodpy.solver.boussinesq.boussinesq",
    # Core infrastructure
    "Workspace": "hydromodpy.core.workspace",
    "WorkspaceConfig": "hydromodpy.core.workspace",
    "HydroModPyConfig": "hydromodpy.config:HydroModPyConfig",
    "Config": "hydromodpy.config:HydroModPyConfig",
    # Simulation orchestration
    "SimulationConfig": "hydromodpy.simulation.planning.config",
    "Sim": "hydromodpy.simulation.planning.config:SimulationConfig",
    # Data variables (public surface)
    "DataManagersConfig": "hydromodpy.data.data_managers_config",
    "Data": "hydromodpy.data.data_managers_config:DataManagersConfig",
    "RechargeConfig": "hydromodpy.data.variables.recharge.config",
    "Recharge": "hydromodpy.data.variables.recharge.config:RechargeConfig",
    "HydrometryConfig": "hydromodpy.data.variables.hydrometry.config",
    "Hydrometry": "hydromodpy.data.variables.hydrometry.config:HydrometryConfig",
    "PiezometryConfig": "hydromodpy.data.variables.piezometry.config",
    "Piezometry": "hydromodpy.data.variables.piezometry.config:PiezometryConfig",
    "GeologyConfig": "hydromodpy.data.variables.geology.config",
    "Geology": "hydromodpy.data.variables.geology.config:GeologyConfig",
    "DemConfig": "hydromodpy.data.variables.dem.config",
    "DEM": "hydromodpy.data.variables.dem.config:DemConfig",
    "HydrographyConfig": "hydromodpy.data.variables.hydrography.config",
    "HydrographyManager": "hydromodpy.data.variables.hydrography.manager",
    "HydrographyResult": "hydromodpy.data.variables.hydrography.result",
    "IntermittencyConfig": "hydromodpy.data.variables.intermittency.config",
    "IntermittencyManager": "hydromodpy.data.variables.intermittency.manager",
    "OceanicConfig": "hydromodpy.data.variables.oceanic",
    "OceanicManager": "hydromodpy.data.variables.oceanic",
    # Project / run API (programmatic façade)
    "Project": "hydromodpy.project",
    "SimulationPlan": "hydromodpy.simulation.planning.plan",
    # Catalog API
    "Catalog": "hydromodpy.results.catalog:SimulationCatalog",
    "SimulationCatalog": "hydromodpy.results.catalog",
    "SimulationGroup": "hydromodpy.results.simulation_group",
    "Run": "hydromodpy.results.run",
}


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
