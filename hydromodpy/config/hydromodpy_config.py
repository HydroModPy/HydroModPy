"""Top-level Pydantic configuration object for HydroModPy.

Aggregates all sub-configs into a single hierarchical model.
Relative paths in the TOML are resolved against the TOML file location;
absolute paths are left as-is. Paths starting with ``~`` are expanded
to the user's home directory.

Usage::

    from hydromodpy.config import HydroModPyConfig

    cfg = HydroModPyConfig.from_toml(
        "examples/projects/01_simplified_example_presented_in_the_paper/project.toml"
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
from functools import partial
from pathlib import Path
from typing import Annotated, Any, ClassVar, Literal

from pydantic import Field, ValidationError, ValidationInfo, field_validator, model_validator

from hydromodpy.calibration.config import CalibrationConfig, apply_project_defaults
from hydromodpy.calibration.protocols import expand_calibration_protocol
from hydromodpy.config.config_migration import (
    _raw_flow_process_solver,
    migrate_sealed_config_doc,
)
from hydromodpy.config.section_loader import (
    _load_optional_calibration_section,
    _load_optional_mesh_section,
    _raw_declares_dem_source,
    load_geographic_section,
    load_optional_section,
    load_standard_section,
)
from hydromodpy.config.sites import SitesConfig
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.introspect import (
    collect_profile_violations,
    resolve_profile,
)
from hydromodpy.core.config_kit.profile import Profile, ProfileName
from hydromodpy.core.config_kit.written import written_payload
from hydromodpy.core.exceptions import (
    ConfigError,
    ConfigValidationError,
    IncompatibleCapabilitiesError,
)
from hydromodpy.core.logging import get_logger
from hydromodpy.core.site import SiteConfig
from hydromodpy.core.state.result_dirs import is_sealed_run_config, resolve_project_root
from hydromodpy.core.time.window import (
    build_simulation_time_boundaries,
    resolve_simulation_time_window,
)
from hydromodpy.core.toml_io.error_locator import (
    format_validation_error,
    json_pointer,
    validation_error_details,
)
from hydromodpy.core.toml_io.loader import config_base_dir, load_toml_with_base_config
from hydromodpy.core.toml_io.paths import assign, parse, source_of_effective_copy
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.data import DataManagersConfig
from hydromodpy.display.config import DisplayConfig
from hydromodpy.display.overview.config import OverviewConfig
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.physics.forcing.validation import refuse_an_impossible_recharge
from hydromodpy.physics.hydrology.soil_reservoir.config import (
    soil_reservoir_of,
    spinup_refusal,
    steady_start_refusal,
)
from hydromodpy.physics.transport.transport_config import TransportConfig
from hydromodpy.results.exporters.export_spec import ExportRequest, load_export_requests
from hydromodpy.results.metric_rule import MetricsConfig
from hydromodpy.results.publication import PublicationConfig
from hydromodpy.simulation.planning.config import SimulationConfig
from hydromodpy.simulation.planning.observation_config import ObservationConfig
from hydromodpy.simulation.spinup_config import SpinupConfig
from hydromodpy.solver.base.solver_config import (
    CustomBackend,
    SolverConfig,
    backend_following_the_process,
    solver_name_of_backend,
)
from hydromodpy.solver.field_property_mapping import k_tensor_parameter_ids
from hydromodpy.solver.modflow6.modflow6_config import Modflow6Config
from hydromodpy.solver.modflow_nwt.nwt import ModflowConfig
from hydromodpy.spatial.domain.depth_model_config import RASTER_DEPTH_MODEL_KINDS
from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.spatial.domain.layers_config import VerticalGridConfig
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.mesh.mesh_config import MeshConfig

logger = get_logger(__name__)

WorkflowMode = Literal["simulation", "calibration", "overview"]
ValidationContext = Literal["toml", "api", "snapshot"]
Verbosity = Literal["quiet", "normal", "verbose", "debug"]

ANALYSIS_SECTION_REFUSAL = (
    "[analysis] was removed: a comparison is hmp report compare over sealed runs, "
    "figures are hmp export <run> --regen figures on a run"
)
HYDROMETRY_SECTION_REFUSAL = (
    "a root [hydrometry] is not read: a run reads its stations from [data.hydrometry]"
)

RETIRED_WORKFLOW_MODES: dict[str, str] = {
    "testbed": (
        "workflow.mode = 'testbed' is gone: a case of a testbed is a recipe. List the "
        "catchments in [sites] and the variants in [sites.recipes], then hmp run the file."
    ),
    "comparison": (
        "workflow.mode = 'comparison' is gone: the legs of a comparison are recipes of "
        "one site in [sites.recipes]. Run them with hmp run, then compare the runs with "
        "hmp report compare <run> <run>."
    ),
}


class WorkflowConfig(HydroModelBase):
    """Workflow selector configuration."""

    mode: Annotated[WorkflowMode | None, Profile.USER] = Field(
        default=None,
        description=(
            "What `hmp run` does with the file. Unset, it follows from the sections: "
            "[calibration] calibrates, [overview] without [simulation] draws the "
            "overview, anything else simulates."
        ),
        json_schema_extra={
            "value_docs": {
                "simulation": ("Runs one forward simulation and writes its run directory."),
                "calibration": (
                    "Repeatedly proposes parameters, runs candidate simulations, "
                    "and records the calibration history."
                ),
                "overview": (
                    "Loads geographic and data context and renders review maps "
                    "without running a solver."
                ),
            }
        },
    )

    @field_validator("mode", mode="before")
    @classmethod
    def _name_the_replacement_of_a_retired_mode(cls, value: Any) -> Any:
        """Refuse a retired mode with what replaces it."""
        if isinstance(value, str) and value in RETIRED_WORKFLOW_MODES:
            raise ValueError(RETIRED_WORKFLOW_MODES[value])
        return value

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
        if getattr(process, "kind", None) == "flow" and getattr(process, "solvers", None):
            return str(process.solvers[0])
    solver_cfg = getattr(cfg, "solver", None)
    engine = getattr(solver_cfg, "backend_name", None) if solver_cfg is not None else None
    return str(engine) if engine else None


_ROOT_PERSISTENCE_REFUSAL = (
    "Section [persistence] is not read by any run. Write its keys under "
    "[simulation.results.persistence], which a run reads, and so does the run "
    "a calibration promotes."
)


_RETIRED_MESH_SECTIONS: dict[str, str] = {
    "mesh_catchment": (
        'Section [mesh_catchment] is replaced by [mesh]. Write engine = "triangle" or '
        '"voronoi" (the cells MODFLOW 6 ran on were chosen by sgrid.grid_dual), '
        "cell_size (was zone_meshing.global_size), river_cell_size and river_band (were "
        "zone_meshing.interface_size and interface_distance) and [mesh.families] (was "
        "constraints_mode and watershed_boundary). The cache, output, figure, "
        "hydraulic_properties and rivers keys are gone: the run caches its mesh and "
        "reads K from [flow.param.K]."
    ),
    "mesh_catchment_batch": (
        "Section [mesh_catchment_batch] has no replacement: [mesh] meshes the catchment "
        "of the project."
    ),
    "mesh_input": (
        'Section [mesh_input] is replaced by [mesh.triangle] path, with engine = "triangle" '
        'or "voronoi" in [mesh]. '
        "Its bundle_dir has no replacement."
    ),
}


_TESTBED_REFUSAL = (
    "a case of a testbed is a recipe: list the catchments in [sites] and the "
    "variants in [sites.recipes]."
)

RETIRED_SECTIONS: dict[str, str] = {
    "initializing": "Section [initializing] is no longer supported. Use [workspace] instead.",
    "modflow": (
        "Section [modflow] is no longer supported. "
        "Use [solver], [modflownwt], and [modflow6] sections instead."
    ),
    "capability_gallery": (
        "Section [capability_gallery] is no longer supported: the figures of "
        "a run are drawn again by hmp export <run> --regen figures."
    ),
    "analysis": ANALYSIS_SECTION_REFUSAL,
    "hydrometry": HYDROMETRY_SECTION_REFUSAL,
    "batch": (
        "Section [batch] is no longer supported. List the catchments in [sites] "
        "and the variants in [sites.recipes]."
    ),
    "testbed": "Section [testbed] is no longer supported: " + _TESTBED_REFUSAL,
    "persistence": _ROOT_PERSISTENCE_REFUSAL,
    **_RETIRED_MESH_SECTIONS,
    "regional_lab": (
        "Section [regional_lab] is not a HydroModPyConfig section. A regional "
        "lab is a [sites] project: list the catchments in [sites] and the "
        "variants in [sites.recipes]."
    ),
}
"""Root sections a file may no longer write, each with the sentence that refuses it.

