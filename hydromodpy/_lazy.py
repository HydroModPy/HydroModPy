"""Lazy-import maps for the top-level ``hydromodpy`` package facade.

Kept separate from ``__init__.py`` so the package init stays minimal.
"""

from __future__ import annotations

MODULE_EXPORTS: dict[str, str] = {
    "analysis": "hydromodpy.analysis",
    "calibration": "hydromodpy.calibration",
    "config": "hydromodpy.config",
    "core": "hydromodpy.core",
    "data": "hydromodpy.data",
    "physics": "hydromodpy.physics",
    "results": "hydromodpy.results",
    "simulation": "hydromodpy.simulation",
    "solver": "hydromodpy.solver",
    "spatial": "hydromodpy.spatial",
    "viz": "hydromodpy.display.viz",
    "workflow": "hydromodpy.workflow",
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
    # Flow boundary conditions
    "DirichletBC": "hydromodpy.physics.flow.boundary_conditions",
    "CauchyBC": "hydromodpy.physics.flow.boundary_conditions",
    "RobinBC": "hydromodpy.physics.flow.boundary_conditions",
    # Solvers
    "ModflowNwt": "hydromodpy.solver.modflow_nwt",
    "Modflow6": "hydromodpy.solver.modflow6.modflow6",
    "Modpath": "hydromodpy.solver.modflow_nwt",
    "Mt3dms": "hydromodpy.solver.modflow_nwt",
    "Boussinesq": "hydromodpy.solver.boussinesq.boussinesq",
    # Core infrastructure
    "Workspace": "hydromodpy.core.workspace",
    "WorkspaceConfig": "hydromodpy.core.workspace",
    "HydroModPyConfig": "hydromodpy.config.hydromodpy_config",
    "WorkflowConfig": "hydromodpy.config.hydromodpy_config",
    # Simulation orchestration
    "SimulationConfig": "hydromodpy.simulation.planning.config",
    "SimulationTimeConfig": "hydromodpy.simulation.planning.config",
    "SimulationProcessConfig": "hydromodpy.simulation.planning.config",
    "FlowProcessConfig": "hydromodpy.simulation.planning.config",
    "TransportProcessConfig": "hydromodpy.simulation.planning.config",
    "MeshProcessConfig": "hydromodpy.simulation.planning.config",
    # Display
    "DisplayConfig": "hydromodpy.display.config",
    # Data variables (public surface)
    "DataManagersConfig": "hydromodpy.data.data_managers_config",
    "DemConfig": "hydromodpy.data.variables.dem.config",
    "CustomDemSource": "hydromodpy.data.variables.dem.config",
    "IgnBdaltiDemSource": "hydromodpy.data.variables.dem.config",
    "GeologyConfig": "hydromodpy.data.variables.geology.config",
    "CustomGeologySource": "hydromodpy.data.variables.geology.config",
    "BrgmGeology1mSource": "hydromodpy.data.variables.geology.config",
    "BrgmGeology50kSource": "hydromodpy.data.variables.geology.config",
    "HydrographyConfig": "hydromodpy.data.variables.hydrography.config",
    "HydrographySourceConfig": "hydromodpy.data.variables.hydrography.config",
    "HydrographyManager": "hydromodpy.data.variables.hydrography.manager",
    "HydrometryConfig": "hydromodpy.data.variables.hydrometry.config",
    "HydrometrySourceConfig": "hydromodpy.data.variables.hydrometry.config",
    "PiezometryConfig": "hydromodpy.data.variables.piezometry.config",
    "PiezometrySourceConfig": "hydromodpy.data.variables.piezometry.config",
    "IntermittencyConfig": "hydromodpy.data.variables.intermittency.config",
    "IntermittencySourceConfig": "hydromodpy.data.variables.intermittency.config",
    "IntermittencyManager": "hydromodpy.data.variables.intermittency.manager",
    "OceanicConfig": "hydromodpy.data.variables.oceanic",
    "OceanicSourceConfig": "hydromodpy.data.variables.oceanic.config",
    "OceanicManager": "hydromodpy.data.variables.oceanic",
    "RechargeConfig": "hydromodpy.data.variables.recharge.config",
    "RechargeSourceConfig": "hydromodpy.data.variables.recharge.config",
    "RunoffConfig": "hydromodpy.data.variables.runoff.config",
    "RunoffSourceConfig": "hydromodpy.data.variables.runoff.config",
    "EtpConfig": "hydromodpy.data.variables.etp.config",
    "EtpSourceConfig": "hydromodpy.data.variables.etp.config",
    "PrecipitationConfig": "hydromodpy.data.variables.precipitation.config",
    "PrecipitationSourceConfig": "hydromodpy.data.variables.precipitation.config",
    "TemperatureConfig": "hydromodpy.data.variables.temperature.config",
    "TemperatureSourceConfig": "hydromodpy.data.variables.temperature.config",
    "HumidityConfig": "hydromodpy.data.variables.humidity.config",
    "HumiditySourceConfig": "hydromodpy.data.variables.humidity.config",
    "WindConfig": "hydromodpy.data.variables.wind.config",
    "WindSourceConfig": "hydromodpy.data.variables.wind.config",
    "RadiationConfig": "hydromodpy.data.variables.radiation.config",
    "RadiationSourceConfig": "hydromodpy.data.variables.radiation.config",
    "SoilMoistureConfig": "hydromodpy.data.variables.soil_moisture.config",
    "SoilMoistureSourceConfig": "hydromodpy.data.variables.soil_moisture.config",
    "WaterQualityConfig": "hydromodpy.data.variables.water_quality.config",
    "WaterQualitySourceConfig": "hydromodpy.data.variables.water_quality.config",
    # Project / run API (programmatic facade)
    "Project": "hydromodpy.project",
    "SimulationPlan": "hydromodpy.simulation.planning.plan",
    # Catalog API
    "SimulationCatalog": "hydromodpy.results.catalog",
    "SimulationGroup": "hydromodpy.results.simulation_group",
    "Run": "hydromodpy.results.run",
}
