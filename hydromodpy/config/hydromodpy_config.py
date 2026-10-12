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
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationError, ValidationInfo, model_validator

from hydromodpy.analysis.config import AnalysisConfig
from hydromodpy.analysis.testbed.config import TestbedConfig
from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.protocols import expand_calibration_protocol
from hydromodpy.config.config_migration import migrate_config_doc_on_load
from hydromodpy.config.stored_config_migration import (
    is_sealed_run_config,
    migrate_stored_config,
    raw_flow_process_solver,
)
from hydromodpy.config.toml_section_loader import (
    _deep_merge,
    _load_data_section,
    _load_flow_section,
    _load_optional_analysis_section,
    _load_optional_calibration_section,
    _load_optional_mesh_catchment_section,
    _load_optional_mesh_input_section,
    _load_optional_overview_section,
    _load_optional_spinup_section,
    _load_optional_testbed_section,
    _raw_declares_dem_source,
    _validation_context,
    load_geographic_section,
    load_standard_section,
)
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.export_spec import ExportRequest, load_export_requests
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.introspect import (
    collect_profile_violations,
    resolve_profile,
)
from hydromodpy.core.config_kit.mesh_input import MeshInputConfig
from hydromodpy.core.config_kit.profile import Profile, ProfileName
from hydromodpy.core.exceptions import (
    ConfigValidationError,
    IncompatibleCapabilitiesError,
)
from hydromodpy.core.time.window import (
    build_simulation_time_boundaries,
    resolve_simulation_time_window,
)
from hydromodpy.core.toml_io.error_locator import (
    format_validation_error,
    json_pointer,
    validation_error_details,
)
from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.data import DataManagersConfig
from hydromodpy.data.variables.hydrometry.config import HydrometryConfig
from hydromodpy.display.config import DisplayConfig
from hydromodpy.display.overview.config import OverviewConfig
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.physics.hydrology.soil_reservoir.config import (
    soil_reservoir_of,
    spinup_refusal,
    steady_start_refusal,
)
from hydromodpy.physics.transport.transport_config import TransportConfig
from hydromodpy.simulation.planning.config import SimulationConfig
from hydromodpy.simulation.planning.observation_config import ObservationConfig
from hydromodpy.simulation.spinup_config import SpinupConfig
from hydromodpy.solver.base.solver_config import (
    CustomBackend,
    SolverConfig,
    backend_following_the_process,
    solver_name_of_backend,
)
from hydromodpy.solver.modflow6.modflow6_config import Modflow6Config
from hydromodpy.solver.modflow_nwt.nwt import ModflowConfig
from hydromodpy.spatial.domain.depth_model_config import RASTER_DEPTH_MODEL_KINDS
from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.mesh.config import MeshCatchmentConfig
from hydromodpy.spatial.site_selection.config import SiteSelectionConfig

WorkflowMode = Literal[
    "simulation",
    "calibration",
    "overview",
    "comparison",
    "testbed",
    "site_selection",
]
ValidationContext = Literal["toml", "api"]
Verbosity = Literal["quiet", "normal", "verbose", "debug"]


class WorkflowConfig(HydroModelBase):
    """Workflow selector configuration."""

    mode: Annotated[WorkflowMode, Profile.USER] = Field(
        ...,
        description="Workflow mode dispatched by `hmp run`.",
        json_schema_extra={
            "value_docs": {
                "simulation": (
                    "Runs one forward simulation and persists solver outputs, "
                    "catalog rows, and result stores."
                ),
                "calibration": (
                    "Repeatedly proposes parameters, runs candidate simulations, "
                    "and records the calibration history."
                ),
                "overview": (
                    "Loads geographic and data context and renders review maps "
                    "without running a solver."
                ),
                "comparison": (
                    "Runs several child simulations from one shared base config "
                    "and compares their observables."
                ),
                "testbed": (
                    "Expands a case matrix, delegates each case to a runner, and "
                    "collects evidence artifacts."
                ),
                "site_selection": (
                    "Selects or rejects candidate catchments and produces an "
                    "auditable HTML review report."
                ),
            }
        },
    )
    verbosity: Annotated[Verbosity, Profile.USER] = Field(
        default="normal",
        description=(
            "How much the run prints on the console. The project debug log, "
            "`.hmp/logs/hydromodpy_debug.log`, records every DEBUG line "
            "whatever this says. `hmp run -q/-v/--debug` and the "
            "HMP_VERBOSITY environment variable both win over this field."
        ),
        json_schema_extra={
            "value_docs": {
                "quiet": "Warnings and errors only. No banner, no progress display.",
                "normal": (
                    "Banner, one spinner line per pipeline step with its duration, "
                    "warnings, and the milestones: what was rendered, what was "
                    "exported, how the run ended."
                ),
                "verbose": "Every INFO line the run emits, on top of `normal`.",
                "debug": (
                    "Every DEBUG line, with module and line number. The progress "
                    "display steps aside so the lines scroll plainly."
                ),
            }
        },
        examples=["normal", "quiet"],
    )
    profile: Annotated[bool | str, Profile.EXPERT] = Field(
        default=False,
        description=(
            "Profile the run with pyinstrument (honored by the hmp CLI; the "
            "--profile flag wins over this field). true writes "
            "<config>.profile.html next to the config; a string sets the "
            "HTML report path."
        ),
    )


