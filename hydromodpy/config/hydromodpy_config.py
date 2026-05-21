"""Top-level Pydantic configuration object for HydroModPy.

Aggregates all sub-configs into a single hierarchical model.
Relative paths in the TOML are resolved against the TOML file location;
absolute paths are left as-is. Paths starting with ``~`` are expanded
to the user's home directory.

Usage::

    from hydromodpy.config import HydroModPyConfig

    cfg = HydroModPyConfig.from_toml(
        "examples/projects/03_canut_watershed/project.toml"
    )
    cfg.workspace.project_root
    cfg.geographic.catch_def
    cfg.geographic.dem_init_path
    cfg.domain.zone_ids
    cfg.data.geology.id
    cfg.flow.param["K"]
    cfg.modflownwt.process_specific.vka
"""

from __future__ import annotations

import copy
import json
import os
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationError, ValidationInfo, model_validator

from hydromodpy.analysis.config import AnalysisConfig
from hydromodpy.analysis.testbed.config import TestbedConfig
from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.config.toml_section_loader import (
    _deep_merge,
    _load_data_section,
    _load_flow_section,
    _load_optional_analysis_section,
    _load_optional_calibration_section,
    _load_optional_mesh_catchment_section,
    _load_optional_mesh_input_section,
    _load_optional_overview_section,
    _load_optional_testbed_section,
    _raw_declares_dem_source,
    _validation_context,
    load_geographic_section,
    load_standard_section,
)
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.introspect import (
    collect_profile_violations,
    resolve_profile,
)
from hydromodpy.core.config_kit.mesh_input import MeshInputConfig
from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.core.config_kit.profile import Profile, ProfileName
from hydromodpy.core.toml_io.error_locator import format_validation_error
from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.core.workspace.config import WorkspaceConfig
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

WorkflowMode = Literal[
    "simulation",
    "calibration",
    "overview",
    "comparison",
    "testbed",
]
ValidationContext = Literal["toml", "api"]


class WorkflowConfig(HydroModelBase):
    """Workflow selector configuration."""

    mode: Annotated[WorkflowMode, Profile.USER] = Field(
        ...,
        description="Workflow mode dispatched by `hmp run`.",
    )


def _derive_run_id_from_filename(toml_path: Path) -> str:
    """Derive a run_id from a TOML filename.

    ``run_steady_nwt.toml`` -> ``steady_nwt``
    ``config.toml`` -> ``config``
    """
    stem = toml_path.stem
    return re.sub(r"^run_", "", stem)


