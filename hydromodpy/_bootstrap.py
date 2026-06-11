"""Bootstrap helper that resolves HydroModPyConfig forward references.

Lives at the top level so ``config/`` stays decoupled from sibling
layers at module-load time: configs from ``physics/``, ``solver/``,
``spatial/``, ``data/``, ``simulation/``, ``display/``, ``analysis/``,
``calibration/``, and ``workflow/`` are imported here, never from
``config/``.
"""

from __future__ import annotations

from collections.abc import Callable

_BOOTSTRAPPED = False
_IN_PROGRESS = False


def _rebuild_forward_refs() -> None:
    """Inject sibling configs into ``hydromodpy_config`` and rebuild the model.

    Pydantic resolves forward references at ``model_rebuild()`` time by name
    lookup against the defining module's globals, so the sibling classes are
    written into the canonical root-config module globals.
    """
    from hydromodpy.analysis import config as analysis_module
    from hydromodpy.analysis.capability_gallery import CapabilityGalleryConfig
    from hydromodpy.analysis.comparison.experiment_config import ComparisonSection
    from hydromodpy.analysis.testbed.regional_lab_config import RegionalLabConfig
    from hydromodpy.calibration.config import CalibrationConfig
    from hydromodpy.config import hydromodpy_config as cfg_module
    from hydromodpy.data.data_managers_config import DataManagersConfig
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.overview.config import OverviewConfig
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
        ComparisonSection=ComparisonSection,
    )
    analysis_module.AnalysisConfig.model_rebuild()
    refs = {
        "CalibrationConfig": CalibrationConfig,
        "DataManagersConfig": DataManagersConfig,
        "DisplayConfig": DisplayConfig,
        "FlowConfig": FlowConfig,
        "TransportConfig": TransportConfig,
        "SimulationConfig": SimulationConfig,
        "SolverConfig": SolverConfig,
        "Modflow6Config": Modflow6Config,
        "ModflowConfig": ModflowConfig,
        "DomainConfig": DomainConfig,
        "GeographicConfig": GeographicConfig,
        "MeshCatchmentConfig": MeshCatchmentConfig,
        "OverviewConfig": OverviewConfig,
        "RegionalLabConfig": RegionalLabConfig,
        "CapabilityGalleryConfig": CapabilityGalleryConfig,
        "ComparisonSection": ComparisonSection,
    }
    cfg_module.__dict__.update(refs)
    cfg_module.HydroModPyConfig.model_rebuild(force=True)


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
    from hydromodpy.calibration.runners.contracts import (
        register_trial_promotion_provider,
    )
    from hydromodpy.project.dispatch.calibration import ProjectTrialPromotionProvider
    from hydromodpy.workflow.steps.calibration import (
        register_default_trial_pipeline_provider,
    )

    register_default_trial_pipeline_provider()
    register_trial_promotion_provider(ProjectTrialPromotionProvider())


def _register_rerun_provider() -> None:
    """Wire the Project-backed rerun provider used by ``catalog.rerun``."""
    from hydromodpy.project.dispatch.rerun import ProjectRerunProvider
    from hydromodpy.results.rerun_contract import register_rerun_provider

    register_rerun_provider(ProjectRerunProvider())


def _register_solver_registry_provider() -> None:
    """Wire a single solver-registry provider for simulation and analysis.

    The 15x15 layer matrix forbids ``simulation -> solver`` and
    ``analysis -> solver``. Both consumers reach the registry through the
    ``SolverRegistryProvider`` Protocol declared in
    :mod:`hydromodpy.core.contracts.solver_registry`. The singleton lives
    in ``core`` so the two consumers share one provider instead of
    maintaining parallel module-level state.
    """
    from hydromodpy.core.contracts import solver_registry
    from hydromodpy.solver.base import registry as _registry

    class _RegistryProvider:
        def distributed_flow_solver_sections(self) -> tuple[str, ...]:
            flow_solvers = {name for _, name in _registry.pairs_for_process("flow")}
            sections: list[str] = []
            for process_type, name in _registry.list_extractor_pairs():
                if process_type != "flow" or name not in flow_solvers:
                    continue
                try:
                    extractor = _registry.get_extractor(process_type, name)
                except KeyError:
                    continue
                if getattr(extractor, "category", None) == "distributed":
                    sections.append(name)
            return tuple(sections)

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

        def get_extractor_instance(self, process_type: str, solver_name: str):
            return _registry.get_extractor_instance(process_type, solver_name)

    solver_registry.set_solver_registry_provider(_RegistryProvider())


def _register_analysis_contracts() -> None:
    """Wire testbed runner provider into the analysis layer.

    Testbed child workflow execution is injected through
    ``TestbedRunnerProvider`` so the analysis package never imports the
    workflow package.
    """
    from hydromodpy.analysis.testbed.contracts import register_testbed_runner_provider
    from hydromodpy.project.dispatch.workflow import ProjectTestbedRunnerProvider

    register_testbed_runner_provider(ProjectTestbedRunnerProvider())


def _register_root_config_contracts() -> None:
    """Wire HydroModPyConfig into the core config_kit registry.

    The 15x15 layer matrix forbids ``core -> config``. The
    config_kit registry, JSON Schema exporter and other downstream layers
    (results, schema) reach the root model through the
    ``RootConfigProvider`` Protocol declared in
    :mod:`hydromodpy.core.config_kit.root_config_protocol`.
    """
    from pathlib import Path
    from typing import Any

    from hydromodpy.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.core.config_kit import root_config_protocol

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

    The 15x15 layer matrix forbids ``core -> physics`` and
    ``core -> spatial``. The TOML generator delegates the rendering of
    dynamic ``[flow.param.*]``, ``[flow.bc.*]`` and ``[flow.sinks_sources.*]``
    example blocks to the provider declared in
    :mod:`hydromodpy.core.toml_io.dynamic_examples_protocol`.
    """
    from hydromodpy.config.dynamic_flow_examples import DynamicFlowExamples
    from hydromodpy.core.toml_io import dynamic_examples_protocol

    dynamic_examples_protocol.set_dynamic_flow_examples_provider(DynamicFlowExamples())


_BOOTSTRAP_HOOKS: tuple[Callable[[], None], ...] = (
    _register_physics_contracts,
    _register_spatial_contracts,
    _register_calibration_contracts,
    _register_rerun_provider,
    _register_solver_registry_provider,
    _register_analysis_contracts,
    _rebuild_forward_refs,
    _register_root_config_contracts,
    _register_dynamic_flow_examples_contract,
)


def bootstrap() -> None:
    """Resolve HydroModPyConfig forward references and wire DI contracts.

    Idempotent: subsequent calls short-circuit on ``_BOOTSTRAPPED``. The
    hook order is significant: ``_rebuild_forward_refs`` must precede the
    hooks that observe the fully rebuilt ``HydroModPyConfig``
    (``_register_root_config_contracts``,
    ``_register_dynamic_flow_examples_contract``).
    """
    global _BOOTSTRAPPED, _IN_PROGRESS
    if _BOOTSTRAPPED or _IN_PROGRESS:
        return
    _IN_PROGRESS = True
    try:
        for hook in _BOOTSTRAP_HOOKS:
            hook()
        _BOOTSTRAPPED = True
    finally:
        _IN_PROGRESS = False


def _register_bootstrap_hook() -> None:
    """Register :func:`bootstrap` as the lazy hook (called at module import)."""
    from hydromodpy.core.bootstrap_hook import set_bootstrap_hook

    set_bootstrap_hook(bootstrap)


_register_bootstrap_hook()