RESTART_CAPABILITY = "flow:restart"
"""What a backend declares when it reads ``[flow] restart_from``."""

CYCLIC_SPINUP_CAPABILITY = "flow:spinup_cyclic"
"""What a backend declares when it can repeat its own period to settle a state."""


def _declared_flow_engine(cfg: HydroModPyConfig) -> str | None:
    """Name of the flow solver this config would build, or None if undeclared.

    Same lookup order as ``project.phases.detect_solver``: a
    ``[[simulation.process]]`` entry of type 'flow' names its solver before
    ``solver.backend_name`` falls back to the global default.
    """
    for process in getattr(getattr(cfg, "simulation", None), "process", None) or ():
        if getattr(process, "type", None) == "flow" and getattr(process, "solvers", None):
            return str(process.solvers[0])
    solver_cfg = getattr(cfg, "solver", None)
    engine = getattr(solver_cfg, "backend_name", None) if solver_cfg is not None else None
    return str(engine) if engine else None


_ROOT_PERSISTENCE_REFUSAL = (
    "Section [persistence] is not read by any run. Write its keys under "
    "[simulation.results.persistence], which a run reads, or under "
    "[calibration.persistence] for the outputs of a calibration."
)


def _refuse_unknown_transport_solvers(names: list[str]) -> None:
    """Refuse a transport solver name that is neither built in nor a plugin.

    Without this check the name passed validation and the run failed later,
    far from the line of the file that holds the typo.
    """
    if not names:
        return
    from hydromodpy.solver.base import registry

    registry.load_plugins()
    unknown = [name for name in names if not registry.is_supported("transport", name)]
    if not unknown:
        return
    known = ", ".join(name for _, name in registry.pairs_for_process("transport"))
    raise ValueError(
        f"Unknown transport solver '{unknown[0]}' in [[simulation.process]]: it is "
        f"neither built in nor a registered plugin. Write one of: {known}."
    )


def _section_refusal(
    section: str,
    message: str,
    *,
    source_path: Path | None = None,
    error_type: str = "extra_forbidden",
) -> ConfigValidationError:
    """Build the refusal of one named top-level section, pointer included.

    A section a document is not allowed to declare is a fault of that document,
    not of this process, so it carries the same shape as a Pydantic field fault
    and reaches the same exit code.
    """
    return ConfigValidationError(
        f"{source_path}: {message}" if source_path is not None else message,
        details=(
            {
                "pointer": json_pointer((section,)),
                "loc": section,
                "msg": message,
                "type": error_type,
            },
        ),
        source=None if source_path is None else str(source_path),
    )


def _validation_refusal(
    exc: ValidationError,
    *,
    loc_prefix: Sequence[str] = (),
    source_path: Path | None = None,
    document: Mapping[str, Any] | None = None,
) -> ConfigValidationError:
    """Turn a Pydantic failure into the typed refusal this boundary raises.

    ``loc_prefix`` is what makes the JSON Pointer true. A section is validated
    against its own model, so Pydantic reports ``dem_correction_type`` where the
    document says ``geographic.dem_correction_type``; without the prefix the
    pointer would name a root key that does not exist.

    ``document`` is the mapping that was validated, and it is what settles the
    other half: Pydantic inserts the tag of the union variant it chose, and the
    document is the only thing that knows that segment is not a key of its own.
    """
    return ConfigValidationError(
        format_validation_error(
            exc, source_path=source_path, loc_prefix=loc_prefix, document=document
        ),
        details=validation_error_details(
            exc, loc_prefix=loc_prefix, source_path=source_path, document=document
        ),
        source=None if source_path is None else str(source_path),
    )


def _derive_name_from_filename(toml_path: Path) -> str:
    """Derive a simulation name from a TOML filename.

    ``run_steady_nwt.toml`` -> ``steady_nwt``
    ``config.toml`` -> ``config``
    """
    stem = toml_path.stem
    return re.sub(r"^run_", "", stem)