A new retired section is one row here. ``_from_payload`` refuses the first one a
document writes, and a direct ``model_validate`` refuses it too.
"""


def _retired_section(data: Mapping[str, Any]) -> str | None:
    """Return the first retired root section a document declares, or None."""
    return next((name for name in RETIRED_SECTIONS if name in data), None)


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


_LAYERS_PATH = "domain.layers"

_OLDER_LAYERING = (
    "The [modflow6.sgrid.vertical] or [modflownwt.sgrid.vertical] of an older file, "
    "as a table or as a phase override, is read as [domain.layers]."
)


def _boussinesq_layering_refusals(layers: VerticalGridConfig, calibration: Any) -> list[str]:
    """Say why Boussinesq refuses the layering of the file and of each calibration phase."""
    from hydromodpy.solver.boussinesq.solver_contract import layering_refusal

    written = [("[domain.layers]", layers)]
    for phase in getattr(calibration, "phases", None) or ():
        phase_layers = _layering_of_the_phase(layers, getattr(phase, "overrides", None) or {})
        if phase_layers is not None:
            where = f"the domain.layers override of calibration phase {phase.name!r}"
            written.append((where, phase_layers))
    refusals: list[str] = []
    for where, read in written:
        refusal = layering_refusal(read, written_in=where)
        if refusal is not None:
            # Layers by surfaces came after the solver tables moved: no older file holds them.
            older = "" if read.genmtd_lay == "surfaces" else f" {_OLDER_LAYERING}"
            refusals.append(refusal + older)
    return refusals


def _layering_of_the_phase(
    layers: VerticalGridConfig, overrides: Mapping[str, Any]
) -> VerticalGridConfig | None:
    """Return the layering a calibration phase runs, with its ``domain.layers`` overrides.

    None when the phase writes no such override, or one that does not validate:
    the preflight names an override it cannot write.
    """
    written = {
        str(key): value
        for key, value in overrides.items()
        if key == _LAYERS_PATH or str(key).startswith(f"{_LAYERS_PATH}.")
    }
    if not written:
        return None
    table = written.pop(_LAYERS_PATH, layers.model_dump(exclude_unset=True))
    if not isinstance(table, Mapping):
        return None
    payload = dict(table)
    payload.update({key.removeprefix(f"{_LAYERS_PATH}."): value for key, value in written.items()})
    try:
        return VerticalGridConfig.model_validate(payload)
    except ValueError:
        return None


def _with_calibration_defaults(raw: dict[str, Any], *, source_path: Path | None) -> dict[str, Any]:
    """Write ``[site] gauge`` and ``[metrics] window`` into ``[calibration]``.

    The defaults the calibration runners apply
    (:func:`~hydromodpy.calibration.config.apply_project_defaults`), applied
    here too, so a document that leaves ``observes`` or ``window``
    to the project loads the same way through ``from_toml`` and
    ``hmp config check``. A written station that is not the gauge is refused.
    """
    calibration = raw.get("calibration")
    if not isinstance(calibration, Mapping):
        return raw
    site, metrics = raw.get("site"), raw.get("metrics")
    try:
        raw["calibration"] = apply_project_defaults(
            calibration,
            site_gauge=site.get("gauge") if isinstance(site, Mapping) else None,
            metrics_window=metrics.get("window") if isinstance(metrics, Mapping) else None,
        )
    except ConfigError as exc:
        raise _section_refusal(
            "calibration", str(exc), source_path=source_path, error_type="value_error"
        ) from exc
    return raw


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


def _optional_model(model_cls: type[HydroModelBase]) -> Callable[[Any, Path], Any]:
    """Return the loader of an optional section that names no file.

    The section is validated as written: its relative paths, if any, are read
    from the project root by the code that opens them, not rebased here.
    """
    return lambda data, _base: None if data is None else model_cls.model_validate(data)


def _derive_name_from_filename(toml_path: Path) -> str:
    """Derive a simulation name from a TOML filename.

    ``run_steady_nwt.toml`` -> ``steady_nwt``
    ``config.toml`` -> ``config``
    """
    stem = source_of_effective_copy(toml_path).stem
    return re.sub(r"^run_", "", stem)


def _resolve_calibration_parameter_names(cfg: Any) -> None:
    """Give every calibration parameter the path its name points at.

    A parameter that names a quantity rather than a path is resolved against
    the catalog this very configuration exposes, so the search writes into a
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


