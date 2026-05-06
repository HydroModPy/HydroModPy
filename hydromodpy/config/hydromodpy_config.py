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

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.fields import FieldInfo

from hydromodpy.analysis.config import AnalysisConfig
from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.core.toml_io.paths import resolve_declared_path
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.data.data_managers_config import DataManagersConfig
from hydromodpy.display.config import DisplayConfig
from hydromodpy.display.overview.config import OverviewSection
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.physics.transport.transport_config import TransportConfig
from hydromodpy.simulation.planning.config import SimulationConfig
from hydromodpy.solver.base.solver_config import SolverConfig
from hydromodpy.solver.modflow6.modflow6_config import Modflow6Config
from hydromodpy.solver.modflow_nwt.nwt import ModflowConfig
from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.mesh.config import MeshCatchmentConfig


def _derive_run_id_from_filename(toml_path: Path) -> str:
    """Derive a run_id from a TOML filename.

    ``run_steady_nwt.toml`` -> ``steady_nwt``
    ``config.toml`` -> ``config``
    """
    stem = toml_path.stem
    return re.sub(r"^run_", "", stem)


_KNOWN_TOP_LEVEL_KEYS = frozenset(
    {
        "workflow",
        "workspace",
        "geographic",
        "domain",
        "data",
        "flow",
        "transport",
        "simulation",
        "solver",
        "modflownwt",
        "modflow6",
        "display",
        "persistence",
        "analysis",
        "overview",
        "mesh_catchment",
        "mesh_input",
        "testbed",
        "calibration",
    }
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

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    workflow: Annotated[
        Literal[
            "simulation",
            "calibration",
            "batch",
            "overview",
            "mesh",
            "comparison",
            "testbed",
        ],
        Profile.USER,
    ] = Field(
        description=(
            "Workflow selector (mandatory). Must be one of "
            "'simulation', 'calibration', 'batch', 'overview', 'mesh', "
            "'comparison', 'testbed'. "
            "Drives dispatch in `hmp run <toml>` and in API-driven callers "
            "that instantiate `HydroModPyConfig` from a frontend form."
        ),
    )
    workspace: Annotated[WorkspaceConfig, Profile.USER] = Field(
        description="Configuration block for the project workspace and folder structure."
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
            "Global solver selection loaded from [solver], including the active solver_engine."
        ),
    )
    modflownwt: Annotated[ModflowConfig, Profile.USER] = Field(
        default_factory=ModflowConfig,
        description=(
            "Expert MODFLOW-NWT package configuration loaded from "
            "[modflownwt.runtime], [modflownwt.process_specific], "
            "[modflownwt.sgrid.planar], and [modflownwt.sgrid.vertical]."
        ),
    )
    modflow6: Annotated[Modflow6Config, Profile.USER] = Field(
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
    analysis: Annotated[AnalysisConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional analysis hub loaded from [analysis]. Aggregates "
            "[analysis.batch] (regional-lab launcher), "
            "[analysis.capability_gallery] (figure publication), and "
            "[analysis.comparison] (simulation-comparison launcher)."
        ),
    )

    # Lightweight workflows (without simulation)
    overview: Annotated[OverviewSection | None, Profile.USER] = Field(
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
            "section.  When present without [simulation], triggers the "
            "mesh-only workflow."
        ),
    )
    calibration: Annotated[CalibrationConfig | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional calibration settings loaded from the [calibration] "
            "section.  When present, triggers the calibration workflow."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _default_workspace_for_direct_validation(cls, data):
        """Provide a minimal workspace for direct model_validate callers."""
        if not isinstance(data, Mapping):
            return data
        payload = dict(data)
        workspace = payload.get("workspace")
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
            engine = getattr(solver_cfg, "solver_engine", None)
            engine_value = getattr(engine, "value", engine)
            active_transport_solver = getattr(transport_cfg, "solver", None)
            if engine_value == "boussinesq" and active_transport_solver:
                raise ValueError(
                    "solver.solver_engine='boussinesq' does not support the [transport] section"
                )

        return self

    @classmethod
    def from_toml(cls, toml_path: Path | str) -> HydroModPyConfig:
        """
        Load and validate configuration from a TOML file.

        Relative paths are resolved against the TOML file's directory.
        Absolute paths are left unchanged. Paths starting with ``~`` are
        expanded to the user's home directory.

        Parameters
        ----------
        toml_path : Path | str
            Path to the input TOML configuration file.

        Returns
        -------
        HydroModPyConfig
            The fully loaded and path-resolved configuration instance.
        """
        toml_path = Path(toml_path).expanduser().resolve()
        raw = load_toml_with_base_config(toml_path)

        cfg = cls._from_payload(raw, base=toml_path.parent)

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
        return cls._from_payload(payload, base=base)

    @classmethod
    def _from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        base: Path,
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
                "Section [batch] is no longer supported. Use [analysis.batch] instead."
            )
        unknown = sorted(set(raw) - _KNOWN_TOP_LEVEL_KEYS)
        if unknown:
            raise ValueError(f"Unknown top-level TOML section(s): {', '.join(unknown)}")

        # Auto-derive workspace.project_root from TOML location if absent.
        # HYDROMODPY_PROJECT_ROOT env var takes precedence (used by test infra).
        workspace_section = raw.get("workspace", {})
        env_project_root = os.environ.get("HYDROMODPY_PROJECT_ROOT")
        if env_project_root:
            workspace_section["project_root"] = str(Path(env_project_root).expanduser().resolve())
        elif not workspace_section.get("project_root"):
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
        allow_dem_bootstrap = (
            isinstance(geographic_section, Mapping)
            and not geographic_section.get("dem_init_path")
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
            "calibration": (None, _load_optional_calibration_section),
        }

        parsed_sections: dict[str, Any] = {"workspace": parsed_workspace}
        for section_name, (default_value, loader) in section_loaders.items():
            section_data = raw.get(section_name, default_value)
            parsed_sections[section_name] = loader(section_data, base)

        # Top-level scalar fields (non-section) - forward as-is to Pydantic.
        if "workflow" in raw:
            parsed_sections["workflow"] = raw["workflow"]

        cfg = cls.model_validate(
            parsed_sections,
            context={"allow_dem_bootstrap": allow_dem_bootstrap},
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


def _deep_merge(base: dict, overrides: dict) -> dict:
    """Recursively merge *overrides* into a copy of *base*."""
    result = dict(base)
    for key, val in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _is_path_field(field_info: FieldInfo) -> bool:
    """
    Return True if the field is typed as ``Path`` or ``Path | None``.
    """
    annotation = field_info.annotation
    if annotation is Path:
        return True
    return Path in getattr(annotation, "__args__", ())


def _input_file_role(field_info: FieldInfo) -> str | None:
    """Return the ``InputFile.role`` annotation attached to a field, if any."""
    from hydromodpy.core.tracking.input_file import InputFile

    for meta in field_info.metadata or ():
        if isinstance(meta, InputFile):
            return meta.role
    return None


def _build_path_fallback_dirs(
    role: str | None,
    workspace_data_dir: Path | None,
) -> list[Path] | None:
    """Build the search path used when a config field is a bare filename.

    Order of fallbacks (each tried only when the bare filename does not
    resolve under the TOML directory):

    1. ``<workspace>/data/<role>/`` - convention-over-configuration:
       data files for variable ``<role>`` live here.
    2. ``<workspace>/data/`` - flat fallback for cross-cutting files.
    """
    if workspace_data_dir is None:
        return None
    fallback: list[Path] = []
    if role:
        fallback.append(workspace_data_dir / role)
    fallback.append(workspace_data_dir)
    return fallback


def _resolve_section_paths(
    data: dict,
    model_cls: type[BaseModel],
    base: Path,
    *,
    workspace_data_dir: Path | None = None,
) -> None:
    """
    Resolve relative paths and ``~`` in a config section dict (in-place).

    Bare filenames (no separator, no ``..``) get the convention-driven
    lookup under ``<workspace>/data/<role>/`` when the field carries an
    ``InputFile`` annotation, so users can write
    ``path = "etp_sim2.nc"`` instead of ``../../data/etp/etp_sim2.nc``.
    """
    for field_name, field_info in model_cls.model_fields.items():
        if not _is_path_field(field_info):
            continue
        value = data.get(field_name)
        if isinstance(value, str) and value:
            role = _input_file_role(field_info)
            fallback_dirs = _build_path_fallback_dirs(role, workspace_data_dir)
            data[field_name] = str(
                resolve_declared_path(
                    value,
                    base_dir=base,
                    fallback_dirs=fallback_dirs,
                )
            )


def load_standard_section(
    section_data: Any,
    model_cls: type[BaseModel],
    base: Path,
    *,
    workspace_data_dir: Path | None = None,
) -> BaseModel:
    """Load one regular section by validating against a Pydantic model class."""
    if section_data is None:
        section_data = {}
    if not isinstance(section_data, Mapping):
        raise ValueError(f"TOML section must be a mapping for {model_cls.__name__}")

    payload = dict(section_data)
    _resolve_section_paths(payload, model_cls, base, workspace_data_dir=workspace_data_dir)
    return model_cls(**payload)


def _raw_declares_dem_source(section_data: Any) -> bool:
    """Return True when raw TOML declares at least one DEM data source."""
    if not isinstance(section_data, Mapping):
        return False
    dem_section = section_data.get("dem")
    if not isinstance(dem_section, Mapping):
        return False
    sources = dem_section.get("sources")
    return isinstance(sources, list) and bool(sources)


def load_geographic_section(
    section_data: Any,
    base: Path,
    *,
    workspace_data_dir: Path | None = None,
    allow_dem_bootstrap: bool = False,
) -> GeographicConfig:
    """Load [geographic], allowing DEM resolution from [data.dem] when declared."""
    if section_data is None:
        section_data = {}
    if not isinstance(section_data, Mapping):
        raise ValueError("TOML section must be a mapping for GeographicConfig")

    payload = dict(section_data)
    _resolve_section_paths(payload, GeographicConfig, base, workspace_data_dir=workspace_data_dir)
    return GeographicConfig.model_validate(
        payload,
        context={"allow_dem_bootstrap": allow_dem_bootstrap},
    )


def _load_flow_section(section_data: Any, base: Path) -> FlowConfig:
    """Load the flow section using FlowConfig's dedicated parser."""
    if section_data is None:
        section_data = {}
    return FlowConfig.from_toml_section(section_data, base_dir=base)


def _load_data_section(
    section_data: Any,
    base: Path,
    *,
    workspace_data_dir: Path | None = None,
) -> DataManagersConfig:
    """Load the data section with dynamic validation by enabled data types."""
    return DataManagersConfig.from_toml_section(
        section_data,
        base_dir=base,
        workspace_data_dir=workspace_data_dir,
    )


def _load_optional_overview_section(
    section_data: Any,
    base: Path,
) -> OverviewSection | None:
    """Load the optional ``[overview]`` section."""
    if section_data is None:
        return None
    return load_standard_section(section_data, OverviewSection, base)


def _load_optional_mesh_catchment_section(
    section_data: Any,
    base: Path,
) -> MeshCatchmentConfig | None:
    """Load the optional ``[mesh_catchment]`` section."""
    if section_data is None:
        return None
    from hydromodpy.spatial.mesh.config import parse_mesh_catchment_config_data

    return parse_mesh_catchment_config_data(section_data)


def _load_optional_calibration_section(
    section_data: Any,
    base: Path,
) -> CalibrationConfig | None:
    """Load the optional ``[calibration]`` section."""
    if section_data is None:
        return None
    return load_standard_section(section_data, CalibrationConfig, base)


def _load_optional_analysis_section(
    section_data: Any,
    base: Path,
) -> AnalysisConfig | None:
    """Load the optional ``[analysis]`` section."""
    if section_data is None:
        return None
    if not isinstance(section_data, Mapping):
        raise ValueError("[analysis] must be a mapping")

    from hydromodpy.analysis.batch.config import RegionalLabConfig
    from hydromodpy.analysis.capability_gallery import CapabilityGalleryConfig
    from hydromodpy.analysis.comparison.config import ComparisonSection

    parsed: dict[str, Any] = {}

    raw_gallery = section_data.get("capability_gallery")
    if raw_gallery is not None:
        parsed["capability_gallery"] = load_standard_section(
            raw_gallery, CapabilityGalleryConfig, base
        )

    raw_batch = section_data.get("batch")
    if raw_batch is not None:
        if not isinstance(raw_batch, Mapping):
            raise ValueError("[analysis.batch] must be a mapping")
        parsed["batch"] = RegionalLabConfig.from_toml(
            raw_batch,
            config_path=base / "analysis_batch.toml",
        )

    raw_comparison = section_data.get("comparison")
    if raw_comparison is not None:
        if not isinstance(raw_comparison, Mapping):
            raise ValueError("[analysis.comparison] must be a mapping")
        parsed["comparison"] = ComparisonSection.model_validate(raw_comparison)

    extra_keys = set(section_data) - {"batch", "capability_gallery", "comparison"}
    if extra_keys:
        unknown = ", ".join(sorted(extra_keys))
        raise ValueError(f"Unknown [analysis] sub-section(s): {unknown}")

    return AnalysisConfig(**parsed)
