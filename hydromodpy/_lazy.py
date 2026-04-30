"""Lazy-import maps for the top-level ``hydromodpy`` package facade.

Kept separate from ``__init__.py`` so the package init stays minimal.
"""

from __future__ import annotations

MODULE_EXPORTS: dict[str, str] = {
    "analysis": "hydromodpy.analysis",
    "calibration": "hydromodpy.calibration",
    "core": "hydromodpy.core",
    "data": "hydromodpy.data",
    "master_config": "hydromodpy.master_config",
    "physics": "hydromodpy.physics",
    "results": "hydromodpy.results",
    "simulation": "hydromodpy.simulation",
    "solver": "hydromodpy.solver",
    "spatial": "hydromodpy.spatial",
}

LAZY_IMPORTS: dict[str, str] = {
    # Spatial / geographic
    "CatchmentDelineation": "hydromodpy.spatial.geographic.catchment_delineation",
    "GeographicConfig": "hydromodpy.spatial.geographic.geographic_config",
    "Subbasin": "hydromodpy.spatial.geographic.subbasin",
    "HydroMesh": "hydromodpy.spatial.mesh.hydro_mesh",
    "DomainConfig": "hydromodpy.spatial.domain.domain_config",
    # Processes (factories expose FlowConfig/TransportConfig)
    "FlowConfig": "hydromodpy.physics.flow.flow_config",
    "FlowProcess": "hydromodpy.physics.flow.flow:Flow",
    "TransportConfig": "hydromodpy.physics.transport.transport_config",
    "TransportProcess": "hydromodpy.physics.transport.transport:Transport",
    # Solvers
    "ModflowNwt": "hydromodpy.solver.modflow_nwt",
    "Modflow6": "hydromodpy.solver.modflow6.modflow6",
    "Modpath": "hydromodpy.solver.modflow_nwt",
    "Mt3dms": "hydromodpy.solver.modflow_nwt",
    "Boussinesq": "hydromodpy.solver.boussinesq.boussinesq",
    # Core infrastructure
    "Workspace": "hydromodpy.core.workspace",
    "WorkspaceConfig": "hydromodpy.core.workspace",
    "HydroModPyConfig": "hydromodpy.master_config.hydromodpy_config",
    # Simulation orchestration
    "SimulationConfig": "hydromodpy.simulation.planning.config",
    # Data variables (public surface)
    "DataManagersConfig": "hydromodpy.data.data_managers_config",
    "RechargeConfig": "hydromodpy.data.variables.recharge.config",
    "HydrometryConfig": "hydromodpy.data.variables.hydrometry.config",
    "PiezometryConfig": "hydromodpy.data.variables.piezometry.config",
    "GeologyConfig": "hydromodpy.data.variables.geology.config",
    "DemConfig": "hydromodpy.data.variables.dem.config",
    "HydrographyConfig": "hydromodpy.data.variables.hydrography.config",
    "HydrographyManager": "hydromodpy.data.variables.hydrography.manager",
    "HydrographyResult": "hydromodpy.data.variables.hydrography.result",
    "IntermittencyConfig": "hydromodpy.data.variables.intermittency.config",
    "IntermittencyManager": "hydromodpy.data.variables.intermittency.manager",
    "OceanicConfig": "hydromodpy.data.variables.oceanic",
    "OceanicManager": "hydromodpy.data.variables.oceanic",
    # Project / run API (programmatic facade)
    "Project": "hydromodpy.project",
    "SimulationPlan": "hydromodpy.simulation.planning.plan",
    # Catalog API
    "SimulationCatalog": "hydromodpy.results.catalog",
    "SimulationGroup": "hydromodpy.results.simulation_group",
    "Run": "hydromodpy.results.run",
}
