"""Bootstrap helper that resolves HydroModPyConfig forward references.

Lives at the top level so ``master_config/`` stays decoupled from sibling
layers at module-load time: configs from ``physics/``, ``solver/``,
``spatial/``, ``data/``, ``simulation/``, ``display/``, ``analysis/``,
``calibration/``, and ``workflow/`` are imported here, never from
``master_config/``.
"""

from __future__ import annotations

_BOOTSTRAPPED = False


def _rebuild_forward_refs() -> None:
    """Inject sibling configs into ``hydromodpy_config`` and rebuild the model.

    Pydantic resolves forward references at ``model_rebuild()`` time by name
    lookup against the defining module's globals, so the sibling classes are
    written into ``hydromodpy.master_config.hydromodpy_config.__dict__``.
    """
    from hydromodpy.analysis.batch.config import RegionalLabConfig
    from hydromodpy.analysis.capability_gallery import CapabilityGalleryConfig
    from hydromodpy.analysis.comparison.config import MethodComparisonSection
    from hydromodpy.calibration.config import CalibrationConfig
    from hydromodpy.data.data_managers_config import DataManagersConfig
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.overview.config import OverviewSection
    from hydromodpy.master_config import analysis as analysis_module
    from hydromodpy.master_config import hydromodpy_config as cfg_module
    from hydromodpy.physics.flow.flow_config import FlowConfig
    from hydromodpy.physics.transport.transport_config import TransportConfig
    from hydromodpy.simulation.planning.config import SimulationConfig
    from hydromodpy.solver.base.solver_config import SolverConfig
    from hydromodpy.solver.modflow6.modflow6_config import Modflow6Config
    from hydromodpy.solver.modflow_nwt.nwt import ModflowConfig
    from hydromodpy.spatial.domain.domain_config import DomainConfig
    from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
    from hydromodpy.spatial.mesh.config import MeshCatchmentConfig

    analysis_module.__dict__.update(
        RegionalLabConfig=RegionalLabConfig,
        CapabilityGalleryConfig=CapabilityGalleryConfig,
        MethodComparisonSection=MethodComparisonSection,
    )
    analysis_module.AnalysisConfig.model_rebuild()
    cfg_module.__dict__.update(
        CalibrationConfig=CalibrationConfig,
        DataManagersConfig=DataManagersConfig,
        DisplayConfig=DisplayConfig,
        FlowConfig=FlowConfig,
        TransportConfig=TransportConfig,
        SimulationConfig=SimulationConfig,
        SolverConfig=SolverConfig,
        Modflow6Config=Modflow6Config,
        ModflowConfig=ModflowConfig,
        DomainConfig=DomainConfig,
        GeographicConfig=GeographicConfig,
        MeshCatchmentConfig=MeshCatchmentConfig,
        OverviewSection=OverviewSection,
    )
    cfg_module.HydroModPyConfig.model_rebuild()


def _register_physics_contracts() -> None:
    """Wire spatial-layer callables into the physics ``contracts`` registry.

    Physics annotates its inputs through ``FieldParamLike`` and resolves
    field-param payloads / spatial aggregations via these registered hooks
    so the physics package never imports the spatial package.
    """
    from hydromodpy.physics import contracts
    from hydromodpy.spatial.field.aggregation import (
        extract_homogeneous_series_from_fields,
    )
    from hydromodpy.spatial.field.core.field_param import FieldParam
    from hydromodpy.spatial.field.core.field_param_config import (
        resolve_field_param_config_payload,
        validate_resolved_field_param_data,
    )

    contracts.register_field_param_factory(FieldParam.from_dict)
    contracts.register_field_param_payload_resolver(resolve_field_param_config_payload)
    contracts.register_field_param_payload_validator(validate_resolved_field_param_data)
    contracts.register_field_aggregator(extract_homogeneous_series_from_fields)


def _register_spatial_contracts() -> None:
    """Wire data-layer sources into the spatial ``protocols`` registry.

    Spatial code resolves geology IO through ``GeologyDataSource`` so the
    spatial package never imports the data package at module load time.
    """
    from hydromodpy.data.variables.geology.io import default_geology_data_source
    from hydromodpy.spatial import protocols

    protocols.register_geology_data_source(default_geology_data_source())


def _register_calibration_contracts() -> None:
    """Wire workflow-layer callables into the calibration trial registry.

    Calibration runners resolve the pipeline driver, standard steps, and
    structural binders through ``TrialPipelineProvider`` so the
    calibration package never imports the workflow package.
    """
    from hydromodpy.workflow.steps.calibration import (
        register_default_trial_pipeline_provider,
    )

    register_default_trial_pipeline_provider()