class HydroModPyConfig(HydroModelBase):
    """
    Top-level configuration for HydroModPy.

    Aggregates sub-components (workspace, geographic, domain, data, flow,
    transport, solver, modflownwt, modflow6, display)
    into a centralized,
    hierarchical model and validates optional flow parameters as
    `FieldParamConfig` dictionaries.
    """

    workflow: Annotated[WorkflowConfig, Profile.USER] = Field(
        description=(
            "Workflow configuration. `workflow.mode` must be one of "
            "'simulation', 'calibration', 'overview', "
            "'comparison', 'testbed'. "
            "Drives dispatch in `hmp run <toml>` and in API-driven callers "
            "that instantiate `HydroModPyConfig` from a frontend form."
        ),
        examples=[{"mode": "simulation"}],
    )
    workspace: Annotated[WorkspaceConfig, Profile.USER] = Field(
        description="Configuration block for the project workspace and folder structure.",
        examples=[{"project_root": "."}],
    )
    geographic: Annotated[GeographicConfig, Profile.USER] = Field(
        description="Configuration block for geographic and watershed delineation parameters."
    )
    domain: Annotated[DomainConfig, Profile.USER] = Field(
        default_factory=DomainConfig,
        description=(
            "Domain configuration defining domain depth plus the spatial-support "
            "mode used for heterogeneous parameter mapping "
            "(`none`, `geology`, or `zones`)."
        ),
    )
    data: Annotated[DataManagersConfig, Profile.USER] = Field(
        default_factory=DataManagersConfig,
        description=(
            "Data-managers configuration. Use `data.types` to declare requested "
            "families (for example `geology`). The launcher can also infer extra "
            "families from other sections (domain, flow), controlled by "
            "`data.inference_mode` ('warn' or 'strict')."
        ),
    )
    flow: Annotated[FlowConfig, Profile.USER] = Field(
        default_factory=FlowConfig,
        description=(
            "Flow process configuration with declared parameter ids in "
            "[flow].param_list and payloads validated from [flow.param.<id>] "
            "TOML sections."
        ),
    )
    transport: Annotated[TransportConfig, Profile.USER] = Field(
        default_factory=TransportConfig,
        description=(
            "Transport process configuration, with solver-specific parameter "
            "blocks under [transport.modpath.parameters], "
            "[transport.mt3dms.parameters], and [transport.modflow6gwt.parameters]."
        ),
    )
    simulation: Annotated[SimulationConfig, Profile.USER] = Field(
        default_factory=SimulationConfig,
        description=(
            "Optional simulation orchestration block loaded from [simulation] "
            "and [[simulation.process]]. When absent, the launcher uses its "
            "default fixed phase order."
        ),
    )
    solver: Annotated[SolverConfig, Profile.USER] = Field(
        default_factory=SolverConfig,
        description="Global solver selection loaded from [solver.backend].",
    )
    modflownwt: Annotated[ModflowConfig, Profile.EXPERT] = Field(
        default_factory=ModflowConfig,
        description=(
            "Expert MODFLOW-NWT package configuration loaded from "
            "[modflownwt.runtime.<package>], [modflownwt.process_specific], "
            "[modflownwt.sgrid.planar], and [modflownwt.sgrid.vertical]."
        ),
    )
    modflow6: Annotated[Modflow6Config, Profile.EXPERT] = Field(
        default_factory=Modflow6Config,
        description=(
            "Expert MODFLOW 6 package configuration loaded from "
            "[modflow6.runtime], [modflow6.process_specific], "
            "[modflow6.sgrid.planar], and [modflow6.sgrid.vertical]."
        ),
    )
    display: Annotated[DisplayConfig, Profile.USER] = Field(
        default_factory=DisplayConfig,
        description=("Optional display and export toggles loaded from the [display] section."),
    )
    persistence: Annotated[PersistenceConfig, Profile.USER] = Field(
        default_factory=PersistenceConfig,
        description=(
            "Storage backend toggles loaded from [persistence]. Drives the "
            "DuckDB catalog, Zarr field arrays, Parquet tables, and the "
            "`hydromodpy.lock` reproducibility manifest."
        ),
    )
    analysis: Annotated[AnalysisConfig | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Optional analysis hub loaded from [analysis]. Aggregates "
            "[analysis.capability_gallery] (figure publication), and "
            "[analysis.comparison] (simulation-comparison launcher)."
        ),
    )

    # Lightweight workflows (without simulation)
    overview: Annotated[OverviewConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional overview report settings loaded from the [overview] "
            "section.  When present without [simulation], triggers the "
            "data-overview (watershed identity card) workflow."
        ),
    )
    mesh_catchment: Annotated[MeshCatchmentConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional mesh-only settings loaded from the [mesh_catchment] "
            "section. Mesh-only public runs should use [simulation.process] "
            "with type='mesh'; the standalone mesh API can still consume this "
            "section directly."
        ),
    )
    mesh_input: Annotated[MeshInputConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional external mesh declaration loaded from the [mesh_input] "
            "section. Declares a pre-existing planar mesh (and optional solver "
            "exchange bundle) the simulation or comparison workflow should "
            "consume instead of running the embedded mesh-catchment workflow. "
            "Mutually exclusive with [mesh_catchment]."
        ),
    )
    calibration: Annotated[CalibrationConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional calibration settings loaded from the [calibration] "
            "section.  When present, triggers the calibration workflow."
        ),
    )
    testbed: Annotated[TestbedConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional method-testbed settings loaded from the [testbed] "
            "section. Drives the orchestration layer over child runners "
            "(comparison or simulation) and is dispatched when "
            "workflow.mode='testbed'."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _default_workspace_for_direct_validation(cls, data, info: ValidationInfo):
        """Provide a minimal workspace for direct model_validate callers."""
        if not isinstance(data, Mapping):
            return data
        context = _validation_context(info.context)
        payload = dict(data)
        workspace = payload.get("workspace")
        has_project_root = (
            isinstance(workspace, Mapping) and bool(workspace.get("project_root"))
        ) or bool(getattr(workspace, "project_root", None))
        if context == "toml" and not has_project_root:
            raise ValueError("TOML [workspace].project_root is required")
        if workspace is None:
            payload["workspace"] = {"project_root": "."}
        elif isinstance(workspace, Mapping) and not workspace.get("project_root"):
            workspace_payload = dict(workspace)
            workspace_payload["project_root"] = "."
            payload["workspace"] = workspace_payload
        return payload

    @model_validator(mode="after")
    def _check_cross_section_coherence(self) -> HydroModPyConfig:
        """Cross-section coherence checks run after sub-configs validate.

        Currently enforced invariants (architecture spec
        ``02_config_pydantic.md`` §3.2):

        * ``data.inference_mode == "strict"`` ⇒ at least one data type must
          be declared (``data.types`` non-empty).
        * ``calibration`` actif ⇒ ``flow.param_list`` non vide (no point
          calibrating with zero tunable parameters).
        * ``transport`` actif ⇒ solver must not be ``boussinesq`` (the
          Boussinesq solver does not support a transport process).
        """
        data_cfg = getattr(self, "data", None)
        if data_cfg is not None and getattr(data_cfg, "inference_mode", None) == "strict":
            declared_types = list(getattr(data_cfg, "types", []) or [])
            if not declared_types:
                raise ValueError(
                    "data.inference_mode='strict' requires at least one explicit "
                    "data type in data.types"
                )

        calibration_cfg = getattr(self, "calibration", None)
        flow_cfg = getattr(self, "flow", None)
        if calibration_cfg is not None and flow_cfg is not None:
            param_list = list(getattr(flow_cfg, "param_list", []) or [])
            if not param_list:
                raise ValueError(
                    "[calibration] requires flow.param_list to declare at least "
                    "one tunable parameter"
                )

        transport_cfg = getattr(self, "transport", None)
        solver_cfg = getattr(self, "solver", None)
        if transport_cfg is not None and solver_cfg is not None:
            engine = getattr(solver_cfg, "backend_name", None)
            engine_value = getattr(engine, "value", engine)
            active_transport_solver = getattr(transport_cfg, "solver", None)
            if engine_value == "boussinesq" and active_transport_solver:
                raise ValueError(
                    "solver.backend='boussinesq' does not support the [transport] section"
                )

        return self

    @classmethod
    def from_toml(
        cls,
        toml_path: Path | str,
        *,
        validate_profile: ProfileName | Profile | None = None,
    ) -> HydroModPyConfig:
        """
        Load and validate configuration from a TOML file.

        Relative paths are resolved against the TOML file's directory.
        Absolute paths are left unchanged. Paths starting with ``~`` are
        expanded to the user's home directory.

        Parameters
        ----------
        toml_path : Path | str
            Path to the input TOML configuration file.
        validate_profile : ProfileName | Profile | None
            Optional profile threshold. When provided, fields whose declared
            :class:`Profile` exceeds the threshold and are present in the TOML
            payload trigger a :class:`UserWarning` (validation still succeeds).

        Returns
        -------
        HydroModPyConfig
            The fully loaded and path-resolved configuration instance.
        """
        toml_path = Path(toml_path).expanduser().resolve()
        raw = load_toml_with_base_config(toml_path)

        if validate_profile is not None:
            threshold = resolve_profile(validate_profile)
            violations = collect_profile_violations(cls, raw, threshold)
            if violations:
                import warnings

                joined = ", ".join(
                    f"{'.'.join(path)}={level.name.lower()}" for path, level in violations
                )
                warnings.warn(
                    f"TOML {toml_path} declares fields above profile "
                    f"{threshold.name.lower()!r}: {joined}",
                    UserWarning,
                    stacklevel=2,
                )

        try:
            cfg = cls._from_payload(raw, base=toml_path.parent, context="toml")
        except ValidationError as exc:
            message = format_validation_error(exc, source_path=toml_path)
            raise ValueError(message) from exc

        # Derive run_id from TOML filename if not set explicitly.
        if not cfg.simulation.run_id:
            cfg.simulation.run_id = _derive_run_id_from_filename(toml_path)

        return cfg

    @classmethod
    def from_json(
        cls,
        payload: str | bytes,
        *,
        base_dir: str | Path | None = None,
    ) -> HydroModPyConfig:
        """Load and validate configuration from a JSON payload."""
        if base_dir is None:
            return cls.model_validate_json(payload)
        raw = json.loads(payload)
        if not isinstance(raw, Mapping):
            raise ValueError("HydroModPyConfig JSON payload must be a mapping")
        return cls.from_dict(raw, base_dir=base_dir)

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        base_dir: str | Path | None = None,
    ) -> HydroModPyConfig:
        """Load and validate configuration from a Python mapping."""
        base = Path(base_dir).expanduser().resolve() if base_dir is not None else Path.cwd()
        return cls._from_payload(payload, base=base, context="api")

    @classmethod
    def _from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        base: Path,
        context: ValidationContext = "api",
    ) -> HydroModPyConfig:
        """Normalize one raw config payload and validate the root model."""
        raw = copy.deepcopy(dict(payload))
        if "initializing" in raw:
            raise ValueError(
                "Section [initializing] is no longer supported. Use [workspace] instead."
            )
        if "modflow" in raw:
            raise ValueError(
                "Section [modflow] is no longer supported. "
                "Use [solver], [modflownwt], and [modflow6] sections instead."
            )
        if "capability_gallery" in raw:
            raise ValueError(
                "Section [capability_gallery] is no longer supported. "
                "Use [analysis.capability_gallery] instead."
            )
        if "batch" in raw:
            raise ValueError(
                "Section [batch] is no longer supported. Use workflow='testbed' "
                "with [testbed].profile = 'regional_lab' and [analysis.batch] instead."
            )
        if "regional_lab" in raw:
            raise ValueError(
                "Section [regional_lab] is not a HydroModPyConfig section. "
                "Use [analysis.batch] for regional-lab testbed settings."
            )
        known = set(cls.model_fields)
        unknown = sorted(set(raw) - known)
        if unknown:
            raise ValueError(f"Unknown top-level TOML section(s): {', '.join(unknown)}")

        # Auto-derive workspace.project_root from TOML location if absent.
        # HMP_PROJECT_ROOT env var takes precedence (used by test infra).
        workspace_section = raw.get("workspace", {})
        if workspace_section is None:
            workspace_section = {}
        if not isinstance(workspace_section, Mapping):
            raise ValueError("TOML section [workspace] must be a mapping")
        workspace_section = dict(workspace_section)
        env_project_root = os.environ.get("HMP_PROJECT_ROOT")
        if env_project_root:
            workspace_section["project_root"] = str(Path(env_project_root).expanduser().resolve())
        elif not workspace_section.get("project_root"):
            if context == "toml":
                raise ValueError("TOML [workspace].project_root is required")
            workspace_section["project_root"] = str(base)

        # Workspace must be parsed first so we can derive the shared data
        # directory and pass it to every other section loader. This lets
        # bare filenames in [data.*.sources].path resolve against
        # <workspace>/data/<role>/ instead of forcing the user to write
        # ../../data/<role>/<file>.
        parsed_workspace = load_standard_section(workspace_section, WorkspaceConfig, base)
        workspace_data_dir = getattr(parsed_workspace, "data_dir", None)

        def _std(model_cls):
            return lambda data, b: load_standard_section(
                data, model_cls, b, workspace_data_dir=workspace_data_dir
            )

        geographic_section = raw.get("geographic", {})
        catchment_section = (
            geographic_section.get("catchment") if isinstance(geographic_section, Mapping) else None
        )
        catchment_dem = (
            catchment_section.get("dem_init_path")
            if isinstance(catchment_section, Mapping)
            else None
        )
        allow_dem_bootstrap = (
            isinstance(geographic_section, Mapping)
            and not geographic_section.get("dem_init_path")
            and not catchment_dem
            and _raw_declares_dem_source(raw.get("data", {}))
        )

        section_loaders: dict[str, tuple[Any, Callable[[Any, Path], Any]]] = {
            "geographic": (
                geographic_section,
                lambda data, b: load_geographic_section(
                    data,
                    b,
                    workspace_data_dir=workspace_data_dir,
                    allow_dem_bootstrap=allow_dem_bootstrap,
                ),
            ),
            "domain": ({}, _std(DomainConfig)),
            "data": (
                {},
                lambda data, b: _load_data_section(data, b, workspace_data_dir=workspace_data_dir),
            ),
            "flow": ({}, _load_flow_section),
            "transport": ({}, _std(TransportConfig)),
            "simulation": ({}, _std(SimulationConfig)),
            "solver": ({}, _std(SolverConfig)),
            "modflownwt": ({}, _std(ModflowConfig)),
            "modflow6": ({}, _std(Modflow6Config)),
            "display": ({}, _std(DisplayConfig)),
            "persistence": ({}, _std(PersistenceConfig)),
            "analysis": (None, _load_optional_analysis_section),
            "overview": (None, _load_optional_overview_section),
            "mesh_catchment": (None, _load_optional_mesh_catchment_section),
            "mesh_input": (None, _load_optional_mesh_input_section),
            "calibration": (None, _load_optional_calibration_section),
            "testbed": (None, _load_optional_testbed_section),
        }

        parsed_sections: dict[str, Any] = {"workspace": parsed_workspace}
        for section_name, (default_value, loader) in section_loaders.items():
            section_data = raw.get(section_name, default_value)
            parsed_sections[section_name] = loader(section_data, base)

        if "workflow" in raw:
            workflow_section = raw["workflow"]
            if not isinstance(workflow_section, Mapping):
                raise ValueError("TOML section [workflow] must be a mapping with key 'mode'")
            parsed_sections["workflow"] = WorkflowConfig.model_validate(dict(workflow_section))

        cfg = cls.model_validate(
            parsed_sections,
            context={
                "allow_dem_bootstrap": allow_dem_bootstrap,
                "validation_context": context,
            },
        )
        return cfg

    @classmethod
    def from_snapshot(
        cls,
        snapshot: dict,
        **overrides,
    ) -> HydroModPyConfig:
        """Reconstruct a config from a stored JSON snapshot.

        Parameters
        ----------
        snapshot : dict
            The ``config_toml`` JSON snapshot stored in DuckDB.
        overrides
            Keyword overrides merged into the snapshot before
            validation.  Nested dicts are merged recursively.

        Returns
        -------
        HydroModPyConfig
        """
        merged = _deep_merge(snapshot, overrides) if overrides else dict(snapshot)
        return cls.model_validate(merged)