def _resolve_calibration_parameter_names(cfg: Any) -> None:
    """Give every calibration parameter the path its name points at.

    A parameter that names a quantity rather than a path is resolved against
    the catalogue this very configuration exposes, so the search writes into a
    value the model actually carries. A parameter that declares its path is left
    alone, and a configuration without a calibration costs one attribute read.
    """
    calibration = getattr(cfg, "calibration", None)
    if calibration is None:
        return
    from hydromodpy.calibration.parameter_resolution import resolve_parameter_targets

    # Not strict: a name that reaches nothing is reported by the preflight, beside
    # the other faults of the file. Refusing here would make it the only one found.
    resolve_parameter_targets(calibration, cfg, strict=False)


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
            "'comparison', 'testbed', 'site_selection'. "
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
        description=(
            "Global solver block loaded from [solver]: the backend selector in "
            "[solver.backend], plus the backend-agnostic preprocessing switches "
            "both MODFLOW backends read (solver.sink_fill, "
            "solver.drain_band_depth_m)."
        ),
    )
    modflownwt: Annotated[ModflowConfig, Profile.USER] = Field(
        default_factory=ModflowConfig,
        description=(
            "MODFLOW-NWT settings: the structured grid ([modflownwt.sgrid.planar], "
            "[modflownwt.sgrid.vertical]), the package options "
            "([modflownwt.process_specific]) and the solver settings "
            "([modflownwt.runtime.<package>], expert keys)."
        ),
    )
    modflow6: Annotated[Modflow6Config, Profile.USER] = Field(
        default_factory=Modflow6Config,
        description=(
            "MODFLOW 6 settings: the structured grid ([modflow6.sgrid.planar], "
            "[modflow6.sgrid.vertical]), the package options ([modflow6.process_specific]) "
            "and the solver settings ([modflow6.runtime], expert keys)."
        ),
    )
    display: Annotated[DisplayConfig, Profile.USER] = Field(
        default_factory=DisplayConfig,
        description="The figures a run draws, loaded from the [display] section.",
    )
    export: Annotated[list[ExportRequest], Profile.USER] = Field(
        default_factory=list,
        description=(
            "The exports written at the end of a run, one [[export]] block per request, "
            "in the order of the file. Each block says what (variables), when (time or "
            "period) and where (folder or file); the format follows the data."
        ),
        json_schema_extra=field_metadata(
            renamed_from=[
                "export.artifacts",
                "export.csv_timeseries",
                "export.geopackage",
                "export.geotiff",
                "export.netcdf",
                "export.output_dir",
                "export.package",
                "export.shapefile",
                "export.vtu",
            ]
        ),
    )
    observation: Annotated[ObservationConfig, Profile.USER] = Field(
        default_factory=ObservationConfig,
        description=(
            "Observation points declared in [observation] and sampled while the "
            "run still holds its fields. Each [[observation.points]] entry names "
            "a location (x, y, and layer or depth); its series land in the run "
            "timeseries table, so no post-hoc interrogation is needed for a point "
            "known in advance."
        ),
    )
    analysis: Annotated[AnalysisConfig | None, Profile.USER] = Field(
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
    spinup: Annotated[SpinupConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional cyclic spin-up settings loaded from the [spinup] section. "
            "Drives 'hmp spinup': repeat a forcing window, restart each cycle from "
            "the previous state, until the heads and the lake stage converge."
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
    site_selection: Annotated[SiteSelectionConfig | None, Profile.USER] = Field(
        default=None,
        description="Optional upstream basin site-selection workflow configuration.",
    )
    hydrometry: Annotated[HydrometryConfig | None, Profile.USER] = Field(
        default=None,
        description="Optional hydrometric observations used by data and site-selection workflows.",
    )

    @model_validator(mode="before")
    @classmethod
    def _default_workspace_for_direct_validation(cls, data: Any, info: ValidationInfo) -> Any:
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

    @model_validator(mode="before")
    @classmethod
    def _refuse_root_persistence(cls, data: Any) -> Any:
        """Refuse a root ``persistence`` table: no run reads it."""
        if isinstance(data, Mapping) and "persistence" in data:
            raise ValueError(_ROOT_PERSISTENCE_REFUSAL)
        return data

    @model_validator(mode="before")
    @classmethod
    def _align_solver_keys(cls, data: Any) -> Any:
        """Make ``solver.backend`` and the flow process name one solver.

        The run builds the solver the flow process names, and the checks
        below read ``solver.backend``. When the file writes only the process,
        the backend follows it. When it writes both with two names, it is
        refused.
        """
        if not isinstance(data, Mapping):
            return data
        flow = raw_flow_process_solver(data.get("simulation"))
        if flow is None:
            return data
        process_id, process_solver = flow
        solver = data.get("solver")
        if isinstance(solver, SolverConfig):
            declared = "backend" in solver.model_fields_set
            backend = solver.backend if declared else None
        elif isinstance(solver, Mapping):
            declared = "backend" in solver
            backend = solver.get("backend")
        elif solver is None:
            declared, backend = False, None
        else:
            return data
        if declared:
            backend_solver = solver_name_of_backend(backend)
            if backend_solver is not None and backend_solver.lower() != process_solver.lower():
                raise ValueError(
                    f"solver.backend names {backend_solver!r} and the flow process "
                    f"{process_id!r} of [[simulation.process]] names {process_solver!r} in "
                    "solvers. The run builds the solver of the process and the checks "
                    "read solver.backend, so both must name the same solver. Write the "
                    "same name in both, or remove solver.backend: it then follows the "
                    "flow process."
                )
            return data
        # The derived backend is marked, so it stays out of the fields set and a
        # later assignment of another flow solver moves it again.
        payload = dict(data)
        selector = backend_following_the_process(process_solver)
        if isinstance(solver, SolverConfig):
            derived = solver.model_copy(update={"backend": selector})
            derived.__pydantic_fields_set__.discard("backend")
            payload["solver"] = derived
        else:
            payload["solver"] = {**(solver or {}), "backend": selector}
        return payload

    def _check_river_network_threshold_for_the_mesh(self) -> None:
        """Refuse a mesh that needs the river network when no threshold is set.

        The mesh switches ``[geographic.river_network]`` on by itself, so the
        threshold check of that section never ran and the run stopped at
        ``build_geographic`` on a message that named neither the section nor the
        mesh.
        """
        geographic = getattr(self, "geographic", None)
        if geographic is None or geographic.uses_synthetic_geographic():
            return
        river_network = geographic.river_network
        if bool(river_network.enabled):
            return
        needed_by = None
        mesh = getattr(self, "mesh_catchment", None)
        mode = str(getattr(mesh, "constraints_mode", "") or "").strip().lower()
        if mesh is not None and mode in {"rivers_only", "geology_rivers"}:
            needed_by = f"mesh_catchment.constraints_mode = {mode!r}"
        flow_cfg = getattr(self, "flow", None)
        active_bc = {str(name).lower() for name in getattr(flow_cfg, "active_bc", []) or []}
        if getattr(self, "mesh_input", None) is not None and "stream" in active_bc:
            needed_by = "The 'stream' boundary on a [mesh_input] mesh"
        if needed_by is None:
            return
        refusal = river_network.missing_threshold_refusal(needed_by=needed_by)
        if refusal is not None:
            raise ValueError(refusal)

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
        * ``domain.depth_model.kind`` is ``raster_substratum`` or
          ``raster_thickness`` ⇒ ``[data.substratum]`` is declared, since that
          is the raster the domain reads.
        * ``[modflownwt.sgrid.top_sampling]`` zonal ⇒ ``channel_source = "none"``,
          since MODFLOW-NWT builds no channel mask.
        * ``[data.soil_capacity]`` declared ⇒ ``[flow.sinks_sources.recharge.soil]``
          is declared, since only the soil reservoir reads that raster.
        * ``workflow.mode = "overview"`` ⇒ an ``[overview]`` section is declared:
          without it the workflow delineates and loads, then writes no report.
        """
        if getattr(getattr(self, "workflow", None), "mode", None) == "overview" and (
            getattr(self, "overview", None) is None
        ):
            raise ValueError(
                "workflow.mode = 'overview' needs an [overview] section: it names the card and "
                "holds its window and panels. Add the section, with at least a name."
            )

        data_cfg = getattr(self, "data", None)
        if data_cfg is not None and getattr(data_cfg, "inference_mode", None) == "strict":
            declared_types = list(getattr(data_cfg, "types", []) or [])
            if not declared_types:
                raise ValueError(
                    "data.inference_mode='strict' requires at least one explicit "
                    "data type in data.types"
                )

        depth_kind = getattr(
            getattr(getattr(self, "domain", None), "depth_model", None), "kind", None
        )
        if depth_kind in RASTER_DEPTH_MODEL_KINDS and getattr(data_cfg, "substratum", None) is None:
            raise ValueError(
                f"domain.depth_model kind = {depth_kind!r} reads the raster declared under "
                "[data.substratum]; declare it with one custom source."
            )

        nwt_top_sampling = getattr(
            getattr(getattr(self, "modflownwt", None), "sgrid", None), "top_sampling", None
        )
        if (
            nwt_top_sampling is not None
            and nwt_top_sampling.mode == "zonal"
            and nwt_top_sampling.channel_source != "none"
        ):
            raise ValueError(
                "[modflownwt.sgrid.top_sampling] mode = 'zonal' with "
                f"channel_source = {nwt_top_sampling.channel_source!r}: MODFLOW-NWT does "
                "not read the channel tree for the zonal top, so the channel cells would "
                "get the hillslope statistic like the others. Set channel_source = 'none' "
                "(median only) or run MODFLOW 6."
            )

        self._check_river_network_threshold_for_the_mesh()

        calibration_cfg = getattr(self, "calibration", None)
        flow_cfg = getattr(self, "flow", None)
        if calibration_cfg is not None and flow_cfg is not None:
            param_list = list(getattr(flow_cfg, "param_list", []) or [])
            if not param_list:
                raise ValueError(
                    "[calibration] requires flow.param_list to declare at least "
                    "one tunable parameter"
                )

        solver_cfg = getattr(self, "solver", None)
        if solver_cfg is not None and isinstance(
            getattr(solver_cfg, "backend", None), CustomBackend
        ):
            # A name that is not built in becomes a custom backend. Check it
            # resolves now, or the checks below would refuse a typo with a
            # message about a boundary or a capability.
            solver_cfg.validate_registry()
        if solver_cfg is not None:
            # A transport runs when [[simulation.process]] declares one; the
            # [transport] section is always there, filled with its defaults.
            engine = getattr(solver_cfg, "backend_name", None)
            engine_value = getattr(engine, "value", engine)
            processes = getattr(getattr(self, "simulation", None), "process", None) or []
            transport_solvers = [
                name
                for process in processes
                if getattr(process, "type", None) == "transport"
                for name in getattr(process, "solvers", None) or []
            ]
            _refuse_unknown_transport_solvers(transport_solvers)
            if engine_value == "boussinesq" and transport_solvers:
                raise ValueError(
                    "solver.backend = 'boussinesq' runs no transport: the transport "
                    f"solvers ({', '.join(transport_solvers)}) read the flow of a MODFLOW "
                    "model. Remove the transport entry of [[simulation.process]], or run "
                    "the flow with 'modflow6' or 'modflow_nwt'."
                )

        if flow_cfg is not None and solver_cfg is not None:
            from hydromodpy.physics.flow.boundary_condition_registry import boundary_definition

            engine = getattr(solver_cfg, "backend_name", None)
            engine_value = getattr(engine, "value", engine)
            active_bc = {str(name).lower() for name in getattr(flow_cfg, "active_bc", []) or []}
            sinks_sources = getattr(flow_cfg, "sinks_sources", None)

            # Every active boundary must be supported by the chosen backend, or it
            # would be silently ignored at build time (lake/reservoir/sfr on NWT or
            # Boussinesq were accepted then dropped).
            for bc_id in sorted(active_bc):
                definition = boundary_definition(bc_id)
                if definition is not None and not definition.supports_backend(str(engine_value)):
                    supported = ", ".join(definition.supported_backends)
                    raise IncompatibleCapabilitiesError(
                        f"solver.backend={engine_value!r} does not support the '{bc_id}' "
                        f"boundary (supported by: {supported}); it would be silently ignored. "
                        f"Use a supported backend or remove '{bc_id}' from flow.active_bc."
                    )

            lakes = getattr(sinks_sources, "lakes", None) or {}
            if lakes and not ({"lake", "reservoir"} & active_bc):
                raise ValueError(
                    "flow.sinks_sources.lakes declares lakes but flow.active_bc lists "
                    "neither 'lake' nor 'reservoir'; add 'lake' (or 'reservoir') to "
                    "flow.active_bc to activate the LAK package, or remove the lakes. "
                    "The LAK builder only activates on active_bc, so as-is the lakes "
                    "would be silently ignored."
                )
            sfr_payload = getattr(sinks_sources, "sfr", None) or {}
            if sfr_payload and "sfr" not in active_bc:
                raise ValueError(
                    "flow.sinks_sources.sfr declares stream networks but flow.active_bc does "
                    "not list 'sfr'; add 'sfr' to activate the SFR package, or remove the "
                    "networks. As-is the streams would be silently ignored."
                )
            # Every backend builds its wells only when active_sinks_sources lists
            # them, so declared wells would otherwise pump nothing, silently.
            wells = getattr(sinks_sources, "wells", None) or {}
            active_sinks_sources = {
                str(name).lower() for name in getattr(flow_cfg, "active_sinks_sources", []) or []
            }
            if wells and "wells" not in active_sinks_sources:
                names = ", ".join(sorted(str(name) for name in wells))
                raise ValueError(
                    f"flow.sinks_sources.wells declares wells ({names}) but "
                    "flow.active_sinks_sources does not list 'wells', so no well "
                    "would pump: add 'wells' to flow.active_sinks_sources, or remove "
                    "the wells."
                )

            # A hotstart is read by the backends that declare they can read one.
            # Elsewhere the key was accepted and never looked at, so the run
            # started from the declared initial condition and said nothing.
            if getattr(flow_cfg, "restart_from", None):
                from hydromodpy.solver.base.registry import capabilities

                if RESTART_CAPABILITY not in capabilities("flow", str(engine_value)):
                    raise IncompatibleCapabilitiesError(
                        f"solver.backend={engine_value!r} does not read flow.restart_from; "
                        "it would be silently ignored and the run would start from "
                        "flow.ic instead. Use a backend that declares "
                        f"{RESTART_CAPABILITY!r}, or drop flow.restart_from."
                    )

            # A cyclic spin-up repeats the run's own period inside the run. A
            # backend that cannot do that would start from flow.ic and report a
            # settled antecedent it never computed.
            head_ic = getattr(getattr(flow_cfg, "ic", None), "h", None)
            if str(getattr(head_ic, "type", "")) == "spinup_cyclic":
                from hydromodpy.solver.base.registry import capabilities

                if CYCLIC_SPINUP_CAPABILITY not in capabilities("flow", str(engine_value)):
                    raise IncompatibleCapabilitiesError(
                        f"flow.ic.type='spinup_cyclic' repeats the simulated period until "
                        f"the state settles, and solver.backend={engine_value!r} cannot: it "
                        "would start from the declared initial condition and say nothing. "
                        f"Use a backend that declares {CYCLIC_SPINUP_CAPABILITY!r}, or run "
                        "the cycling outside the run with `hmp spinup` and point "
                        "flow.restart_from at its result."
                    )

            # Flow barriers and dam cutoff walls are a MODFLOW 6-only addon.
            barriers = getattr(sinks_sources, "flow_barriers", None) or {}
            has_cutoff = any(
                getattr(lake_cfg, "cutoff_wall", None) is not None for lake_cfg in lakes.values()
            )
            if (barriers or has_cutoff) and engine_value != "modflow6":
                raise IncompatibleCapabilitiesError(
                    f"solver.backend={engine_value!r} does not support flow barriers / dam "
                    "cutoff walls (HFB); they require the 'modflow6' backend."
                )

        soil = soil_reservoir_of(self.flow)
        if soil is not None:
            # data.types is read as declared here: recharge and runoff are never
            # inferred (data/loading/planner.py), so a fully-silent double count
            # would otherwise pass validation.
            declared_data_types = set(getattr(data_cfg, "types", []) or [])
            if "recharge" in declared_data_types:
                raise ValueError(
                    "[flow.sinks_sources.recharge.soil] computes the recharge from "
                    "the precipitation and the ETP, and data.types also loads one "
                    "from [data.recharge]: the model would receive one and ignore "
                    'the other. Remove "recharge" from data.types to keep the soil '
                    "reservoir (and write recharge__delete = true under [data] if a "
                    "base file declares it), or remove "
                    "[flow.sinks_sources.recharge.soil] to use the loaded recharge."
                )
            if "runoff" in declared_data_types:
                raise ValueError(
                    "[data.runoff] loads a surface runoff that already takes its "
                    "share of the rain the soil reservoir receives (SIM2 RUNC, for "
                    "instance): the streams, the lakes and the gauged discharge "
                    'would count that water twice. Remove "runoff" from data.types '
                    "(and write runoff__delete = true under [data] if a base file "
                    "declares it); in soil mode the water that seeps out of "
                    "saturated ground reaches the streams through the drains, and "
                    "sealed ground through impervious_fraction."
                )
            if getattr(data_cfg, "precipitation", None) is None:
                raise ValueError(
                    "[flow.sinks_sources.recharge.soil] fills the soil with daily "
                    "precipitation, and no [data.precipitation] section says where "
                    "to read it: add a [[data.precipitation.sources]] block, for "
                    'example source = "sim2" with extent = "watershed".'
                )
            if getattr(data_cfg, "etp", None) is None:
                raise ValueError(
                    "[flow.sinks_sources.recharge.soil] empties the soil with "
                    "daily ETP, and no [data.etp] section says where to read it: "
                    'add a [[data.etp.sources]] block, for example source = "sim2" '
                    'with extent = "watershed".'
                )

            engine = _declared_flow_engine(self)
            if engine is not None and engine != "modflow6":
                raise IncompatibleCapabilitiesError(
                    "[flow.sinks_sources.recharge.soil] is wired to MODFLOW 6 "
                    f"only, and this run's flow solver is {engine!r}: the recharge "
                    "it computes would never reach that solver. Write "
                    'solvers = ["modflow6"] in [[simulation.process]], or remove '
                    "[flow.sinks_sources.recharge.soil] and declare [data.recharge]."
                )

            active_sinks_sources = {
                str(name).lower() for name in getattr(flow_cfg, "active_sinks_sources", []) or []
            }
            if "recharge" not in active_sinks_sources:
                raise ValueError(
                    "[flow.sinks_sources.recharge.soil] computes a recharge that "
                    "flow.active_sinks_sources does not list, so MODFLOW would "
                    'receive none: add "recharge" to flow.active_sinks_sources.'
                )

            soil_active_bc = {
                str(name).lower() for name in getattr(flow_cfg, "active_bc", []) or []
            }
            if soil_active_bc & {"lake", "reservoir"} and "sfr" not in soil_active_bc:
                lake_token = "lake" if "lake" in soil_active_bc else "reservoir"
                raise ValueError(
                    f'flow.active_bc lists "{lake_token}" without "sfr": in soil '
                    "mode the water that seeps out of the ground reaches a lake "
                    "only through the stream network, so the lake would receive "
                    'none of it. Add "sfr" with its [flow.sinks_sources.sfr] '
                    "network, or remove [flow.sinks_sources.recharge.soil] and "
                    "load [data.runoff] as before."
                )

            for precip_source in (
                getattr(getattr(data_cfg, "precipitation", None), "sources", []) or []
            ):
                components = list(getattr(precip_source, "components", []) or [])
                if components != ["total"]:
                    raise ValueError(
                        f"[data.precipitation] loads components = {components!r}, "
                        "and the soil reservoir takes one precipitation grid: two "
                        "grids would be averaged, not added. Write "
                        'components = ["total"], which counts the snow as rain.'
                    )

            window = resolve_simulation_time_window(self)
            if window is None:
                raise ValueError(
                    "[flow.sinks_sources.recharge.soil] runs day by day over "
                    "[simulation.time], which this file does not declare: add "
                    "start_datetime, end_datetime and step_value."
                )

            boundaries = build_simulation_time_boundaries(window)
            run_days = (boundaries[-1] - boundaries[0]).days
            spinup_message = spinup_refusal(soil, run_days)
            if spinup_message is not None:
                raise ValueError(spinup_message)

            steady_start_message = steady_start_refusal(flow_cfg, window)
            if steady_start_message is not None:
                raise ValueError(steady_start_message)

        if soil is None and getattr(data_cfg, "soil_capacity", None) is not None:
            raise ValueError(
                "[data.soil_capacity] is read only by the soil reservoir, and this "
                "file declares no [flow.sinks_sources.recharge.soil]: declare the "
                "soil section, or remove [data.soil_capacity]."
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
        if is_sealed_run_config(toml_path):
            # A run froze this file in its run directory: drop the keys removed
            # since, so the run can still be resumed. It goes first: the stored
            # migration owns the keys a sealed file cannot be told to fix, and the
            # message for a user file would name a command that does not apply.
            raw = migrate_stored_config(raw, source=toml_path)
        # A config written against an earlier schema still loads: the migration
        # runs on the parsed payload, in memory. Reading never rewrites the file;
        # only `hmp doctor` does, and the log line says so.
        migrate_config_doc_on_load(raw, source=toml_path)

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
            cfg = cls._from_payload(
                raw, base=toml_path.parent, context="toml", source_path=toml_path
            )
        except IncompatibleCapabilitiesError as exc:
            # A typed capability error from the after-validator does not carry the
            # TOML location; prepend it while keeping the type and error code.
            raise type(exc)(f"{toml_path}: {exc.message or exc}") from exc

        # Derive the simulation name from the TOML filename if not set explicitly.
        if not cfg.simulation.name:
            cfg.simulation.name = _derive_name_from_filename(toml_path)

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
            raise ConfigValidationError(
                "HydroModPyConfig JSON payload must be a mapping",
                details=(
                    {
                        "pointer": "",
                        "loc": "<root>",
                        "msg": "Input should be a valid dictionary",
                        "type": "dict_type",
                    },
                ),
            )
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
        source_path: Path | None = None,
    ) -> HydroModPyConfig:
        """Normalize one raw config payload and validate the root model.

        Every refusal of the document leaves this method as a
        :class:`~hydromodpy.core.exceptions.ConfigValidationError`, never as a
        bare ``ValueError`` and never as a raw Pydantic ``ValidationError``:
        those two both map to exit code 1, which is the code for a bug in this
        process, and a caller cannot tell them apart from one.

        A section loader is handed the raw mapping of one section and nothing
        else, so a ``ValueError`` leaving it names that section of the document.
        It is converted here rather than at each of its raise sites, which is
        what keeps the rule true for the next loader somebody writes.
        """
        try:
            raw = expand_calibration_protocol(copy.deepcopy(dict(payload)))
        except ValidationError as exc:
            # Pydantic's ValidationError IS a ValueError, so this clause has to
            # come first: a protocol validating its own options against a model
            # would otherwise be rendered by `str()` as a raw Pydantic dump,
            # typed `value_error`, and pointed at the whole [calibration] table.
            raise _validation_refusal(
                exc,
                loc_prefix=("calibration", "protocol"),
                source_path=source_path,
                document=payload,
            ) from exc
        except ValueError as exc:
            raise _section_refusal(
                "calibration",
                str(exc),
                source_path=source_path,
                error_type="value_error",
            ) from exc
        if "initializing" in raw:
            raise _section_refusal(
                "initializing",
                "Section [initializing] is no longer supported. Use [workspace] instead.",
                source_path=source_path,
            )
        if "modflow" in raw:
            raise _section_refusal(
                "modflow",
                "Section [modflow] is no longer supported. "
                "Use [solver], [modflownwt], and [modflow6] sections instead.",
                source_path=source_path,
            )
        if "capability_gallery" in raw:
            raise _section_refusal(
                "capability_gallery",
                "Section [capability_gallery] is no longer supported. "
                "Use [analysis.capability_gallery] instead.",
                source_path=source_path,
            )
        if "batch" in raw:
            raise _section_refusal(
                "batch",
                "Section [batch] is no longer supported. Use workflow='testbed' "
                "with [testbed].profile = 'regional_lab' and [analysis.batch] instead.",
                source_path=source_path,
            )
        if "persistence" in raw:
            raise _section_refusal(
                "persistence",
                _ROOT_PERSISTENCE_REFUSAL,
                source_path=source_path,
            )
        if "regional_lab" in raw:
            raise _section_refusal(
                "regional_lab",
                "Section [regional_lab] is not a HydroModPyConfig section. "
                "Use [analysis.batch] for regional-lab testbed settings.",
                source_path=source_path,
            )
        known = set(cls.model_fields)
        unknown = sorted(set(raw) - known)
        if unknown:
            message = f"Unknown top-level TOML section(s): {', '.join(unknown)}"
            raise ConfigValidationError(
                f"{source_path}: {message}" if source_path is not None else message,
                source=None if source_path is None else str(source_path),
                details=tuple(
                    {
                        "pointer": json_pointer((name,)),
                        "loc": name,
                        "msg": "Extra inputs are not permitted",
                        "type": "extra_forbidden",
                    }
                    for name in unknown
                ),
            )

        # Auto-derive workspace.project_root from TOML location if absent.
        # HMP_PROJECT_ROOT env var takes precedence (used by test infra).
        workspace_section = raw.get("workspace", {})
        if workspace_section is None:
            workspace_section = {}
        if not isinstance(workspace_section, Mapping):
            raise _section_refusal(
                "workspace",
                "TOML section [workspace] must be a mapping",
                source_path=source_path,
                error_type="dict_type",
            )
        workspace_section = dict(workspace_section)
        env_project_root = os.environ.get("HMP_PROJECT_ROOT")
        if env_project_root:
            workspace_section["project_root"] = str(Path(env_project_root).expanduser().resolve())
        elif not workspace_section.get("project_root"):
            if context == "toml":
                message = "TOML [workspace].project_root is required"
                raise ConfigValidationError(
                    f"{source_path}: {message}" if source_path is not None else message,
                    source=None if source_path is None else str(source_path),
                    details=(
                        {
                            "pointer": json_pointer(("workspace", "project_root")),
                            "loc": "workspace.project_root",
                            "msg": "Field required",
                            "type": "missing",
                        },
                    ),
                )
            workspace_section["project_root"] = str(base)

        # Workspace must be parsed first so we can derive the shared data
        # directory and pass it to every other section loader. This lets
        # bare filenames in [data.*.sources].path resolve against
        # <workspace>/data/<role>/ instead of forcing the user to write
        # ../../data/<role>/<file>.
        try:
            parsed_workspace = load_standard_section(workspace_section, WorkspaceConfig, base)
        except ValidationError as exc:
            raise _validation_refusal(
                exc, loc_prefix=("workspace",), source_path=source_path, document=raw
            ) from exc
        except ValueError as exc:
            raise _section_refusal(
                "workspace", str(exc), source_path=source_path, error_type="value_error"
            ) from exc
        workspace_data_dir = getattr(parsed_workspace, "data_dir", None)

        def _std(model_cls: type[Any]) -> Callable[[Any, Path], Any]:
            return lambda data, b: load_standard_section(
                data, model_cls, b, workspace_data_dir=workspace_data_dir
            )

        workflow_mode = None
        workflow_section = raw.get("workflow")
        if isinstance(workflow_section, Mapping):
            workflow_mode = workflow_section.get("mode")

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
            "flow": (
                {},
                lambda data, b: _load_flow_section(data, b, workspace_data_dir=workspace_data_dir),
            ),
            "transport": ({}, _std(TransportConfig)),
            "simulation": ({}, _std(SimulationConfig)),
            "solver": ({}, _std(SolverConfig)),
            "modflownwt": ({}, _std(ModflowConfig)),
            "modflow6": ({}, _std(Modflow6Config)),
            "display": ({}, _std(DisplayConfig)),
            "export": ([], lambda data, _b: load_export_requests(data)),
            "observation": ({}, _std(ObservationConfig)),
            "analysis": (None, _load_optional_analysis_section),
            "overview": (None, _load_optional_overview_section),
            "mesh_catchment": (None, _load_optional_mesh_catchment_section),
            "mesh_input": (None, _load_optional_mesh_input_section),
            "calibration": (None, _load_optional_calibration_section),
            "spinup": (None, _load_optional_spinup_section),
            "testbed": (None, _load_optional_testbed_section),
            "site_selection": (
                None,
                lambda data, b: (
                    None
                    if (
                        data is None
                        or (
                            isinstance(data, Mapping)
                            and not data
                            and workflow_mode != "site_selection"
                        )
                    )
                    else load_standard_section(
                        data,
                        SiteSelectionConfig,
                        b,
                        workspace_data_dir=workspace_data_dir,
                    )
                ),
            ),
            "hydrometry": (
                None,
                lambda data, b: (
                    None
                    if data is None
                    else load_standard_section(
                        data,
                        HydrometryConfig,
                        b,
                        workspace_data_dir=workspace_data_dir,
                    )
                ),
            ),
        }

        parsed_sections: dict[str, Any] = {"workspace": parsed_workspace}
        for section_name, (default_value, loader) in section_loaders.items():
            section_data = raw.get(section_name, default_value)
            try:
                parsed_sections[section_name] = loader(section_data, base)
            except ValidationError as exc:
                raise _validation_refusal(
                    exc, loc_prefix=(section_name,), source_path=source_path, document=raw
                ) from exc
            except ValueError as exc:
                raise _section_refusal(
                    section_name, str(exc), source_path=source_path, error_type="value_error"
                ) from exc

        if "workflow" in raw:
            workflow_section = raw["workflow"]
            if not isinstance(workflow_section, Mapping):
                raise _section_refusal(
                    "workflow",
                    "TOML section [workflow] must be a mapping with key 'mode'",
                    source_path=source_path,
                    error_type="dict_type",
                )
            try:
                parsed_sections["workflow"] = WorkflowConfig.model_validate(dict(workflow_section))
            except ValidationError as exc:
                raise _validation_refusal(
                    exc, loc_prefix=("workflow",), source_path=source_path, document=raw
                ) from exc

        try:
            cfg = cls.model_validate(
                parsed_sections,
                context={
                    "allow_dem_bootstrap": allow_dem_bootstrap,
                    "validation_context": context,
                },
            )
        except ValidationError as exc:
            raise _validation_refusal(exc, source_path=source_path, document=raw) from exc
        _resolve_calibration_parameter_names(cfg)
        return cfg

    @classmethod
    def from_snapshot(
        cls,
        snapshot: dict[str, Any],
        **overrides: Any,
    ) -> HydroModPyConfig:
        """Reconstruct a config from a stored JSON snapshot.

        The snapshot is migrated first: a key removed from the schema since the
        run was stored is dropped or moved, and one log line names it.

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
        stored = migrate_stored_config(snapshot, source="config snapshot")
        merged = _deep_merge(stored, overrides) if overrides else stored
        return cls.model_validate(merged)


# Resolve the config forward references (and wire the DI graph) lazily, the first
# time this module is loaded. ``import hydromodpy`` does not import this module
# (it is lazy), so the package import stays cheap; any real config use loads this
# module and triggers the full bootstrap once.
from hydromodpy.core.bootstrap_hook import (  # noqa: E402
    ensure_bootstrapped as _ensure_bootstrapped,
)

_ensure_bootstrapped()