REAL_CATCHMENT_DEFINITIONS: frozenset[str] = frozenset(
    {"from_outlet_coord", "from_polyg_shp", "dem"}
)
"""Values of ``geographic.catchment.kind`` that model a real catchment, named by a site."""


def require_site_for_real_catchment(config: Any) -> None:
    """Refuse a real catchment that no site names.

    A run on a real catchment is grouped, compared and published by its site,
    never by the name of its project folder. A synthetic domain has no site,
    and a ``[sites]`` project takes the site of each case from its table row.
    Raises :class:`~hydromodpy.core.exceptions.ConfigError` naming
    ``catch_def`` and the key to write.
    """
    if getattr(config, "site", None) is not None or getattr(config, "sites", None) is not None:
        return
    geographic = getattr(config, "geographic", None)
    catch_def = getattr(geographic, "catch_def", None) if geographic is not None else None
    if catch_def not in REAL_CATCHMENT_DEFINITIONS:
        return
    raise ConfigError(
        f"geographic.catchment.kind = {catch_def!r} models a real catchment, and no "
        '[site] names it. Add [site] with name = "<catchment>" (letters, digits and '
        'underscores), and gauge = "<station>" when a station measures it.'
    )


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
        default_factory=WorkflowConfig,
        description=(
            "Workflow configuration: `workflow.mode` ('simulation', 'calibration' or "
            "'overview'), the console verbosity and the profiler. The mode is optional; "
            "unset, the sections of the file say what `hmp run` does."
        ),
        examples=[{"mode": "simulation"}],
    )
    workspace: Annotated[WorkspaceConfig, Profile.DEV] = Field(
        description=(
            "Where the shared input data of the project are read and cached. The "
            "project root is the folder that holds project.toml, never a key of the "
            "file."
        ),
        examples=[{"root": "../.."}],
    )
    site: Annotated[SiteConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "The catchment this project models: its name, label, gauge and registry "
            "URI. Required when geographic.catchment.kind declares a real "
            "catchment (from_outlet_coord, from_polyg_shp or dem); a synthetic domain "
            "has none. Refused beside [sites], where each case takes its site from a "
            "row of the site table."
        ),
        examples=[{"name": "nancon", "gauge": "J0014010", "uri": "hubeau:J0014010"}],
    )
    sites: Annotated[SitesConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "The catchments of a campaign and the recipes run on each of them: the "
            "plan is sites x recipes, one case <site>-<recipe> per pair. Refused "
            "beside [site]."
        ),
        examples=[{"table": "sites.csv", "recipes": {"base": "project.toml"}}],
    )
    metrics: Annotated[MetricsConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Where and when a run is scored after it ends: the station (default "
            "[site] gauge) and the window. Without a window the scores are left empty."
        ),
        examples=[{"window": {"start": "2001-01-01", "end": "2002-12-31"}}],
    )
    publication: Annotated[PublicationConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Licence, creators and attribution written into every copy hmp publish "
            "makes of a result. hmp publish --public refuses a project without a "
            "licence."
        ),
        examples=[{"license": "etalab-2.0", "creators": ["A. Author"]}],
    )
    geographic: Annotated[GeographicConfig, Profile.USER] = Field(
        description="Configuration block for geographic and watershed delineation parameters."
    )
    domain: Annotated[DomainConfig, Profile.USER] = Field(
        default_factory=DomainConfig,
        description=(
            "Domain configuration: the depth of the aquifer ([domain.depth_model]), its "
            "layering ([domain.layers], read by every solver) and the spatial-support "
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
            "MODFLOW-NWT settings: the top sampling of the grid "
            "([modflownwt.sgrid.top_sampling]), the package options "
            "([modflownwt.process_specific]) and the solver settings "
            "([modflownwt.runtime.<package>], expert keys)."
        ),
    )
    modflow6: Annotated[Modflow6Config, Profile.USER] = Field(
        default_factory=Modflow6Config,
        description=(
            "MODFLOW 6 settings: the top sampling of the grid "
            "([modflow6.sgrid.top_sampling]), the package options ([modflow6.process_specific]) "
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

    # Lightweight workflows (without simulation)
    overview: Annotated[OverviewConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional overview report settings loaded from the [overview] "
            "section.  When present without [simulation], triggers the "
            "data-overview (watershed identity card) workflow."
        ),
    )
    mesh: Annotated[MeshConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional mesh settings loaded from the [mesh] section: which engine meshes "
            "the model ('regular', 'triangle' or 'voronoi') and how fine. Without the "
            "section the 'regular' engine meshes the model with the DEM pixels. The "
            "solver must read the cells of the engine, which is checked before any "
            "meshing."
        ),
        json_schema_extra=field_metadata(
            renamed_from=[
                "mesh_catchment",
                "mesh_input",
                "modflow6.sgrid.planar",
                "modflownwt.sgrid.planar",
                "modflow6.sgrid.grid_dual",
                "modflownwt.sgrid.grid_dual",
            ]
        ),
    )
    calibration: Annotated[CalibrationConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional calibration settings loaded from the [calibration] "
            "section.  When present, triggers the calibration workflow. The section "
            "and the shape of CalibrationReport are experimental until the rework of "
            "the calibration is published."
        ),
        json_schema_extra=field_metadata(stability="experimental"),
    )
    spinup: Annotated[SpinupConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional cyclic spin-up settings loaded from the [spinup] section. "
            "Drives 'hmp spinup': repeat a forcing window, restart each cycle from "
            "the previous state, until the heads and the lake stage converge."
        ),
    )

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        "testbed": _TESTBED_REFUSAL,
        "analysis": ANALYSIS_SECTION_REFUSAL,
        "hydrometry": HYDROMETRY_SECTION_REFUSAL,
    }

    @model_validator(mode="before")
    @classmethod
    def _default_workspace_for_direct_validation(cls, data: Any) -> Any:
        """Give a direct ``model_validate`` caller the current folder as project root.

        A file never names its project root: the loader derives it from where the
        file sits. A Python caller that validates a mapping without one works in
        the current folder.
        """
        if not isinstance(data, Mapping):
            return data
        payload = dict(data)
        workspace = payload.get("workspace")
        if workspace is None:
            payload["workspace"] = {"project_root": "."}
        elif isinstance(workspace, Mapping) and not workspace.get("project_root"):
            payload["workspace"] = {**workspace, "project_root": "."}
        return payload

    @model_validator(mode="before")
    @classmethod
    def _refuse_retired_sections(cls, data: Any) -> Any:
        """Refuse a retired root section with what replaces it."""
        if isinstance(data, Mapping):
            name = _retired_section(data)
            if name is not None and name not in cls.model_refused_keys:
                raise ValueError(RETIRED_SECTIONS[name])
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
        flow = _raw_flow_process_solver(data.get("simulation"))
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
        mesh. The rule is ``MeshConfig.requires_river_trace``, the one the
        geographic step reads.
        """
        geographic = self.geographic
        if geographic.uses_synthetic_geographic():
            return
        river_network = geographic.river_network
        if bool(river_network.enabled):
            return
        mesh = self.mesh
        if mesh is None:
            return
        active_bc = {str(name).lower() for name in self.flow.active_bc}
        if not mesh.requires_river_trace(active_bc=active_bc, synthetic=False):
            return
        if mesh.triangle is not None and mesh.triangle.path is not None:
            needed_by = "The 'stream' boundary on a [mesh.triangle] path mesh"
        elif mesh.families.rivers == "cell":
            needed_by = f"[mesh] engine = {mesh.engine!r} with families.rivers = 'cell'"
        else:
            needed_by = "[[mesh.refinement_zone]] where = 'height_above_stream'"
        refusal = river_network.missing_threshold_refusal(needed_by=needed_by)
        if refusal is not None:
            raise ValueError(refusal)

    def _check_the_solver_reads_the_mesh(self, solver_cfg: SolverConfig) -> None:
        """Refuse a solver paired with a mesh engine whose cells it cannot read.

        Raised while the document is read, before any step of the pipeline runs.
        The engine is the one of ``[mesh]``, or ``regular`` when the section is
        absent.
        """
        from hydromodpy.solver.base import registry as solver_registry
        from hydromodpy.spatial.mesh import registry as mesh_registry
        from hydromodpy.spatial.mesh.port import ANY_PLANAR_ENGINE, engine_accepted

        mesh = self.mesh
        engine_id = mesh.engine if mesh is not None else mesh_registry.DEFAULT_ENGINE_ID
        solver_name = solver_cfg.backend_name

        def reads(accepted: frozenset[str]) -> bool:
            # The engine class is loaded only when the solver accepts engines by capability.
            if engine_id in accepted:
                return True
            return ANY_PLANAR_ENGINE in accepted and engine_accepted(
                accepted, engine_id, mesh_registry.get(engine_id).capabilities
            )

        accepted = solver_registry.accepted_meshes("flow", solver_name)
        if reads(accepted):
            return
        names = ", ".join(sorted(accepted - {ANY_PLANAR_ENGINE}))
        if ANY_PLANAR_ENGINE in accepted:
            names += " and any engine with planar cells"
        readers = sorted(
            name
            for _, name in solver_registry.pairs_for_process("flow")
            if reads(solver_registry.accepted_meshes("flow", name))
        )
        origin = "" if mesh is not None and "engine" in mesh.model_fields_set else " (the default)"
        raise ValueError(
            f"solver {solver_name!r} reads the meshes of the engines {names}, and mesh.engine "
            f"is {engine_id!r}{origin}. Write [mesh] engine with one of the engines the solver "
            f"reads, or run a solver that reads {engine_id!r}"
            + (f" ({', '.join(readers)})." if readers else ".")
        )

    def _check_the_layering(self, solver_cfg: SolverConfig | None, *, sealed: bool) -> None:
        """Refuse a layering its data or its solver cannot serve; warn on a coarse K profile.

        Boussinesq solves one layer and reads no ``[domain.layers]``, so more
        layers or a layering by surfaces are refused for it, in the file and in
        the overrides of a calibration phase. A sealed run only warns. A
        layering by surfaces reads its rasters by name from ``[data.layer_base]``,
        and the two lists must match. MODFLOW-NWT has no vertical pass-through
        cell, so it reads such a layering only when a thin layer keeps its minimum
        thickness. A vertical profile of K on one layer is summed up by K at the
        middle of the column: with H/d = 2.5 the transmissivity is off by -22 % to
        +75 % with the water table, and five equal layers bring it near -1 %.
        """
        domain = self.domain
        layers = getattr(domain, "layers", None)
        if layers is None:
            return
        engine_value = _declared_flow_engine(self)
        if engine_value == "boussinesq":
            for refusal in _boussinesq_layering_refusals(layers, self.calibration):
                if not sealed:
                    raise ValueError(refusal)
                logger.warning("%s This sealed run was solved on one layer.", refusal)
        layer_base = self.data.layer_base
        declared = set() if layer_base is None else {source.name for source in layer_base.sources}
        read = set(layers.base_surface_names)
        if read - declared:
            raise ValueError(
                f"[domain.layers] reads the base surfaces {sorted(read - declared)}, and "
                "[data.layer_base] does not declare them. Add one "
                "[[data.layer_base.sources]] entry per name, with its raster."
            )
        if declared - read:
            raise ValueError(
                f"[data.layer_base] declares {sorted(declared - read)}, and no layer of "
                "[domain.layers] reads them as its surface. Give a layer that surface, or "
                "remove the entries."
            )
        if engine_value == "modflow_nwt" and layers.has_pass_through_cells:
            raise ValueError(
                "[domain.layers] pinch_out = 'pass_through' makes a thin layer a vertical "
                "pass-through cell (idomain -1), which MODFLOW-NWT does not have. Write "
                "pinch_out = 'keep_min_thickness', or run MODFLOW 6."
            )
        params = self.flow.param or {}
        for param_id, param in params.items():
            profile = getattr(param, "field_vertical_profile", None)
            if str(param_id).lower() != "k" or profile is None or profile.kind == "none":
                continue
            if engine_value == "boussinesq":
                logger.warning(
                    "flow.param.%s has a vertical profile, and boussinesq reads K at the "
                    "top of the aquifer only, one value per column: the profile below the "
                    "top is not read.",
                    param_id,
                )
            elif layers.layer_count < 5:
                logger.warning(
                    "flow.param.%s has a vertical profile and [domain.layers] builds %d "
                    "layer(s). One layer sums the profile up by K at mid-column, off by "
                    "-22 %% to +75 %% of the transmissivity at H/d = 2.5 as the water table "
                    "moves; five equal layers bring it near -1 %%. Use at least five layers.",
                    param_id,
                    layers.layer_count,
                )

    def _check_the_conductivity_tensor(self, solver_cfg: SolverConfig | None) -> None:
        """Refuse a K tensor its solver cannot read, and an angle with a depth profile.

        K22 and the three angles of the tensor reach the NPF package of MODFLOW 6
        only. MODFLOW-NWT and Boussinesq would drop them in silence, so the load
        refuses them there. An angle is a direction: a vertical profile would
        scale it with depth, which has no meaning.
        """
        params = self.flow.param or {}
        tensor_ids = k_tensor_parameter_ids(params)
        if not tensor_ids:
            return
        for param_id in tensor_ids:
            profile = getattr(params[param_id], "field_vertical_profile", None)
            if param_id.startswith("angle") and profile is not None and profile.kind != "none":
                raise ValueError(
                    f"flow.param.{param_id} has a vertical profile, which would scale the "
                    "angle with depth. Remove [flow.param."
                    f"{param_id}.field_vertical_profile]; give the angle per zone instead."
                )
        engine_value = _declared_flow_engine(self)
        if engine_value in {"modflow_nwt", "boussinesq"}:
            raise ValueError(
                f"flow.param sets {', '.join(tensor_ids)}, the K tensor past K and Kv, "
                f"which only MODFLOW 6 reads; {engine_value} would drop it. Remove these "
                "parameters, or run MODFLOW 6."
            )

    def _check_cell_addressing_needs_a_regular_mesh(self) -> None:
        """Refuse a ``[lay, row, col]`` address when the mesh has no rows and columns.

        A well (``location.kind = "cell"``) or an explicit SFR reach
        (``reaches[].cell``) names its cell by layer, row and column. Only the
        ``regular`` engine has rows and columns: on a triangle or Voronoi mesh the
        address names no cell, and the build would stop on it after meshing. The
        engine is the one of ``[mesh]``, or ``regular`` when the section is absent.
        """
        from hydromodpy.spatial.mesh import registry as mesh_registry

        mesh = self.mesh
        engine_id = mesh.engine if mesh is not None else mesh_registry.DEFAULT_ENGINE_ID
        if engine_id == "regular":
            return
        sinks_sources = self.flow.sinks_sources
        addressed: list[str] = []
        for well_id, well in (getattr(sinks_sources, "wells", None) or {}).items():
            if getattr(getattr(well, "location", None), "kind", None) == "cell":
                addressed.append(f"flow.sinks_sources.wells.{well_id}.location")
        for network_id, network in (getattr(sinks_sources, "sfr", None) or {}).items():
            for index, reach in enumerate(getattr(network, "reaches", None) or []):
                if getattr(getattr(reach, "cell", None), "kind", None) == "cell":
                    addressed.append(f"flow.sinks_sources.sfr.{network_id}.reaches[{index}].cell")
        if addressed:
            raise ValueError(
                f"A cell is addressed by [lay, row, col] at {', '.join(addressed)}, and "
                f"mesh.engine is {engine_id!r}: only the 'regular' engine has rows and "
                "columns. Locate a well by coordinates (absolute_xy or relative_xy), or "
                'write [mesh] engine = "regular".'
            )

    @model_validator(mode="after")
    def _name_the_site_of_a_real_catchment(self) -> HydroModPyConfig:
        """Refuse a real catchment without [site].

        The rule holds for a file read from disk and for a Python caller alike.
        """
        try:
            require_site_for_real_catchment(self)
        except ConfigError as exc:
            raise ValueError(exc.message) from exc
        return self

    @model_validator(mode="after")
    def _take_the_site_gauge(self, info: ValidationInfo) -> HydroModPyConfig:
        """Fill the station sources from [site] gauge; refuse a station other than it.

        A sealed document is read as it was run, so ``[metrics] station`` is not checked.
        """
        from hydromodpy.core.site.config import resolve_gauge
        from hydromodpy.data.sites.gauge import apply_site_gauge

        context = info.context if isinstance(info.context, Mapping) else {}
        try:
            apply_site_gauge(self.data, self.site)
            if context.get("validation_context") != "snapshot":
                station = getattr(self.metrics, "station", None)
                resolve_gauge(self.site, station, field="metrics.station")
        except ConfigError as exc:
            raise ValueError(exc.message) from exc
        return self

    def _check_the_metrics_window_meets_the_run(self, *, sealed: bool) -> None:
        """Refuse a ``[metrics] window`` that shares no day with ``[simulation.time]``.

        A sealed document, the frozen config of a run already on disk, is read
        as it was run: the window only warns, and the run has no score.
        """
        window = getattr(self.metrics, "window", None)
        run = self.simulation.time
        run_start = getattr(run, "start_datetime", None)
        run_end = getattr(run, "end_datetime", None)
        if window is None or run_start is None or run_end is None:
            return
        if window.end >= run_start.date() and window.start <= run_end.date():
            return
        missed = (
            f"[metrics] window runs from {window.start} to {window.end} and shares no "
            f"day with [simulation.time], which runs from {run_start.date()} to "
            f"{run_end.date()}"
        )
        if sealed:
            logger.warning("%s: this sealed run has no score.", missed)
            return
        raise ValueError(
            f"{missed}: the run would be scored on nothing. Move the window inside the "
            "run, or remove it."
        )

    @model_validator(mode="after")
    def _check_cross_section_coherence(self, info: ValidationInfo) -> HydroModPyConfig:
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
        * ``[domain.layers]`` by surfaces reads only bases ``[data.layer_base]``
          declares, ``[data.layer_base]`` declares only bases a layer reads, and
          MODFLOW-NWT reads it only with ``pinch_out = "keep_min_thickness"``.
          A vertical K profile on fewer than five layers is warned about.
        * ``solver.backend = "boussinesq"`` ⇒ ``[domain.layers]``, and the
          ``domain.layers`` overrides of a calibration phase, build one layer and
          not by surfaces, since Boussinesq solves one layer and reads no layering.
        * ``workflow.mode = "overview"`` ⇒ an ``[overview]`` section is declared:
          without it the workflow delineates and loads, then writes no report.
        * ``[metrics] window`` shares at least one day with ``[simulation.time]``,
          else the run is scored on nothing.
        """
        if self.site is not None and self.sites is not None:
            raise ValueError(
                "[site] and [sites] are both declared: a [sites] project takes the site "
                "of each case from its row of the site table. Remove [site], or remove "
                "[sites] to model one catchment."
            )

        context = info.context if isinstance(info.context, Mapping) else {}
        sealed = context.get("validation_context") == "snapshot"
        self._check_the_metrics_window_meets_the_run(sealed=sealed)

        if self.workflow.mode == "overview" and (self.overview is None):
            raise ValueError(
                "workflow.mode = 'overview' needs an [overview] section: it names the card and "
                "holds its window and panels. Add the section, with at least a name."
            )

        data_cfg = self.data
        if data_cfg.inference_mode == "strict":
            if not data_cfg.types:
                raise ValueError(
                    "data.inference_mode='strict' requires at least one explicit "
                    "data type in data.types"
                )

        depth_kind = self.domain.depth_model.kind
        if depth_kind in RASTER_DEPTH_MODEL_KINDS and data_cfg.substratum is None:
            raise ValueError(
                f"domain.depth_model kind = {depth_kind!r} reads the raster declared under "
                "[data.substratum]; declare it with one custom source."
            )

        nwt_top_sampling = self.modflownwt.sgrid.top_sampling
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

        calibration_cfg = self.calibration
        flow_cfg = self.flow
        if calibration_cfg is not None:
            if not flow_cfg.param_list:
                raise ValueError(
                    "[calibration] requires flow.param_list to declare at least "
                    "one tunable parameter"
                )

        solver_cfg = self.solver
        if isinstance(solver_cfg.backend, CustomBackend):
            # A name that is not built in becomes a custom backend. Check it
            # resolves now, or the checks below would refuse a typo with a
            # message about a boundary or a capability.
            solver_cfg.validate_registry()
        # A transport runs when [[simulation.process]] declares one; the
        # [transport] section is always there, filled with its defaults.
        engine_value = _declared_flow_engine(self)
        processes = self.simulation.process or []
        transport_solvers = [
            name
            for process in processes
            if getattr(process, "kind", None) == "transport"
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

        from hydromodpy.physics.flow.boundary_condition_registry import boundary_definition

        active_bc = {str(name).lower() for name in flow_cfg.active_bc}
        sinks_sources = flow_cfg.sinks_sources

        # Every active boundary must be supported by the chosen backend, or it
        # would be silently ignored at build time (lake/sfr on NWT or
        # Boussinesq were accepted then dropped).
        for bc_id in sorted(active_bc):
            definition = boundary_definition(bc_id)
            if definition is not None and not definition.supports_backend(str(engine_value)):
                supported = ", ".join(definition.supported_backends)
                raise IncompatibleCapabilitiesError(
                    f"solver.backend={engine_value!r} does not support the '{bc_id}' "
                    f"boundary (supported by: {supported}); it would be silently ignored. "
                    f"Use a supported backend, or remove the '{bc_id}' table, or write "
                    "enabled = false in it."
                )

        # A hotstart is read by the backends that declare they can read one.
        # Elsewhere the key was accepted and never looked at, so the run
        # started from the declared initial condition and said nothing.
        if flow_cfg.restart_from:
            from hydromodpy.solver.base.registry import capabilities

            if RESTART_CAPABILITY not in capabilities("flow", str(engine_value)):
                raise IncompatibleCapabilitiesError(
                    f"solver.backend={engine_value!r} does not read flow.restart_from; "
                    "it would be silently ignored and the run would start from "
                    "flow.ic instead. Use a backend that declares "
                    f"{RESTART_CAPABILITY!r}, or drop flow.restart_from."
                )

        # A steady pre-solve or a cyclic spin-up writes its own heads after the
        # hotstart is read, so the restart would be overwritten and unused.
        head_ic = getattr(getattr(flow_cfg, "ic", None), "h", None)
        ic_kind = str(getattr(head_ic, "kind", ""))
        if flow_cfg.restart_from and ic_kind in {
            "steady_state",
            "spinup_cyclic",
        }:
            raise ValueError(
                f"flow.restart_from is set and flow.ic.kind = {ic_kind!r} computes "
                "its own initial heads, which would overwrite the restart without "
                "a message. Write a flow.ic of kind 'top' (or any kind that is not "
                "'steady_state' or 'spinup_cyclic') to start from the restart, or "
                "drop flow.restart_from to keep the computed start."
            )

        # A cyclic spin-up repeats the run's own period inside the run. A
        # backend that cannot do that would start from flow.ic and report a
        # settled antecedent it never computed.
        if str(getattr(head_ic, "kind", "")) == "spinup_cyclic":
            from hydromodpy.solver.base.registry import capabilities

            if CYCLIC_SPINUP_CAPABILITY not in capabilities("flow", str(engine_value)):
                raise IncompatibleCapabilitiesError(
                    f"flow.ic.kind='spinup_cyclic' repeats the simulated period until "
                    f"the state settles, and solver.backend={engine_value!r} cannot: it "
                    "would start from the declared initial condition and say nothing. "
                    f"Use a backend that declares {CYCLIC_SPINUP_CAPABILITY!r}, or run "
                    "the cycling outside the run with `hmp spinup` and point "
                    "flow.restart_from at its result."
                )

        # Flow barriers and dam cutoff walls are a MODFLOW 6-only addon.
        barriers = getattr(sinks_sources, "flow_barriers", None) or {}
        has_cutoff = any(
            getattr(lake_cfg, "cutoff_wall", None) is not None
            for lake_cfg in sinks_sources.enabled_lakes().values()
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
                    "[flow.sinks_sources.recharge.soil] computes a recharge and its table "
                    "says enabled = false, so MODFLOW would receive none: remove "
                    "enabled = false, or remove the soil section."
                )

            soil_active_bc = {
                str(name).lower() for name in getattr(flow_cfg, "active_bc", []) or []
            }
            if "lake" in soil_active_bc and "sfr" not in soil_active_bc:
                raise ValueError(
                    "[flow.sinks_sources.lakes] declares a lake with no stream network: in "
                    "soil mode the water that seeps out of the ground reaches a lake "
                    "only through the stream network, so the lake would receive "
                    "none of it. Declare a [flow.sinks_sources.sfr] network, or remove "
                    "[flow.sinks_sources.recharge.soil] and load [data.runoff] as before."
                )
            if "lake" in soil_active_bc:
                soil_sinks = getattr(flow_cfg, "sinks_sources", None)
                soil_sfr = getattr(soil_sinks, "sfr", None) or {}
                items = soil_sfr.items() if hasattr(soil_sfr, "items") else []
                for network_id, network in items:
                    flag = (
                        network.get("route_drainage", True)
                        if isinstance(network, dict)
                        else getattr(network, "route_drainage", True)
                    )
                    if flag is False:
                        raise ValueError(
                            f"[flow.sinks_sources.sfr.{network_id}] sets route_drainage = "
                            "false with a lake and [flow.sinks_sources.recharge.soil]: the "
                            "water of the drains would leave the model and the lake would "
                            "receive only its own rain. Remove route_drainage = false "
                            "(it is on by default)."
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

        declared_recharge = getattr(self.flow.sinks_sources, "recharge", None)
        if declared_recharge is not None:
            refuse_an_impossible_recharge(
                declared_recharge.peak_rate_mm_day(),
                label="flow.sinks_sources.recharge.values",
            )
            if (
                soil is None
                and "recharge" in set(getattr(data_cfg, "types", []) or [])
                and declared_recharge.peak_rate_mm_day() != 0.0
            ):
                raise ValueError(
                    f"flow.sinks_sources.recharge.values = {declared_recharge.values!r} would be "
                    "replaced by the series [data.recharge] loads, so the model would not read "
                    "it: remove values (write values__delete = true if a base file declares "
                    'it), or remove "recharge" from data.types to impose this rate.'
                )

        if soil is None and getattr(data_cfg, "soil_capacity", None) is not None:
            raise ValueError(
                "[data.soil_capacity] is read only by the soil reservoir, and this "
                "file declares no [flow.sinks_sources.recharge.soil]: declare the "
                "soil section, or remove [data.soil_capacity]."
            )

        self._check_the_layering(solver_cfg, sealed=sealed)
        self._check_the_conductivity_tensor(solver_cfg)

        # Last, so a fault of the solver itself is named before a mesh it would not read.
        self._check_the_solver_reads_the_mesh(solver_cfg)
        self._check_cell_addressing_needs_a_regular_mesh()
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

        Relative paths are resolved against the project root: the folder
        that holds ``project.toml`` above the file, else the folder of the
        root file of the ``base_config`` chain
        (:func:`hydromodpy.core.toml_io.loader.config_base_dir`). Absolute
        paths are left unchanged. Paths starting with ``~`` are expanded to
        the user's home directory.

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
        # A config written against an earlier schema still loads: the loader
        # migrates each file of the chain in memory. Reading never rewrites a file;
        # only `hmp doctor` does, and the warning says so.
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
            cfg = cls._from_payload(
                raw, base=config_base_dir(toml_path), context="toml", source_path=toml_path
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
        sealed: bool = False,
    ) -> HydroModPyConfig:
        """Load and validate configuration from a Python mapping.

        ``sealed`` reads the frozen config of a run already on disk: a check that
        refuses what a run cannot be scored on, or a layering Boussinesq would
        ignore, only warns there.
        """
        base = Path(base_dir).expanduser().resolve() if base_dir is not None else Path.cwd()
        return cls._from_payload(payload, base=base, context="snapshot" if sealed else "api")

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
        document = copy.deepcopy(dict(payload))
        if context == "snapshot":
            # A sealed config is read under the key names of today, before the
            # protocol is expanded: it compares the stages the run froze with the
            # ones it writes, and a stage frozen under an old key would differ.
            migrate_sealed_config_doc(document)
        try:
            raw = expand_calibration_protocol(document)
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
        raw = _with_calibration_defaults(raw, source_path=source_path)
        retired = _retired_section(raw)
        if retired is not None:
            raise _section_refusal(retired, RETIRED_SECTIONS[retired], source_path=source_path)
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

        # The project root is never a key of a file: it is the folder that holds
        # project.toml above the file, else the folder of the file. A Python caller
        # may pass it. HMP_PROJECT_ROOT wins over both (used by test infra).
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
        if context == "toml" and "project_root" in workspace_section:
            message = (
                "[workspace] project_root is not a key of a file: the project root is "
                "the folder that holds project.toml (or the folder of this file). "
                "Delete the line."
            )
            raise ConfigValidationError(
                f"{source_path}: {message}" if source_path is not None else message,
                source=None if source_path is None else str(source_path),
                details=(
                    {
                        "pointer": json_pointer(("workspace", "project_root")),
                        "loc": "workspace.project_root",
                        "msg": message,
                        "type": "extra_forbidden",
                    },
                ),
            )
        env_project_root = os.environ.get("HMP_PROJECT_ROOT")
        if env_project_root:
            workspace_section["project_root"] = str(Path(env_project_root).expanduser().resolve())
        elif context == "toml":
            workspace_section["project_root"] = str(resolve_project_root(base))
        elif not workspace_section.get("project_root"):
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

        sealed = context == "snapshot" or (
            source_path is not None and is_sealed_run_config(source_path)
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
                lambda data, b: DataManagersConfig.from_toml_section(
                    data, base_dir=b, workspace_data_dir=workspace_data_dir
                ),
            ),
            "flow": (
                {},
                lambda data, b: FlowConfig.from_toml_section(
                    {} if data is None else data, base_dir=b, workspace_data_dir=workspace_data_dir
                ),
            ),
            "transport": ({}, _std(TransportConfig)),
            "simulation": ({}, _std(SimulationConfig)),
            "solver": ({}, _std(SolverConfig)),
            "modflownwt": ({}, _std(ModflowConfig)),
            "modflow6": ({}, _std(Modflow6Config)),
            "display": ({}, _std(DisplayConfig)),
            "export": ([], lambda data, _b: load_export_requests(data)),
            "observation": ({}, _std(ObservationConfig)),
            "overview": (None, lambda data, b: load_optional_section(data, OverviewConfig, b)),
            "mesh": (None, _load_optional_mesh_section),
            "calibration": (None, partial(_load_optional_calibration_section, sealed=sealed)),
            "spinup": (None, lambda data, b: load_optional_section(data, SpinupConfig, b)),
            "site": (None, _optional_model(SiteConfig)),
            "sites": (None, _optional_model(SitesConfig)),
            "metrics": (None, _optional_model(MetricsConfig)),
            "publication": (None, _optional_model(PublicationConfig)),
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
        snapshot: Mapping[str, Any],
        *,
        changes: Mapping[str, Any] | None = None,
    ) -> HydroModPyConfig:
        """Reconstruct a config from the frozen configuration of a run.

        The snapshot is read as stored: a key removed from the schema since the
        run was stored is refused, as in a file. A snapshot that names its
        project (``[workspace] project_root``) is read as its ``config.toml``
        is: relative paths from the project root, bare names in ``data/`` of
        its workspace, so a run frozen in one workspace reruns in another.

        Parameters
        ----------
        snapshot : Mapping
            The frozen ``config.toml`` of a run, as a mapping.
        changes : Mapping, optional
            Values to set before validation, by dotted path: the grammar of
            ``--set`` (:func:`hydromodpy.core.toml_io.paths.parse`).

        Returns
        -------
        HydroModPyConfig
        """
        merged = copy.deepcopy(dict(snapshot))
        for dotted, value in (changes or {}).items():
            assign(merged, dotted, value)
        workspace = merged.get("workspace")
        project_root = workspace.get("project_root") if isinstance(workspace, Mapping) else None
        if project_root:
            return cls.from_dict(merged, base_dir=project_root, sealed=True)
        return cls.model_validate(merged, context={"validation_context": "snapshot"})

    def with_changes(self, changes: Mapping[str, Any]) -> HydroModPyConfig:
        """Return this configuration with *changes* set, by dotted path, and validated.

        This is the one way a configuration takes a change after it is built: a
        keyword override of a run, a rerun. The whole document is validated, so
        the cross-section checks see the change. The result shares every section
        no change touches with this configuration: a built domain or flow compares
        its section by identity to know whether it still describes the run.
        """
        validated = type(self).from_snapshot(written_payload(self), changes=changes)
        touched = {parse(dotted).parts[0] for dotted in changes}
        return self.model_copy(update={name: getattr(validated, name) for name in touched})


# Resolve the config forward references (and wire the DI graph) lazily, the first
# time this module is loaded. ``import hydromodpy`` does not import this module
# (it is lazy), so the package import stays cheap; any real config use loads this
# module and triggers the full bootstrap once.
from hydromodpy.core.runtime.bootstrap_hook import (  # noqa: E402
    ensure_bootstrapped as _ensure_bootstrapped,
)

_ensure_bootstrapped()
