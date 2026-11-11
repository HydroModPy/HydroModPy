"""Top-level Pydantic configuration object for HydroModPy.

Aggregates all sub-configs into a single hierarchical model.
Relative paths in the TOML are resolved against the TOML file location;
absolute paths are left as-is. Paths starting with ``~`` are expanded
to the user's home directory.

Usage::

    from hydromodpy.config.hydromodpy_config import HydroModPyConfig

    cfg = HydroModPyConfig.from_toml("project.toml")
    cfg.workspace.project_root
    cfg.geographic.catch_def
    cfg.data.dem.sources
    cfg.domain.zone_ids
    cfg.data.geology.id
    cfg.flow.param["K"]
    cfg.solver.options_of("modflow_nwt").process_specific.vka

``from_toml`` is the check of ``config/check.py`` with ``partial=False``, followed by the
building of the root. ``from_dict`` and ``from_json`` read their document the way a file is
read, with ``context="api"``, so they migrate it and refuse it like a file. They need a
``base_dir``, which has no default because a mapping has no folder. ``from_snapshot``
rebuilds a config from the JSON snapshot stored with a run, whose paths are absolute.
``ROOT_CONFIG`` hands the root class and its two migrations to the core helpers as an
argument. The root builds its sections through ``section_loader.py`` and runs the rows of
``CROSS_RULES``, so it holds no rule of its own. ``[workflow].mode`` is optional: unset, the
sections of the file say what ``hmp run`` does, and a retired mode is refused with its
replacement (``RETIRED_WORKFLOW_MODES``). ``[site]`` and ``[sites]`` never coexist.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, ClassVar, Literal

from pydantic import (
    Field,
    ModelWrapValidatorHandler,
    PrivateAttr,
    ValidationInfo,
    field_validator,
    model_validator,
)

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
from hydromodpy.config.config_migration import (
    RETIRED_SGRID_KEYS,
    migrate_layers,
    migrate_merged_doc,
    migrate_sealed_config_doc,
)
from hydromodpy.config.cross_checks import check_against_the_solver
from hydromodpy.config.section_loader import (
    ANALYSIS_SECTION_REFUSAL,
    HYDROMETRY_SECTION_REFUSAL,
    RETIRED_SECTIONS,
    TESTBED_REFUSAL,
    _raw_declares_dem_source,
    align_solver_keys,
    build_document,
    raise_the_first,
    resolve_document,
    retired_section,
    validate_sections,
)
from hydromodpy.config.sites import SitesConfig
from hydromodpy.config.solver_supports import deduce_the_mesh_engine
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.introspect import (
    collect_profile_violations,
    resolve_profile,
)
from hydromodpy.core.config_kit.profile import Profile, ProfileName
from hydromodpy.core.config_kit.root import RootConfig
from hydromodpy.core.config_kit.said import say
from hydromodpy.core.config_kit.written import written_payload
from hydromodpy.core.exceptions import (
    ConfigError,
)
from hydromodpy.core.logging import get_logger
from hydromodpy.core.plugin_registry import check_registered_name
from hydromodpy.core.site.config import SiteConfig
from hydromodpy.core.state.names import fold_name
from hydromodpy.core.state.result_dirs import is_sealed_run_config, resolve_project_root
from hydromodpy.core.toml_io.paths import assign, parse
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.data.loading.config_schema import DataConfig
from hydromodpy.data.sites.gauge import apply_site_gauge
from hydromodpy.display.config import DisplayConfig
from hydromodpy.display.overview.config import OverviewConfig
from hydromodpy.mesh.mesh_config import MeshConfig
from hydromodpy.model.domain.domain_config import DomainConfig
from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.model.initial_config import SpinupConfig
from hydromodpy.model.transport.transport_config import TransportConfig
from hydromodpy.results.exporters.export_spec import ExportRequest
from hydromodpy.results.metric_rule import MetricsConfig
from hydromodpy.results.publication import PublicationConfig
from hydromodpy.schema.changes import FIRST_EDITION, editions
from hydromodpy.solver.base.observation_config import ObservationConfig
from hydromodpy.solver.base.simulation_config import SimulationConfig
from hydromodpy.solver.base.solver_config import SolverConfig

logger = get_logger(__name__)

WorkflowMode = Literal["simulation", "calibration", "overview"]
ValidationContext = Literal["toml", "request", "api", "snapshot"]
Verbosity = Literal["quiet", "normal", "verbose", "debug"]

RETIRED_WORKFLOW_MODES: dict[str, str] = {
    "testbed": (
        "workflow.mode = 'testbed' is gone: a case of a testbed is a recipe. List the "
        "catchments in [sites] and the variants in [sites.recipes], then hmp run the file."
    ),
    "comparison": (
        "workflow.mode = 'comparison' is gone: the legs of a comparison are recipes of "
        "one site in [sites.recipes]. Run them with hmp run, then compare the runs with "
        "hmp diff <run> <run> --to DIR."
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


def run_name_of_file(toml_path: Path) -> str:
    """Derive a simulation name from a TOML filename, folded into the letters of a name.

    ``run_steady_nwt.toml`` -> ``steady_nwt``
    ``Config Winter.toml`` -> ``config_winter``

    The code makes this name, so it is folded and not refused here. The claim of
    the run directory refuses it when it is still too long or reserved.
    """
    return fold_name(re.sub(r"^run_", "", toml_path.stem))


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


def _warn_above_profile(
    model: type[HydroModelBase],
    toml_path: Path,
    read_document: Any,
    validate_profile: ProfileName | Profile,
) -> None:
    """Warn about every field the file writes above the *validate_profile* threshold."""
    raw = read_document(Path(toml_path).expanduser().resolve(), root=ROOT_CONFIG)
    threshold = resolve_profile(validate_profile)
    violations = collect_profile_violations(model, raw, threshold)
    if violations:
        joined = ", ".join(f"{'.'.join(path)}={level.name.lower()}" for path, level in violations)
        say(
            f"TOML {toml_path} declares fields above profile {threshold.name.lower()!r}: {joined}",
            UserWarning,
            stacklevel=3,
        )


def _project_root_of(document: Mapping[str, Any]) -> Any:
    """Return ``[workspace] project_root`` of *document*, or ``None``."""
    workspace = document.get("workspace")
    return workspace.get("project_root") if isinstance(workspace, Mapping) else None


class HydroModPyConfig(HydroModelBase):
    """
    Top-level configuration for HydroModPy.

    Aggregates sub-components (workspace, geographic, domain, data, flow,
    transport, solver, display)
    into a centralized,
    hierarchical model and validates optional flow parameters as
    `FieldParamConfig` dictionaries.
    """

    edition: Annotated[str, Profile.USER] = Field(
        default=FIRST_EDITION,
        description=(
            "The set of defaults the file is read with. A key the file does not write "
            "takes its default in this edition, so a later version never moves a number "
            "of a file that did not ask. config.resolved.toml writes it."
        ),
        examples=["2.0"],
    )
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
    data: Annotated[DataConfig, Profile.USER] = Field(
        default_factory=DataConfig,
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
            "Global solver block loaded from [solver]: the flow solver in "
            "solver.backend, the settings of each flow solver under its name, and the "
            "backend-agnostic preprocessing switches (solver.sink_fill, "
            "solver.drain_band_depth_m)."
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
            "the model ('regular', 'triangle', 'voronoi' or 'catchment') and how fine. "
            "Without the section the 'regular' engine meshes the model with the DEM "
            "pixels. The solver must read the cells of the engine, which is checked "
            "before any meshing."
        ),
        json_schema_extra=field_metadata(
            renamed_from=["mesh_catchment", "mesh_input", *RETIRED_SGRID_KEYS]
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

    _read_as_sealed: bool = PrivateAttr(default=False)

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        "testbed": TESTBED_REFUSAL,
        "analysis": ANALYSIS_SECTION_REFUSAL,
        "hydrometry": HYDROMETRY_SECTION_REFUSAL,
    }

    @property
    def read_as_sealed(self) -> bool:
        """True when this config was read as the frozen config of a run already on disk.

        Such a document is read as it ran: a refusal of the checks against the
        solver only warns, and a rerun of the run keeps going where a new run
        would stop.
        """
        return self._read_as_sealed

    @field_validator("edition")
    @classmethod
    def _an_edition_this_version_serves(cls, value: str) -> str:
        """Refuse an edition this version does not serve, with the ones it serves."""
        return check_registered_name(value, editions(), key="edition")

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

    @model_validator(mode="wrap")
    @classmethod
    def _read_the_dem_of_its_source(
        cls, data: Any, handler: ModelWrapValidatorHandler[HydroModPyConfig], info: ValidationInfo
    ) -> HydroModPyConfig:
        """Let a mapping that declares ``[[data.dem.sources]]`` hold a catchment of kind ``dem``.

        ``[geographic.catchment] kind = "dem"`` reads its DEM from a DEM source. The
        file loader tells the geographic section so through the validation context.
        A Python caller that validates a mapping passes no context, so the same rule
        is read here from the mapping, and both routes accept the same document.
        """
        context = info.context if isinstance(info.context, Mapping) else {}
        if (
            isinstance(data, Mapping)
            and "allow_dem_bootstrap" not in context
            and _raw_declares_dem_source(data.get("data"))
        ):
            return cls.model_validate(data, context={**context, "allow_dem_bootstrap": True})
        return handler(data)

    @model_validator(mode="before")
    @classmethod
    def _refuse_retired_sections(cls, data: Any) -> Any:
        """Refuse a retired root section with what replaces it."""
        if isinstance(data, Mapping):
            name = retired_section(data)
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
        return align_solver_keys(data) if isinstance(data, Mapping) else data

    @model_validator(mode="after")
    def _resolve_then_run_the_cross_rules(self, info: ValidationInfo) -> HydroModPyConfig:
        """Fill what the sections leave to one another, then run the rules that read several.

        The station sources take ``[site] gauge``, and a global model with no
        ``[mesh] engine`` takes the one engine it reads. Then every row of
        ``CROSS_RULES`` runs, in order, and the first refusal is raised. The loader
        and ``check`` run the rows themselves and keep every refusal: they say so
        in the context. A sealed document is the frozen config of a run already on
        disk, read as it ran, where a refusal of a rule that checks the run only
        warns.
        """
        context = info.context if isinstance(info.context, Mapping) else {}
        # An assignment on a sealed config validates again without the context.
        sealed = self._read_as_sealed or context.get("validation_context") == "snapshot"
        if sealed:
            self._read_as_sealed = True
        try:
            apply_site_gauge(self.data, self.site)
        except ConfigError as exc:
            raise ValueError(exc.message) from exc
        # Without an engine written, a [mesh] section would fall on the default,
        # which a backend that only accepts lumped engines cannot read: the
        # engine is deduced before the mesh rules read it.
        deduce_the_mesh_engine(self)
        if context.get("cross_rules") != "caller":
            check_against_the_solver(self, sealed=sealed)
        return self
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

        This is :func:`hydromodpy.config.loading.load` on the path. Relative
        paths are resolved against the project root: the folder that holds
        ``project.toml`` above the file, else the folder of the root file of the
        ``base_config`` chain. Absolute paths are left unchanged. Paths starting
        with ``~`` are expanded to the user's home directory.

        Parameters
        ----------
        toml_path : Path | str
            Path to the input TOML configuration file.
        validate_profile : ProfileName | Profile | None
            Optional profile threshold. When provided, fields whose declared
            :class:`Profile` exceeds the threshold and are present in the TOML
            payload trigger a :class:`UserWarning` (validation still succeeds).
            The chain is then read once more, for this check.

        Returns
        -------
        HydroModPyConfig
            The fully loaded and path-resolved configuration instance.
        """
        # Imported here: loading.py reads this module at import.
        from hydromodpy.config.loading import load, read_document

        if validate_profile is not None:
            _warn_above_profile(cls, Path(toml_path), read_document, validate_profile)
        return load(Path(toml_path))

    @classmethod
    def from_json(
        cls,
        payload: str | bytes,
        *,
        base_dir: str | Path,
    ) -> HydroModPyConfig:
        """Load and validate configuration from JSON text, read as a file is.

        *base_dir* is the folder relative paths are read from: JSON text has no
        folder of its own. The text goes through the same migration and the same
        refusals as a file.
        """
        from hydromodpy.config.loading import json_object

        return cls.from_dict(
            json_object(payload, where="HydroModPyConfig JSON payload"), base_dir=base_dir
        )

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        base_dir: str | Path,
        sealed: bool = False,
    ) -> HydroModPyConfig:
        """Load and validate configuration from a Python mapping.

        *base_dir* is the folder relative paths are read from, the project root;
        a mapping has no folder of its own. The mapping is read as a file is: it
        is migrated, refused on what a file is refused on, ``[workspace]
        project_root`` included (:func:`hydromodpy.config.loading.load`).

        ``sealed`` reads the frozen config of a run already on disk: a check that
        refuses what a run cannot be scored on, or what its flow solver would
        ignore, only warns there, and ``read_as_sealed`` is true on the result.
        """
        base = Path(base_dir).expanduser().resolve()
        if sealed:
            return cls._from_payload(payload, base=base, context="snapshot")
        from hydromodpy.config.loading import load

        return load(payload, base)

    @classmethod
    def _from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        base: Path,
        context: ValidationContext = "api",
        source_path: Path | None = None,
    ) -> HydroModPyConfig:
        """Validate one raw config payload, section by section, and build the root.

        The resolutions of ``config/section_loader.py`` run first, then each
        section is validated on its own, then the root is built and the rules of
        ``CROSS_RULES`` run. This is the validator ``check`` walks too. A
        document with faults raises the error of the first fault in the order of
        the steps, carrying the diagnostics of every fault: a
        :class:`~hydromodpy.core.exceptions.ConfigValidationError` for a fault of
        a section, the typed error of a rule otherwise. Never a bare
        ``ValueError`` nor a raw Pydantic ``ValidationError``, which both map to
        exit code 1, the code of a bug in this process.

        The project root is never a key of a file nor of a request: it is the
        project above *base*, else *base*. A sealed snapshot reads the root it
        names, since its paths were written from there.
        """
        document = copy.deepcopy(dict(payload))
        if context == "snapshot":
            # A sealed config is read under the key names of today, before the
            # protocol is expanded: it compares the stages the run froze with the
            # ones it writes, and a stage frozen under an old key would differ.
            migrate_sealed_config_doc(document)
        in_a_file = context in ("toml", "request")
        forced_root = resolve_project_root(base) if in_a_file else None
        resolved = resolve_document(
            cls,
            document,
            base=base,
            forced_root=forced_root,
            in_a_file=in_a_file,
            source_path=source_path,
        )
        sealed = context == "snapshot" or (
            source_path is not None and is_sealed_run_config(source_path)
        )
        sections, faults = validate_sections(
            cls, resolved, base=base, sealed=sealed, source_path=source_path
        )
        faults = [*resolved.faults, *faults]
        if faults:
            raise_the_first(faults)
        cfg, faults, said = build_document(
            cls,
            sections,
            resolved,
            context=context,
            sealed=context == "snapshot",
            source_path=source_path,
        )
        for text in said:
            logger.warning("%s", text)
        if faults:
            raise_the_first(faults)
        assert isinstance(cfg, HydroModPyConfig)
        _resolve_calibration_parameter_names(cfg)
        return cfg

    @classmethod
    def from_snapshot(
        cls,
        snapshot: Mapping[str, Any],
        *,
        changes: Mapping[str, Any] | None = None,
        sealed: bool = True,
    ) -> HydroModPyConfig:
        """Reconstruct a config from the frozen configuration of a run.

        The snapshot is read as stored, under today's names
        (:func:`~hydromodpy.config.config_migration.migrate_sealed_config_doc`): a key
        removed from the schema since the run was stored is refused, as in a file. A snapshot that names its
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
        sealed : bool, default True
            Read the result as the frozen config of a run already on disk, where
            a refusal of the checks against the solver only warns. False reads it
            as a live document, refused as a file is.

        Returns
        -------
        HydroModPyConfig
        """
        merged = copy.deepcopy(dict(snapshot))
        # The migration drops workspace.project_root, so it is read first.
        project_root = _project_root_of(merged)
        # Under today's names before the changes, which are written in today's names.
        migrate_sealed_config_doc(merged)
        for dotted, value in (changes or {}).items():
            assign(merged, dotted, value)
        project_root = _project_root_of(merged) or project_root
        if project_root:
            return cls.from_dict(merged, base_dir=project_root, sealed=sealed)
        return cls.model_validate(
            merged, context={"validation_context": "snapshot" if sealed else "api"}
        )

    def with_changes(self, changes: Mapping[str, Any]) -> HydroModPyConfig:
        """Return this configuration with *changes* set, by dotted path, and validated.

        This is the one way a configuration takes a change after it is built: a
        keyword override of a run, a rerun. The whole document is validated, so
        the cross-section checks see the change. The result shares every section
        no change touches with this configuration: a built domain or flow compares
        its section by identity to know whether it still describes the run.
        A live configuration stays live, so a change that asks its solver for a
        trait it ignores is refused. A sealed one stays sealed and only warns.
        """
        validated = type(self).from_snapshot(
            written_payload(self), changes=changes, sealed=self.read_as_sealed
        )
        touched = {parse(dotted).parts[0] for dotted in changes}
        return self.model_copy(update={name: getattr(validated, name) for name in touched})


ROOT_CONFIG = RootConfig(HydroModPyConfig, migrate_layers, migrate_merged_doc)
"""The root configuration and its migrations, handed down as an argument.

Core and solver helpers read the sections and migrate a file through the
``RootConfig`` they receive, so they never import this package.
"""