def _register_analysis_contracts() -> None:
    """Wire the solver registry into analysis comparison helpers.

    Analysis cannot import the solver layer (cf. layer matrix), so the
    distributed flow solver lookup is injected here through the
    ``SolverRegistryProvider`` Protocol declared in
    :mod:`hydromodpy.analysis.comparison._solver_protocol`.
    """
    from hydromodpy.analysis.comparison import _solver_protocol
    from hydromodpy.solver.base import registry as _registry

    class _RegistryProvider:
        def distributed_flow_solver_sections(self) -> tuple[str, ...]:
            flow_solvers = {name for _, name in _registry.pairs_for_process("flow")}
            sections: list[str] = []
            for name in _registry.list_extractor_solvers():
                if name not in flow_solvers:
                    continue
                try:
                    extractor = _registry.get_extractor(name)
                except KeyError:
                    continue
                if getattr(extractor, "category", None) == "distributed":
                    sections.append(name)
            return tuple(sections)

    _solver_protocol.set_solver_registry_provider(_RegistryProvider())


def _register_simulation_contracts() -> None:
    """Wire the solver registry into simulation orchestration.

    Simulation must not import the solver layer (cf. layer matrix). The
    planner, runner, post-run hook and transport helpers reach the registry
    through the ``SolverRegistryProvider`` Protocol declared in
    :mod:`hydromodpy.simulation._solver_protocol`.
    """
    from hydromodpy.simulation import _solver_protocol as _sim_protocol
    from hydromodpy.solver.base import registry as _registry

    class _RegistryProvider:
        def known_process_types(self) -> set[str]:
            return _registry.known_process_types()

        def required_bindings(
            self, process_type: str, solver_name: str
        ) -> tuple[tuple[str, str], ...]:
            return _registry.required_bindings(process_type, solver_name)

        def get_solver_adapter(self, process_type: str, solver_name: str):
            return _registry.get_solver_adapter(process_type, solver_name)

        def get_solver_adapter_class(self, process_type: str, solver_name: str) -> type:
            return _registry.get(process_type, solver_name)

        def get_extractor_instance(self, solver_name: str):
            return _registry.get_extractor_instance(solver_name)

    _sim_protocol.set_solver_registry_provider(_RegistryProvider())


def _register_root_config_contracts() -> None:
    """Wire HydroModPyConfig into the core config_kit registry.

    The 14x14 layer matrix forbids ``core -> master_config``. The
    config_kit registry, JSON Schema exporter and other downstream layers
    (results, schema) reach the root model through the
    ``RootConfigProvider`` Protocol declared in
    :mod:`hydromodpy.core.config_kit.root_config_protocol`.
    """
    from pathlib import Path
    from typing import Any

    from hydromodpy.core.config_kit import root_config_protocol
    from hydromodpy.master_config.hydromodpy_config import HydroModPyConfig

    class _RootConfigProvider:
        def root_model(self) -> type[HydroModPyConfig]:
            return HydroModPyConfig

        def from_toml(self, toml_path: str | Path) -> HydroModPyConfig:
            return HydroModPyConfig.from_toml(toml_path)

        def from_json(self, payload: str | bytes) -> HydroModPyConfig:
            return HydroModPyConfig.from_json(payload)

        def from_dict(self, payload: dict[str, Any]) -> HydroModPyConfig:
            return HydroModPyConfig.from_dict(payload)

    root_config_protocol.set_root_config_provider(_RootConfigProvider())


def _register_dynamic_flow_examples_contract() -> None:
    """Wire dynamic-flow TOML examples into the core toml_io generator.

    The 14x14 layer matrix forbids ``core -> physics`` and
    ``core -> spatial``. The TOML generator delegates the rendering of
    dynamic ``[flow.param.*]``, ``[flow.bc.*]`` and ``[flow.sinks_sources.*]``
    example blocks to the provider declared in
    :mod:`hydromodpy.core.toml_io.dynamic_examples_protocol`.
    """
    from hydromodpy.core.toml_io import dynamic_examples_protocol
    from hydromodpy.master_config.dynamic_flow_examples import DynamicFlowExamples

    dynamic_examples_protocol.set_dynamic_flow_examples_provider(DynamicFlowExamples())


def bootstrap() -> None:
    """Resolve HydroModPyConfig forward references. Idempotent."""
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    _register_physics_contracts()
    _register_spatial_contracts()
    _register_calibration_contracts()
    _register_analysis_contracts()
    _register_simulation_contracts()
    _rebuild_forward_refs()
    _register_root_config_contracts()
    _register_dynamic_flow_examples_contract()
    _BOOTSTRAPPED = True
