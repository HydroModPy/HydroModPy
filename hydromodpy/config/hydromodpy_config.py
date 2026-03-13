"""Top-level Pydantic configuration object for HydroModPy.

Aggregates all sub-configs into a single hierarchical model.
Relative paths in the TOML are resolved against the TOML file location;
absolute paths are left as-is. Paths starting with ``~`` are expanded
to the user's home directory.

Usage::

    from hydromodpy.config import HydroModPyConfig

    cfg = HydroModPyConfig.from_toml("examples_legacy/01S_short/config.toml")
    cfg.workspace.catch_name
    cfg.geographic.catch_def
    cfg.geographic.dem_init_path
    cfg.domain.zone_ids
    cfg.data.geology.id
    cfg.flow.param["K"]
    cfg.modflownwt.process_specific.vka
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.fields import FieldInfo

from hydromodpy.domain.domain_config import DomainConfig
from hydromodpy.data_managers.data_managers_config import DataManagersConfig
from hydromodpy.display.options import DisplayConfig
from hydromodpy.geographic.geographic_config import GeographicConfig
from hydromodpy.postprocess.postprocess_config import PostprocessConfig
from hydromodpy.process.flow.flow_config import FlowConfig
from hydromodpy.process.transport.transport_config import TransportConfig
from hydromodpy.forcing.recharge_chronicle_config import (
    RechargeChronicleConfig,
    validate_recharge_chronicle_section,
)
from hydromodpy.simulation.planning.config import SimulationConfig
from hydromodpy.solver.modflow6.modflow6_config import Modflow6Config
from hydromodpy.solver.modflow_nwt.modflow import ModflowConfig
from hydromodpy.solver.prototype.solver_config import SolverConfig
from hydromodpy.simulation.workspace.config import WorkspaceConfig
from hydromodpy.config.toml_loader import load_toml_with_base_config


class RunConfig(BaseModel):
    """Controls which phases the launcher executes."""

    phases: list[str] = Field(
        default=["setup", "data", "flow", "particles", "transport"],
        description=(
            "Ordered list of phases to run. "
            "Allowed values: 'setup', 'data', 'flow', 'particles', 'transport'."
        ),
    )


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
    recharge_chronicle: RechargeChronicleConfig | None = Field(
        default=None,
        description=(
            "Optional launcher recharge chronicle block loaded from "
            "[recharge_chronicle]. Supports observed CSV, synthetic CSV, "
            "and synthetic generated payloads."
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
    run: RunConfig = Field(
        default_factory=RunConfig,
        description=(
            "Launcher run configuration. Controls which phases are executed. "
            "Defaults to all phases if the [run] section is absent from the TOML."
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

    @model_validator(mode="after")
    def _validate_cross_section_constraints(self) -> "HydroModPyConfig":
        """Validate constraints that depend on several top-level sections."""
        return self

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
            "transport": (
                {},
                lambda data, b: _load_standard_section(data, TransportConfig, b),
            ),
            "simulation": (
                {},
                lambda data, b: _load_standard_section(data, SimulationConfig, b),
            ),
            "recharge_chronicle": (
                None,
                _load_recharge_chronicle_section,
            ),
            "solver": ({}, _load_solver_section),
            "modflownwt": ({}, _load_modflow_nwt_section),
            "modflow6": ({}, _load_modflow6_section),
            "run": ({}, lambda data, b: _load_standard_section(data, RunConfig, b)),
            "display": ({}, lambda data, b: _load_standard_section(data, DisplayConfig, b)),
            "postprocess": (
                {},
                lambda data, b: _load_standard_section(data, PostprocessConfig, b),
            ),
        }

        parsed_sections: dict[str, Any] = {}
        for section_name, (default_value, loader) in section_loaders.items():
            section_data = raw.get(section_name, default_value)
            parsed_sections[section_name] = loader(section_data, base)

        return cls(**parsed_sections)

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


def _load_solver_section(section_data: Any, base: Path) -> SolverConfig:
    """Load solver section."""
    if section_data is None:
        section_data = {}
    if not isinstance(section_data, Mapping):
        raise ValueError("TOML section must be a mapping for SolverConfig")
    return SolverConfig.model_validate(dict(section_data))


def _load_modflow_nwt_section(section_data: Any, base: Path) -> ModflowConfig:
    """Load modflownwt section."""
    if section_data is None:
        section_data = {}
    if not isinstance(section_data, Mapping):
        raise ValueError("TOML section must be a mapping for ModflowConfig")
    return ModflowConfig.model_validate(dict(section_data))


def _load_modflow6_section(section_data: Any, base: Path) -> Modflow6Config:
    """Load modflow6 section."""
    if section_data is None:
        section_data = {}
    if not isinstance(section_data, Mapping):
        raise ValueError("TOML section must be a mapping for Modflow6Config")
    return Modflow6Config.model_validate(dict(section_data))


def _load_recharge_chronicle_section(
    section_data: Any,
    base: Path,
) -> RechargeChronicleConfig | None:
    """Load the recharge chronicle section with dedicated validation."""
    return validate_recharge_chronicle_section(section_data)

