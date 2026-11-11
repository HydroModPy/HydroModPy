"""Lazy-import maps for the top-level ``hydromodpy`` package facade.

Kept separate from ``__init__.py`` so the package init stays minimal.
"""

from __future__ import annotations

from dataclasses import dataclass

from hydromodpy.core.exceptions import __all__ as _CORE_EXCEPTIONS
from hydromodpy.core.old_members import OLD_MEMBERS
from hydromodpy.results.errors import __all__ as _RESULT_EXCEPTIONS


@dataclass(frozen=True, slots=True)
class OldName:
    """A name of ``hydromodpy.__all__`` that moved."""

    new: str
    """What replaces it: a name of ``hydromodpy.__all__``, or the path of a refused name."""
    since: str
    """The version that moved it. It leaves this table two minor versions later."""
    refused: bool = False
    """It left before the first stable version, so it has no alias: it is refused, with
    ``new`` in the message. An entry that is not refused warns and forwards."""


_LEFT_BEFORE_2_0: dict[str, str] = {
    "BdtopoCrossingsSource": "hydromodpy.data.variables.crossings.config.BdtopoCrossingsSource",
    "Boussinesq": "hydromodpy.solver.boussinesq.boussinesq.Boussinesq",
    "BrgmGeology1mSource": "hydromodpy.data.variables.geology.config.BrgmGeology1mSource",
    "BrgmGeology50kSource": "hydromodpy.data.variables.geology.config.BrgmGeology50kSource",
    "CatchmentDelineation": "hydromodpy.catchment.preprocess.catchment_delineation.CatchmentDelineation",
    "CrossingsConfig": "hydromodpy.data.variables.crossings.config.CrossingsConfig",
    "CustomCrossingsSource": "hydromodpy.data.variables.crossings.config.FileCrossingsSource",
    "CustomDemSource": "hydromodpy.data.variables.dem.config.FileDemSource",
    "CustomGeologySource": "hydromodpy.data.variables.geology.config.FileGeologySource",
    "CustomLakeAbacusSource": "hydromodpy.data.variables.lake_abacus.config.FileLakeAbacusSource",
    "CustomLakeBathymetrySource": "hydromodpy.data.variables.lake_bathymetry.config.FileLakeBathymetrySource",
    "CustomLakeGeometrySource": "hydromodpy.data.variables.lake_geometry.config.FileLakeGeometrySource",
    "CustomLayerBaseSource": "hydromodpy.data.variables.layer_base.config.FileLayerBaseSource",
    "CustomSoilCapacitySource": "hydromodpy.data.variables.soil_capacity.config.FileSoilCapacitySource",
    "CustomSubstratumSource": "hydromodpy.data.variables.substratum.config.FileSubstratumSource",
    "DataManagersConfig": "hydromodpy.data.DataManagersConfig",
    "DemConfig": "hydromodpy.data.variables.dem.config.DemConfig",
    "DirichletBC": "hydromodpy.model.boundaries.boundary_conditions.DirichletBC",
    "DisplayConfig": "hydromodpy.display.config.DisplayConfig",
    "DomainConfig": "hydromodpy.model.domain.domain_config.DomainConfig",
    "DrainBC": "hydromodpy.model.boundaries.boundary_conditions.DrainBC",
    "EtpConfig": "hydromodpy.data.variables.etp.config.EtpConfig",
    "EtpSourceConfig": "hydromodpy.data.variables.etp.config.EtpSourceConfig",
    "FlowConfig": "hydromodpy.model.flow_config.FlowConfig",
    "FlowProcess": "hydromodpy.model.flow.Flow",
    "FlowProcessConfig": "hydromodpy.solver.base.simulation_config.FlowProcessConfig",
    "GeographicConfig": "hydromodpy.catchment.preprocess.geographic_config.GeographicConfig",
    "GeologyConfig": "hydromodpy.data.variables.geology.config.GeologyConfig",
    "HumidityConfig": "hydromodpy.data.variables.humidity.config.HumidityConfig",
    "HumiditySourceConfig": "hydromodpy.data.variables.humidity.config.HumiditySourceConfig",
    "HydroMesh": "hydromodpy.mesh.planar.hydro_mesh.HydroMesh",
    "HydrographyConfig": "hydromodpy.data.variables.hydrography.config.HydrographyConfig",
    "HydrographyManager": "hydromodpy.data.variables.hydrography.variable.HydrographyVariable",
    "HydrographySourceConfig": "hydromodpy.data.variables.hydrography.config.HydrographySourceConfig",
    "HydrometryConfig": "hydromodpy.data.variables.hydrometry.config.HydrometryConfig",
    "HydrometrySourceConfig": "hydromodpy.data.variables.hydrometry.config.HydrometrySourceConfig",
    "IgnGeoplateformeDemSource": "hydromodpy.data.variables.dem.config.IgnGeoplateformeDemSource",
    "IntermittencyConfig": "hydromodpy.data.variables.intermittency.config.IntermittencyConfig",
    "IntermittencyManager": "hydromodpy.data.variables.intermittency.variable.IntermittencyVariable",
    "IntermittencySourceConfig": "hydromodpy.data.variables.intermittency.config.IntermittencySourceConfig",
    "LakeAbacusConfig": "hydromodpy.data.variables.lake_abacus.config.LakeAbacusConfig",
    "LakeBathymetryConfig": "hydromodpy.data.variables.lake_bathymetry.config.LakeBathymetryConfig",
    "LakeGeometryConfig": "hydromodpy.data.variables.lake_geometry.config.LakeGeometryConfig",
    "LakeInflowConfig": "hydromodpy.data.variables.lake_inflow.config.LakeInflowConfig",
    "LakeInflowSourceConfig": "hydromodpy.data.variables.lake_inflow.config.LakeInflowSourceConfig",
    "LakeLevelsConfig": "hydromodpy.data.variables.lake_levels.config.LakeLevelsConfig",
    "LakeLevelsSourceConfig": "hydromodpy.data.variables.lake_levels.config.LakeLevelsSourceConfig",
    "LakeOutflowConfig": "hydromodpy.data.variables.lake_outflow.config.LakeOutflowConfig",
    "LakeOutflowSourceConfig": "hydromodpy.data.variables.lake_outflow.config.LakeOutflowSourceConfig",
    "LakeWithdrawalConfig": "hydromodpy.data.variables.lake_withdrawal.config.LakeWithdrawalConfig",
    "LakeWithdrawalSourceConfig": "hydromodpy.data.variables.lake_withdrawal.config.LakeWithdrawalSourceConfig",
    "LayerBaseConfig": "hydromodpy.data.variables.layer_base.config.LayerBaseConfig",
    "MeshProcessConfig": "hydromodpy.solver.base.simulation_config.MeshProcessConfig",
    "Modflow6": "hydromodpy.solver.modflow6.modflow6.Modflow6",
    "ModflowNwt": "hydromodpy.solver.modflow_nwt.ModflowNwt",
    "Modpath": "hydromodpy.solver.modflow_nwt.Modpath",
    "Mt3dms": "hydromodpy.solver.modflow_nwt.Mt3dms",
    "OceanicConfig": "hydromodpy.data.variables.oceanic.config.OceanicConfig",
    "OceanicManager": "hydromodpy.data.variables.oceanic.variable.OceanicVariable",
    "OceanicSourceConfig": "hydromodpy.data.variables.oceanic.config.OceanicSourceConfig",
    "PiezometryConfig": "hydromodpy.data.variables.piezometry.config.PiezometryConfig",
    "PiezometrySourceConfig": "hydromodpy.data.variables.piezometry.config.PiezometrySourceConfig",
    "PrecipitationConfig": "hydromodpy.data.variables.precipitation.config.PrecipitationConfig",
    "PrecipitationSourceConfig": "hydromodpy.data.variables.precipitation.config.PrecipitationSourceConfig",
    "RadiationConfig": "hydromodpy.data.variables.radiation.config.RadiationConfig",
    "RadiationSourceConfig": "hydromodpy.data.variables.radiation.config.RadiationSourceConfig",
    "RechargeConfig": "hydromodpy.data.variables.recharge.config.RechargeConfig",
    "RechargeSourceConfig": "hydromodpy.data.variables.recharge.config.RechargeSourceConfig",
    "RoeCrossingsSource": "hydromodpy.data.variables.crossings.config.RoeCrossingsSource",
    "RunoffConfig": "hydromodpy.data.variables.runoff.config.RunoffConfig",
    "RunoffSourceConfig": "hydromodpy.data.variables.runoff.config.RunoffSourceConfig",
    "SimulationConfig": "hydromodpy.solver.base.simulation_config.SimulationConfig",
    "SimulationPlan": "hydromodpy.solver.base.plan.SimulationPlan",
    "SimulationProcessConfig": "hydromodpy.solver.base.simulation_config.SimulationProcessConfig",
    "SimulationTimeConfig": "hydromodpy.solver.base.simulation_config.SimulationTimeConfig",
    "SoilCapacityConfig": "hydromodpy.data.variables.soil_capacity.config.SoilCapacityConfig",
    "SoilMoistureConfig": "hydromodpy.data.variables.soil_moisture.config.SoilMoistureConfig",
    "SoilMoistureSourceConfig": "hydromodpy.data.variables.soil_moisture.config.SoilMoistureSourceConfig",
    "Subbasin": "hydromodpy.catchment.preprocess.subbasin.Subbasin",
    "SubstratumConfig": "hydromodpy.data.variables.substratum.config.SubstratumConfig",
    "TemperatureConfig": "hydromodpy.data.variables.temperature.config.TemperatureConfig",
    "TemperatureSourceConfig": "hydromodpy.data.variables.temperature.config.TemperatureSourceConfig",
    "TransportConfig": "hydromodpy.model.transport.transport_config.TransportConfig",
    "TransportProcess": "hydromodpy.model.transport.transport_config.TransportConfig",
    "TransportProcessConfig": "hydromodpy.solver.base.simulation_config.TransportProcessConfig",
    "WaterQualityConfig": "hydromodpy.data.variables.water_quality.config.WaterQualityConfig",
    "WaterQualitySourceConfig": "hydromodpy.data.variables.water_quality.config.WaterQualitySourceConfig",
    "WindConfig": "hydromodpy.data.variables.wind.config.WindConfig",
    "WindSourceConfig": "hydromodpy.data.variables.wind.config.WindSourceConfig",
    "WorkflowConfig": "hydromodpy.config.hydromodpy_config.WorkflowConfig",
    "WorkspaceConfig": "hydromodpy.core.workspace.WorkspaceConfig",
    "bootstrap_proj": "hydromodpy.core.io.proj_bootstrap.bootstrap_proj",
    "catalog": "hydromodpy.data.provenance.sidecars.scan",
    "log_manager": "hydromodpy.core.logging.LogManager",
    "viz": "hydromodpy.display.quicklook.viz",
}
"""The names the top level gave up before 2.0.0, with where they are now."""

