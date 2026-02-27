"""Top-level Pydantic configuration object for HydroModPy.

Aggregates all sub-configs into a single hierarchical model.
Relative paths in the TOML are resolved against the TOML file location;
absolute paths are left as-is. Paths starting with ``~`` are expanded
to the user's home directory.

Usage::

    from hydromodpy.config import HydroModPyConfig

    cfg = HydroModPyConfig.from_toml("examples/01S_short/config.toml")
    cfg.workspace.catch_name
    cfg.geographic.catch_def
    cfg.geographic.dem_init_path
    cfg.domain.zone_ids
    cfg.data.geology.id
    cfg.flow.param["K"]
    cfg.modflow.process_specific.vka
"""

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field
from pydantic.fields import FieldInfo

from hydromodpy.domain.domain_config import DomainConfig
from hydromodpy.data_managers.data_managers_config import DataManagersConfig
from hydromodpy.geographic.geographic_config import GeographicConfig
from hydromodpy.process.flow.flow_config import FlowConfig
from hydromodpy.solver.modflow_nwt.modflow_config import ModflowConfig
from hydromodpy.watershed.workspace_config import WorkspaceConfig


class HydroModPyConfig(BaseModel):
    """
    Top-level configuration for HydroModPy.

    Aggregates sub-components (workspace, geographic, domain, data, flow, modflow)
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
            "Domain configuration defining which thematic zones are loaded "
            "(for example 'geology')."
        ),
    )
    data: DataManagersConfig = Field(
        default_factory=DataManagersConfig,
        description=(
            "Data-managers configuration. Use `data.types` to declare active "
            "families (for example `geology`) and their nested sections."
        ),
    )
    flow: FlowConfig = Field(
        default_factory=FlowConfig,
        description=(
            "Flow process configuration with parameter payloads validated "
            "from [flow.param.<id>] TOML sections."
        ),
    )
    modflow: ModflowConfig = Field(
        default_factory=ModflowConfig,
        description=(
            "Expert MODFLOW-NWT package configuration loaded from "
            "[modflow.runtime], [modflow.process_specific], [modflow.sgrid]."
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
        with toml_path.open("rb") as stream:
            raw = tomllib.load(stream)

        base = toml_path.parent
        if "initializing" in raw:
            raise ValueError(
                "Section [initializing] is no longer supported. "
                "Use [workspace] instead."
            )
        workspace_section = raw.get("workspace", {})

        section_loaders: dict[str, tuple[Any, Callable[[Any, Path], Any]]] = {
            "workspace": (
                workspace_section,
                lambda data, b: _load_standard_section(data, WorkspaceConfig, b),
            ),
            "geographic": ({}, lambda data, b: _load_standard_section(data, GeographicConfig, b)),
            "domain": ({}, lambda data, b: _load_standard_section(data, DomainConfig, b)),
            "data": ({}, _load_data_section),
            "flow": ({}, _load_flow_section),
            "modflow": ({}, _load_modflow_section),
        }

        parsed_sections: dict[str, Any] = {}
        for section_name, (default_value, loader) in section_loaders.items():
            section_data = raw.get(section_name, default_value)
            parsed_sections[section_name] = loader(section_data, base)

        return cls(**parsed_sections)

    @property
    def initializing(self) -> WorkspaceConfig:
        """Backward-compatible alias. Prefer `workspace`."""
        return self.workspace


def _is_path_field(field_info: FieldInfo) -> bool:
    """
    Return True if the field is typed as ``Path`` or ``Optional[Path]``.
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
            p = Path(value).expanduser()
            if not p.is_absolute():
                p = (base / p).resolve()
            data[field_name] = str(p)


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


def _load_modflow_section(section_data: Any, base: Path) -> ModflowConfig:
    """Load modflow section."""
    if section_data is None:
        section_data = {}
    if not isinstance(section_data, Mapping):
        raise ValueError("TOML section must be a mapping for ModflowConfig")
    return ModflowConfig.model_validate(dict(section_data))
