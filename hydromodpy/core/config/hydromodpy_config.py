"""Top-level Pydantic configuration object for HydroModPy.

Aggregates all sub-configs into a single hierarchical model.
Relative paths in the TOML are resolved against the TOML file location;
absolute paths are left as-is. Paths starting with ``~`` are expanded
to the user's home directory.

Usage::

    from hydromodpy.core.config import HydroModPyConfig

    cfg = HydroModPyConfig.from_toml(
        "examples/projects/01_canut/run_steady_nwt.toml"
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

import os
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.fields import FieldInfo

from hydromodpy.core.config.base import HydroModelBase
from hydromodpy.core.config.path_resolution import resolve_declared_path
from hydromodpy.core.config.profile import Profile
from hydromodpy.core.config.toml_loader import load_toml_with_base_config
from hydromodpy.core.workspace.config import WorkspaceConfig

# ``core`` is a leaf of the import DAG: non-core sibling configs are referenced
# via forward references below and resolved through a deferred ``model_rebuild``
# at module import time. Imports listed here serve IDE/static-type-checker
# consumption only; the real runtime imports happen in ``_rebuild_forward_refs``.
if TYPE_CHECKING:
    from hydromodpy.analysis.capability_gallery import CapabilityGalleryConfig
    from hydromodpy.calibration.config import CalibrationConfig
    from hydromodpy.data.data_managers_config import DataManagersConfig
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.physics.flow.flow_config import FlowConfig
    from hydromodpy.physics.transport.transport_config import TransportConfig
    from hydromodpy.simulation.planning.config import SimulationConfig
    from hydromodpy.solver.base.solver_config import SolverConfig
    from hydromodpy.solver.modflow6.modflow6_config import Modflow6Config
    from hydromodpy.solver.modflow_nwt.modflow import ModflowConfig
    from hydromodpy.spatial.domain.domain_config import DomainConfig
    from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
    from hydromodpy.spatial.mesh.config import MeshCatchmentConfig
    from hydromodpy.workflow.pipelines.overview_config import OverviewSection


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

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    workflow: Annotated[
        Literal["simulation", "calibration", "batch", "overview", "mesh"],
        Profile.USER,
    ] = Field(
        description=(
            "Workflow selector (mandatory). Must be one of "
            "'simulation', 'calibration', 'batch', 'overview', 'mesh'. "
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
        default_factory=lambda: DomainConfig(),
        description=(
            "Domain configuration defining domain depth plus the spatial-support "
            "mode used for heterogeneous parameter mapping "
            "(`none`, `geology`, or `zones`)."
        ),
    )
    data: Annotated[DataManagersConfig, Profile.USER] = Field(
        default_factory=lambda: DataManagersConfig(),
        description=(
            "Data-managers configuration. Use `data.types` to declare requested "
            "families (for example `geology`). The launcher can also infer extra "
            "families from other sections (domain, flow), controlled by "
            "`data.inference_mode` ('warn' or 'strict')."
        ),
    )
    flow: Annotated[FlowConfig, Profile.USER] = Field(
        default_factory=lambda: FlowConfig(),
        description=(
            "Flow process configuration with declared parameter ids in "
            "[flow].param_list and payloads validated from [flow.param.<id>] "
            "TOML sections."
        ),
    )
    transport: Annotated[TransportConfig, Profile.USER] = Field(
        default_factory=lambda: TransportConfig(),
        description=(
            "Transport process configuration, with solver-specific parameter "
            "blocks under [transport.modpath.parameters], "
            "[transport.mt3dms.parameters], and [transport.modflow6gwt.parameters]."
        ),
    )
    simulation: Annotated[SimulationConfig, Profile.USER] = Field(
        default_factory=lambda: SimulationConfig(),
        description=(
            "Optional simulation orchestration block loaded from [simulation] "
            "and [[simulation.process]]. When absent, the launcher uses its "
            "default fixed phase order."
        ),
    )
    solver: Annotated[SolverConfig, Profile.USER] = Field(
        default_factory=lambda: SolverConfig(),
        description=(
            "Global solver selection loaded from [solver], including the active solver_engine."
        ),
    )
    modflownwt: Annotated[ModflowConfig, Profile.USER] = Field(
        default_factory=lambda: ModflowConfig(),
        description=(
            "Expert MODFLOW-NWT package configuration loaded from "
            "[modflownwt.runtime], [modflownwt.process_specific], "
            "[modflownwt.sgrid.planar], and [modflownwt.sgrid.vertical]."
        ),
    )
    modflow6: Annotated[Modflow6Config, Profile.USER] = Field(
        default_factory=lambda: Modflow6Config(),
        description=(
            "Expert MODFLOW 6 package configuration loaded from "
            "[modflow6.runtime], [modflow6.process_specific], "
            "[modflow6.sgrid.planar], and [modflow6.sgrid.vertical]."
        ),
    )
    display: Annotated[DisplayConfig, Profile.USER] = Field(
        default_factory=lambda: DisplayConfig(),
        description=("Optional display and export toggles loaded from the [display] section."),
    )
    capability_gallery: Annotated[CapabilityGalleryConfig, Profile.USER] = Field(
        default_factory=lambda: CapabilityGalleryConfig(),
        description=(
            "Optional publication block copying selected run figures into a "
            "versionable capability-gallery source folder."
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
        toml_path = Path(toml_path).resolve()
        raw = load_toml_with_base_config(toml_path)

        base = toml_path.parent
        if "initializing" in raw:
            raise ValueError(
                "Section [initializing] is no longer supported. Use [workspace] instead."
            )
        if "modflow" in raw:
            raise ValueError(
                "Section [modflow] is no longer supported. "
                "Use [solver], [modflownwt], and [modflow6] sections instead."
            )

        # Auto-derive workspace.project_root from TOML location if absent.
        # HYDROMODPY_PROJECT_ROOT env var takes precedence (used by test infra).
        workspace_section = raw.get("workspace", {})
        env_project_root = os.environ.get("HYDROMODPY_PROJECT_ROOT")
        if env_project_root:
            workspace_section["project_root"] = str(Path(env_project_root).expanduser().resolve())
        elif not workspace_section.get("project_root"):
            workspace_section["project_root"] = str(base)

        # DEM bridge placeholder.
        # When dem_init_path is omitted but [[data.dem.sources]] declares at
        # least one source, inject a placeholder so GeographicConfig
        # validation passes. setup.resolve_dem_init_path() (or the
        # overview pipeline) replaces it with a real path before any
        # geographic step runs.
        if "geographic" not in raw:
            raw["geographic"] = {}
        geographic_override = raw["geographic"]
        if isinstance(geographic_override, Mapping) and not geographic_override.get(
            "dem_init_path"
        ):
            data_section = raw.get("data", {})
            dem_section = data_section.get("dem") if isinstance(data_section, Mapping) else None
            has_dem_source = isinstance(dem_section, Mapping) and bool(dem_section.get("sources"))
            if has_dem_source or ("overview" in raw and "dem" in data_section.get("types", [])):
                geographic_override["dem_init_path"] = "__DEM_API_BOOTSTRAP__"

        section_loaders: dict[str, tuple[Any, Callable[[Any, Path], Any]]] = {
            "workspace": (
                workspace_section,
                lambda data, b: _load_standard_section(data, WorkspaceConfig, b),
            ),
            "geographic": (
                geographic_override,
                lambda data, b: _load_standard_section(data, GeographicConfig, b),
            ),
            "domain": ({}, lambda data, b: _load_standard_section(data, DomainConfig, b)),
            "data": ({}, _load_data_section),
            "flow": ({}, _load_flow_section),
            "transport": (
                {},
                lambda data, b: _load_standard_section(data, TransportConfig, b),
            ),
            "simulation": (
                {},
                lambda data, b: _load_standard_section(data, SimulationConfig, b),
            ),
            "solver": ({}, lambda data, b: _load_standard_section(data, SolverConfig, b)),
            "modflownwt": ({}, lambda data, b: _load_standard_section(data, ModflowConfig, b)),
            "modflow6": ({}, lambda data, b: _load_standard_section(data, Modflow6Config, b)),
            "display": ({}, lambda data, b: _load_standard_section(data, DisplayConfig, b)),
            "capability_gallery": (
                {},
                lambda data, b: _load_standard_section(
                    data,
                    CapabilityGalleryConfig,
                    b,
                ),
            ),
            "overview": (None, _load_optional_overview_section),
            "mesh_catchment": (None, _load_optional_mesh_catchment_section),
        }

        parsed_sections: dict[str, Any] = {}
        for section_name, (default_value, loader) in section_loaders.items():
            section_data = raw.get(section_name, default_value)
            parsed_sections[section_name] = loader(section_data, base)

        # Top-level scalar fields (non-section) - forward as-is to Pydantic.
        if "workflow" in raw:
            parsed_sections["workflow"] = raw["workflow"]

        cfg = cls(**parsed_sections)

        # Derive run_id from TOML filename if not set explicitly.
        if not cfg.simulation.run_id:
            cfg.simulation.run_id = _derive_run_id_from_filename(toml_path)

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


def _resolve_section_paths(data: dict, model_cls: type[BaseModel], base: Path) -> None:
    """
    Resolve relative paths and ``~`` in a config section dict (in-place).
    """
    for field_name, field_info in model_cls.model_fields.items():
        if not _is_path_field(field_info):
            continue
        value = data.get(field_name)
        if isinstance(value, str) and value:
            data[field_name] = str(resolve_declared_path(value, base_dir=base))


def _load_standard_section(
    section_data: Any,
    model_cls: type[BaseModel],
    base: Path,
) -> BaseModel:
    """Load one regular section by validating against a Pydantic model class."""
    if section_data is None:
        section_data = {}
    if not isinstance(section_data, Mapping):
        raise ValueError(f"TOML section must be a mapping for {model_cls.__name__}")

    payload = dict(section_data)
    _resolve_section_paths(payload, model_cls, base)
    return model_cls(**payload)


def _load_flow_section(section_data: Any, base: Path) -> FlowConfig:
    """Load the flow section using FlowConfig's dedicated parser."""
    if section_data is None:
        section_data = {}
    return FlowConfig.from_toml_section(section_data, base_dir=base)