EXCEPTIONS_BESIDE_THEIR_CODE: dict[str, str] = {
    "AmbiguousReferenceError": "hydromodpy.results.catalog.discovery",
    "ComparisonCaseError": "hydromodpy.project.compare",
    "ComparisonReferenceError": "hydromodpy.project.compare",
    "MixedWindowsError": "hydromodpy.results.run.sealed",
    "PointOutsideMeshError": "hydromodpy.results.run.point",
    "SimulationNotFoundError": "hydromodpy.results.catalog.discovery",
    "TimeSelectionError": "hydromodpy.core.time.selection",
    "UnrankedMetricError": "hydromodpy.results.catalog.constants",
}
"""What the verbs and the objects of the facade raise, defined outside the two error modules."""

KEPT_EXCEPTIONS: tuple[str, ...] = (
    "HydroModPyError",
    # The class each exit code of ``hmp`` is mapped from (``cli.helpers.exit_code_for``).
    "CommandUsageError",
    "NothingThereError",
    "WriteConflictError",
    "ConfigError",
    "ConfigMissingError",
    "DataError",
    "CalibrationError",
    "FailedCasesError",
    "JobUsageError",
    "CapabilityVersionMismatchError",
    "SchemaVersionMismatchError",
    "ImportConflictError",
    "ReadOnlyError",
    "SolverError",
    "TerrainError",
    "CrossProjectsError",
    "BackupFailedError",
    "MigrationFailedError",
    "CatalogUnreadableError",
    "StepError",
    "AmbiguousReferenceError",
    "SimulationNotFoundError",
    # The other categories of the hierarchy.
    "MeshError",
    "PipelineError",
    "DisplayError",
    "StorageError",
    "CatalogError",
    "ResultsError",
    # What a verb of the facade documents as raised, named by path in its docstring.
    "RunNotSealedError",
    "FieldNotFoundError",
    "ComparisonCaseError",
    "ComparisonReferenceError",
    # What the facade raises for a name that left.
    "OldNameError",
)
"""The exceptions ``hydromodpy.__all__`` holds: the categories of the hierarchy.

A leaf stays importable from where it is defined (``hydromodpy.core.exceptions``,
``hydromodpy.results.errors`` or its own module) and is not frozen at the top level.
"""

