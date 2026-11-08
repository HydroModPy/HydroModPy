"""Bootstrap helper that resolves HydroModPyConfig forward references.

Lives at the top level so ``config/`` stays decoupled from sibling
layers at module-load time: configs from ``model/``, ``solver/``,
``catchment/``, ``data/``, ``display/``, ``calibration/``,
and ``workflow/`` are imported here, never from
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
    from hydromodpy.calibration.config import CalibrationConfig
    from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
    from hydromodpy.config import hydromodpy_config as cfg_module
    from hydromodpy.data import DataManagersConfig
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.overview.config import OverviewConfig
    from hydromodpy.model.domain.domain_config import DomainConfig
    from hydromodpy.model.flow_config import FlowConfig
    from hydromodpy.model.transport.transport_config import TransportConfig
    from hydromodpy.solver.base.simulation_config import SimulationConfig
    from hydromodpy.solver.base.solver_config import SolverConfig

    refs = {
        "CalibrationConfig": CalibrationConfig,
        "DataManagersConfig": DataManagersConfig,
        "DisplayConfig": DisplayConfig,
        "FlowConfig": FlowConfig,
        "TransportConfig": TransportConfig,
        "SimulationConfig": SimulationConfig,
        "SolverConfig": SolverConfig,
        "DomainConfig": DomainConfig,
        "GeographicConfig": GeographicConfig,
        "OverviewConfig": OverviewConfig,
    }
    cfg_module.__dict__.update(refs)
    cfg_module.HydroModPyConfig.model_rebuild(force=True)


def _register_physics_contracts() -> None:
    """Wire the field-param factory and the field aggregator into ``model.contracts``.

    The model annotates its inputs through ``FieldParamLike`` and resolves
    field-param payloads and spatial means through these registered hooks.
    """
    from hydromodpy.model import contracts
    from hydromodpy.model.forcing.cells import spatial_mean_from_fields
    from hydromodpy.model.properties.field_param import FieldParam

    contracts.register_field_param_factory(FieldParam.from_dict)
    contracts.register_field_aggregator(spatial_mean_from_fields)


def _register_spatial_contracts() -> None:
    """Wire data-layer sources into the catchment ``protocols`` registry.

    Catchment, mesh and model code resolve geology IO through ``GeologyDataSource``
    so they never import the data package at module load time.
    """
    from hydromodpy.catchment import protocols
    from hydromodpy.data.variables.geology.io import default_geology_data_source

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


def _register_rerun_provider() -> None:
    """Wire the Project-backed rerun provider used by ``catalog.rerun``."""
    from hydromodpy.project.dispatch.rerun import ProjectRerunProvider
    from hydromodpy.results.run.rerun_contract import register_rerun_provider

    register_rerun_provider(ProjectRerunProvider())


def _register_root_config_contracts() -> None:
    """Wire HydroModPyConfig into the core config_kit registry.

    The 19-layer matrix forbids ``core -> config``. The
    config_kit registry, JSON Schema exporter and other downstream layers
    (results, schema) reach the root model through the
    ``RootConfigProvider`` Protocol declared in
    :mod:`hydromodpy.core.config_kit.root_config_protocol`.
    """
    from collections.abc import Sequence
    from pathlib import Path
    from typing import Any

    from hydromodpy.config.config_migration import (
        migrate_layers,
        migrate_merged_doc,
        migrate_sealed_config_doc,
    )
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.core.config_kit import root_config_protocol

    class _RootConfigProvider:
        def root_model(self) -> type[HydroModPyConfig]:
            return HydroModPyConfig

        def from_toml(self, toml_path: str | Path) -> HydroModPyConfig:
            return HydroModPyConfig.from_toml(toml_path)

        def from_json(self, payload: str | bytes) -> HydroModPyConfig:
            return HydroModPyConfig.from_json(payload)

        def from_dict(self, payload: dict[str, Any], *, sealed: bool = False) -> HydroModPyConfig:
            return HydroModPyConfig.from_dict(payload, sealed=sealed)

        def migrate_layers(self, layers: Sequence[tuple[str | Path | None, Any]]) -> list[str]:
            return migrate_layers(layers)

        def migrate_merged(
            self, document: dict[str, Any], layers: Sequence[tuple[str | Path | None, Any]]
        ) -> list[str]:
            return migrate_merged_doc(document, layers)

        def migrate_sealed(self, document: dict[str, Any]) -> list[str]:
            return migrate_sealed_config_doc(document)

    root_config_protocol.set_root_config_provider(_RootConfigProvider())


def _register_dynamic_flow_examples_contract() -> None:
    """Wire dynamic-flow TOML examples into the core toml_io generator.

    The 19-layer matrix forbids ``core -> model`` and
    ``core -> catchment``. The TOML generator delegates the rendering of
    dynamic ``[flow.param.*]``, ``[flow.bc.*]`` and ``[flow.sinks_sources.*]``
    example blocks to the provider declared in
    :mod:`hydromodpy.core.toml_io.dynamic_examples_protocol`.
    """
    from hydromodpy.core.toml_io import dynamic_examples_protocol
    from hydromodpy.model.toml_examples import DynamicFlowExamples

    dynamic_examples_protocol.set_dynamic_flow_examples_provider(DynamicFlowExamples())


_BOOTSTRAP_HOOKS: tuple[Callable[[], None], ...] = (
    _register_physics_contracts,
    _register_spatial_contracts,
    _register_calibration_contracts,
    _register_rerun_provider,
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
    from hydromodpy.core.runtime.bootstrap_hook import set_bootstrap_hook

    set_bootstrap_hook(bootstrap)


_register_bootstrap_hook()