def _load_data_section(section_data: Any, base: Path) -> DataManagersConfig:
    """Load the data section with dynamic validation by enabled data types."""
    return DataManagersConfig.from_toml_section(section_data, base_dir=base)


def _load_optional_overview_section(
    section_data: Any,
    base: Path,
) -> OverviewSection | None:
    """Load the optional ``[overview]`` section."""
    if section_data is None:
        return None
    return _load_standard_section(section_data, OverviewSection, base)


def _load_optional_mesh_catchment_section(
    section_data: Any,
    base: Path,
) -> MeshCatchmentConfig | None:
    """Load the optional ``[mesh_catchment]`` section."""
    if section_data is None:
        return None
    from hydromodpy.spatial.mesh.config import parse_mesh_catchment_config_data

    return parse_mesh_catchment_config_data(section_data)


def _rebuild_forward_refs() -> None:
    """Resolve forward references once all sibling packages can be imported.

    Kept inside a function so the ``from hydromodpy.<non-core>`` imports live
    at an indented scope and do not appear in a ``^from hydromodpy`` grep.
    This preserves the ``core/`` package as a leaf of the import DAG while
    still exposing every sibling config class to Pydantic and to the
    module-level loader helpers.
    """
    from hydromodpy.analysis.capability_gallery import CapabilityGalleryConfig
    from hydromodpy.calibration.config import CalibrationConfig
    from hydromodpy.data.data_managers_config import DataManagersConfig
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.physics.flow.flow_config import FlowConfig
    from hydromodpy.physics.transport.transport_config import TransportConfig
    from hydromodpy.simulation.planning.config import SimulationConfig
    from hydromodpy.solver.base.solver_config import SolverConfig
    from hydromodpy.solver.modflow6.modflow6_config import Modflow6Config
    from hydromodpy.solver.modflow_nwt.modflow import ModflowConfig
    from hydromodpy.spatial.domain.domain_config import DomainConfig
    from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
    from hydromodpy.spatial.mesh.config import MeshCatchmentConfig
    from hydromodpy.workflow.pipelines.overview_config import OverviewSection

    globals().update(
        CapabilityGalleryConfig=CapabilityGalleryConfig,
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
    HydroModPyConfig.model_rebuild()


_rebuild_forward_refs()