_EXCEPTION_HOMES: dict[str, str] = {
    **dict.fromkeys(_CORE_EXCEPTIONS, "hydromodpy.core.exceptions"),
    **dict.fromkeys(_RESULT_EXCEPTIONS, "hydromodpy.results.errors"),
    **EXCEPTIONS_BESIDE_THEIR_CODE,
}
"""The module that defines each exception."""

_LEAF_EXCEPTIONS: dict[str, str] = {
    name: f"{home}.{name}" for name, home in _EXCEPTION_HOMES.items() if name not in KEPT_EXCEPTIONS
}

# The public modules retired in 2.1.0, with what answers in their place. The fetch
# rework retired the first three, the data cache lost its database, and the module of
# each data variable is variable.py.
_REFUSED_IN_2_1_0: dict[str, str] = {
    "hydromodpy.core.io.http_client": "hydromodpy.core.io.fetch",
    "hydromodpy.core.io.pinned_download": "hydromodpy.core.io.fetch",
    "hydromodpy.data.workspace.custom_scan": "hydromodpy.data.source.file",
    "hydromodpy.core.contracts.data_cache_backend": "hydromodpy.data.provenance.sidecars",
    "hydromodpy.data.registry": "hydromodpy.data.provenance.sidecars",
    "hydromodpy.data.registry.backend": "hydromodpy.data.provenance.sidecars",
    "hydromodpy.data.registry.cache_lifecycle": "hydromodpy.data.provenance.sidecars",
    "hydromodpy.data.registry.cache_queries": "hydromodpy.data.provenance.sidecars",
    "hydromodpy.data.registry.cache_store": "hydromodpy.data.provenance.sidecars",
    "hydromodpy.data.registry.catalog_duckdb": "hydromodpy.data.provenance.sidecars",
    "hydromodpy.data.registry.constants": "hydromodpy.data.provenance.sidecars",
    "hydromodpy.data.registry.input_cache": "hydromodpy.data.provenance.sidecars",
    "hydromodpy.data.registry.freeze": "hydromodpy.data.provenance.lockfile",
    "hydromodpy.data.variables.crossings.manager": "hydromodpy.data.variables.crossings.variable",
    "hydromodpy.data.variables.dem.manager": "hydromodpy.data.variables.dem.variable",
    "hydromodpy.data.variables.etp.manager": "hydromodpy.data.variables.etp.variable",
    "hydromodpy.data.variables.geology.manager": "hydromodpy.data.variables.geology.variable",
    "hydromodpy.data.variables.humidity.manager": "hydromodpy.data.variables.humidity.variable",
    "hydromodpy.data.variables.hydrography.manager": "hydromodpy.data.variables.hydrography.variable",
    "hydromodpy.data.variables.hydrometry.manager": "hydromodpy.data.variables.hydrometry.variable",
    "hydromodpy.data.variables.intermittency.manager": "hydromodpy.data.variables.intermittency.variable",
    "hydromodpy.data.variables.lake_abacus.manager": "hydromodpy.data.variables.lake_abacus.variable",
    "hydromodpy.data.variables.lake_bathymetry.manager": "hydromodpy.data.variables.lake_bathymetry.variable",
    "hydromodpy.data.variables.lake_geometry.manager": "hydromodpy.data.variables.lake_geometry.variable",
    "hydromodpy.data.variables.lake_inflow.manager": "hydromodpy.data.variables.lake_inflow.variable",
    "hydromodpy.data.variables.lake_levels.manager": "hydromodpy.data.variables.lake_levels.variable",
    "hydromodpy.data.variables.lake_outflow.manager": "hydromodpy.data.variables.lake_outflow.variable",
    "hydromodpy.data.variables.lake_withdrawal.manager": "hydromodpy.data.variables.lake_withdrawal.variable",
    "hydromodpy.data.variables.layer_base.manager": "hydromodpy.data.variables.layer_base.variable",
    "hydromodpy.data.variables.oceanic.manager": "hydromodpy.data.variables.oceanic.variable",
    "hydromodpy.data.variables.piezometry.manager": "hydromodpy.data.variables.piezometry.variable",
    "hydromodpy.data.variables.precipitation.manager": "hydromodpy.data.variables.precipitation.variable",
    "hydromodpy.data.variables.radiation.manager": "hydromodpy.data.variables.radiation.variable",
    "hydromodpy.data.variables.recharge.manager": "hydromodpy.data.variables.recharge.variable",
    "hydromodpy.data.variables.runoff.manager": "hydromodpy.data.variables.runoff.variable",
    "hydromodpy.data.variables.soil_capacity.manager": "hydromodpy.data.variables.soil_capacity.variable",
    "hydromodpy.data.variables.soil_moisture.manager": "hydromodpy.data.variables.soil_moisture.variable",
    "hydromodpy.data.variables.substratum.manager": "hydromodpy.data.variables.substratum.variable",
    "hydromodpy.data.variables.temperature.manager": "hydromodpy.data.variables.temperature.variable",
    "hydromodpy.data.variables.water_quality.manager": "hydromodpy.data.variables.water_quality.variable",
    "hydromodpy.data.variables.wind.manager": "hydromodpy.data.variables.wind.variable",
    "hydromodpy.project.lock": "hydromodpy.project.data_cache",
    # A report reads a sealed run: one engine writes every page, project/report.py
    # assembles the texts and the pages.
    "hydromodpy.display.calibration_report": "hydromodpy.project.report",
    "hydromodpy.display.catchment_report": "hydromodpy.project.report",
    "hydromodpy.display.catchment_report.artifacts": "hydromodpy.display.report.pages",
    "hydromodpy.display.catchment_report.blocks": "hydromodpy.display.report.pages",
    "hydromodpy.display.catchment_report.builder": "hydromodpy.display.report.pages",
    "hydromodpy.display.catchment_report.context": "hydromodpy.display.report.pages",
    "hydromodpy.display.catchment_report.inputs": "hydromodpy.display.report.pages",
    "hydromodpy.display.catchment_report.pipeline": "hydromodpy.project.report",
    "hydromodpy.display.catchment_report.settings": "hydromodpy.display.report.presets",
    "hydromodpy.display.catchment_report.simulation_source": "hydromodpy.display.report.pages",
    "hydromodpy.display.overview.web": "hydromodpy.display.report.pages",
    "hydromodpy.display.report_blocks": "hydromodpy.display.report.engine",
    "hydromodpy.workflow.steps.calibration": "hydromodpy.project.report",
}

