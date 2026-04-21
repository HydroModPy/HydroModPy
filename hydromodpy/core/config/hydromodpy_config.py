"""Top-level Pydantic configuration object for HydroModPy.

Aggregates all sub-configs into a single hierarchical model.
Relative paths in the TOML are resolved against the TOML file location;
absolute paths are left as-is. Paths starting with ``~`` are expanded
to the user's home directory.

Usage::

    from hydromodpy.core.config import HydroModPyConfig

    cfg = HydroModPyConfig.from_toml("examples/projects/01_canut/run_steady_nwt.toml")
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
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field
from pydantic.fields import FieldInfo

from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.data.data_managers_config import DataManagersConfig
from hydromodpy.analysis.capability_gallery import CapabilityGalleryConfig
from hydromodpy.display.config import DisplayConfig
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.results.postprocess_config import PostprocessConfig
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.physics.transport.transport_config import TransportConfig
from hydromodpy.simulation.planning.config import SimulationConfig
from hydromodpy.solver.modflow6.modflow6_config import Modflow6Config
from hydromodpy.solver.modflow_nwt.modflow import ModflowConfig
from hydromodpy.solver.base.solver_config import SolverConfig
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.workflow.pipelines.overview_config import OverviewSection
from hydromodpy.core.config.path_resolution import resolve_declared_path
from hydromodpy.core.config.toml_loader import load_toml_with_base_config
from hydromodpy.spatial.mesh.config import MeshCatchmentConfigSchema
from hydromodpy.calibration.config import CalibrationConfig


def _derive_run_id_from_filename(toml_path: Path) -> str:
    """Derive a run_id from a TOML filename.

    ``run_steady_nwt.toml`` -> ``steady_nwt``
    ``config.toml`` -> ``config``
    """
    stem = toml_path.stem
    return re.sub(r"^run_", "", stem)


class HydroModPyConfig(BaseModel):
    """
    Top-level configuration for HydroModPy.

    Aggregates sub-components (workspace, geographic, domain, data, flow,
    transport, solver, modflownwt, modflow6, display)
    into a centralized,
    hierarchical model and validates optional flow parameters as
    `FieldParamConfig` dictionaries.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    workspace: WorkspaceConfig = Field(
        description="Configuration block for the project workspace and folder structure."
    )
    geographic: GeographicConfig = Field(
        description="Configuration block for geographic and watershed delineation parameters."
    )
    domain: DomainConfig = Field(
        default_factory=DomainConfig,
        description=(
            "Domain configuration defining domain depth plus the spatial-support "
            "mode used for heterogeneous parameter mapping "
            "(`none`, `geology`, or `zones`)."
        ),
    )
    data: DataManagersConfig = Field(
        default_factory=DataManagersConfig,
        description=(
            "Data-managers configuration. Use `data.types` to declare requested "
            "families (for example `geology`). The launcher can also infer extra "
            "families from other sections (domain, flow), controlled by "
            "`data.inference_mode` ('warn' or 'strict')."
        ),
    )
    flow: FlowConfig = Field(
        default_factory=FlowConfig,
        description=(
            "Flow process configuration with declared parameter ids in "
            "[flow].param_list and payloads validated from [flow.param.<id>] "
            "TOML sections."
        ),
    )
    transport: TransportConfig = Field(
        default_factory=TransportConfig,
        description=(
            "Transport process configuration, with solver-specific parameter "
            "blocks under [transport.modpath.parameters], "
            "[transport.mt3dms.parameters], and [transport.modflow6gwt.parameters]."
        ),
    )
    simulation: SimulationConfig = Field(
        default_factory=SimulationConfig,
        description=(
            "Optional simulation orchestration block loaded from [simulation] "
            "and [[simulation.process]]. When absent, the launcher keeps its "
            "legacy fixed phase order."
        ),
    )
    solver: SolverConfig = Field(
        default_factory=SolverConfig,
        description=(
            "Global solver selection loaded from [solver], including "
            "the active solver_engine."
        ),
    )
    modflownwt: ModflowConfig = Field(
        default_factory=ModflowConfig,
        description=(
            "Expert MODFLOW-NWT package configuration loaded from "
            "[modflownwt.runtime], [modflownwt.process_specific], "
            "[modflownwt.sgrid.planar], and [modflownwt.sgrid.vertical]."
        ),
    )
    modflow6: Modflow6Config = Field(
        default_factory=Modflow6Config,
        description=(
            "Expert MODFLOW 6 package configuration loaded from "
            "[modflow6.runtime], [modflow6.process_specific], "
            "[modflow6.sgrid.planar], and [modflow6.sgrid.vertical]."
        ),
    )
    display: DisplayConfig = Field(
        default_factory=DisplayConfig,
        description=(
            "Optional display and export toggles loaded from the [display] section."
        ),
    )
    postprocess: PostprocessConfig = Field(
        default_factory=PostprocessConfig,
        description=(
            "Optional launcher-managed postprocess workflow loaded from the "
            "[postprocess] section."
        ),
    )
    capability_gallery: CapabilityGalleryConfig = Field(
        default_factory=CapabilityGalleryConfig,
        description=(
            "Optional publication block copying selected run figures into a "
            "versionable capability-gallery source folder."
        ),
    )

    # Lightweight workflows (without simulation)
    overview: OverviewSection | None = Field(
        default=None,
        description=(
            "Optional overview report settings loaded from the [overview] "
            "section.  When present without [simulation], triggers the "
            "data-overview (watershed identity card) workflow."
        ),
    )
    mesh_catchment: MeshCatchmentConfigSchema | None = Field(
        default=None,
        description=(
            "Optional mesh-only settings loaded from the [mesh_catchment] "
            "section.  When present without [simulation], triggers the "
            "mesh-only workflow."
        ),
    )
    calibration: CalibrationConfig | None = Field(
        default=None,
        description=(
            "Optional calibration settings loaded from the [calibration] "
            "section.  When present, triggers the calibration workflow."
        ),
    )

    @classmethod
    def from_toml(cls, toml_path: "Path | str") -> "HydroModPyConfig":
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
                "Section [initializing] is no longer supported. "
                "Use [workspace] instead."
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
            workspace_section["project_root"] = str(
                Path(env_project_root).expanduser().resolve()
            )
        elif not workspace_section.get("project_root"):
            workspace_section["project_root"] = str(base)

        # DEM bootstrap placeholder for overview workflow.
        # When [overview] is present without dem_init_path but a DEM API
        # source is configured in [data], inject a placeholder so
        # GeographicConfig validation passes.  The overview pipeline
        # downloads the real DEM later via _bootstrap_dem().
        geographic_override = raw.get("geographic", {})
        if "overview" in raw and not geographic_override.get("dem_init_path"):
            data_section = raw.get("data", {})
            if "dem" in data_section.get("types", []):
                geographic_override = {
                    **geographic_override,
                    "dem_init_path": "__DEM_API_BOOTSTRAP__",
                }

        section_loaders: dict[str, tuple[Any, Callable[[Any, Path], Any]]] = {
            "workspace": (
                workspace_section,
                lambda data, b: _load_standard_section(data, WorkspaceConfig, b),
            ),
            "geographic": (geographic_override, lambda data, b: _load_standard_section(data, GeographicConfig, b)),
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
            "postprocess": (
                {},
                lambda data, b: _load_standard_section(data, PostprocessConfig, b),
            ),
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
    ) -> "HydroModPyConfig":
        """Reconstruct a config from a stored JSON snapshot.

        Parameters
        ----------
        snapshot : dict
            The ``config_toml`` JSON snapshot stored in DuckDB.
        **overrides
            Key-value overrides merged into the snapshot before
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


def _resolve_section_paths(
    data: dict, model_cls: type[BaseModel], base: Path
) -> None:
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
    section_data: Any, base: Path,
) -> OverviewSection | None:
    """Load the optional ``[overview]`` section."""
    if section_data is None:
        return None
    return _load_standard_section(section_data, OverviewSection, base)


def _load_optional_mesh_catchment_section(
    section_data: Any, base: Path,
) -> MeshCatchmentConfigSchema | None:
    """Load the optional ``[mesh_catchment]`` section."""
    if section_data is None:
        return None
    from hydromodpy.spatial.mesh.config import parse_mesh_catchment_config_data

    return parse_mesh_catchment_config_data(section_data)