OLD_NAMES: dict[str, OldName] = {
    name: OldName(path, "2.0.0", refused=True)
    for name, path in {**_LEFT_BEFORE_2_0, **OLD_MEMBERS, **_LEAF_EXCEPTIONS}.items()
}
OLD_NAMES.update(
    {name: OldName(path, "2.1.0", refused=True) for name, path in _REFUSED_IN_2_1_0.items()}
)
"""The old names ``hydromodpy.__getattr__`` answers: it refuses them or forwards them.

A dotted name is a member of a public object, and that object refuses it. At 2.0.0 this
table only holds the names refused because they left before that version. From
then on ``tools/surface_snapshot.py`` refuses a name that leaves ``__all__`` without an
entry here, and a test fails once an entry outlives its delay. The policy is
``docs/source/about/versions.md``.
"""

MODULE_EXPORTS: dict[str, str] = {
    "calibration": "hydromodpy.calibration",
    "config": "hydromodpy.config",
    "core": "hydromodpy.core",
    "data": "hydromodpy.data",
    "results": "hydromodpy.results",
    "solver": "hydromodpy.solver",
    "workflow": "hydromodpy.workflow",
}
"""The packages ``hmp.<name>`` opens without an import. They are out of ``__all__`` and out
of the contract, so a script that reads ``hmp.results`` does not depend on what was imported
before it."""

LAZY_IMPORTS: dict[str, str] = {
    "check": "hydromodpy.project.api",
    "stop": "hydromodpy.project.api",
    "Project": "hydromodpy.project",
    "Run": "hydromodpy.results.run",
    "RunSet": "hydromodpy.results.run.group",
    "Catalog": "hydromodpy.results.catalog",
    "Session": "hydromodpy.results.session.view",
    "Workspace": "hydromodpy.project.accessors",
    "HydroModPyConfig": "hydromodpy.config.hydromodpy_config",
    **{name: _EXCEPTION_HOMES[name] for name in KEPT_EXCEPTIONS},
}
