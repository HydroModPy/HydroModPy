"""Pydantic configuration model for flow-process definitions.

This module validates and normalizes `[flow]`, `[flow.param.<id>]`, `[flow.ic]`,
`[flow.bc]`, and `[flow.sinks_sources]` payloads from TOML into objects
consumable by `Flow`.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from hydromodpy.config.param_level import ParamLevel
from hydromodpy.process.flow.boundary_conditions import (
    DIRICHLET_BC_CANONICAL_DOMAINS,
    FlowBoundaryConditionConfig,
)
from hydromodpy.process.flow.boundary_conditions_config import (
    normalize_flow_boundary_conditions,
)
from hydromodpy.process.flow.initial_conditions import (
    FlowInitialConditions,
)
from hydromodpy.process.flow.initial_conditions_config import (
    normalize_flow_initial_conditions,
)
from hydromodpy.process.flow.param_config import (
    normalize_flow_param_payloads,
    parse_flow_param_sections,
)
from hydromodpy.process.flow.sinks_sources import (
    FlowSinksSourcesConfig,
    FlowWellConfig,
)
from hydromodpy.process.flow.sinks_sources_config import (
    normalize_flow_sinks_sources,
)
from hydromodpy.process.prototype import ProcessSpatialConfig

__all__ = [
    "FlowBoundaryConditionConfig",
    "FlowWellConfig",
    "FlowSinksSourcesConfig",
    "FlowConfig",
]


class FlowConfig(ProcessSpatialConfig):
    """Flow-process configuration.

    Parameters are declared in `param_list` (ordered list of ids), and
    parameter payloads are stored in `param`.
    """

    flow_regime: Annotated[Literal["steady", "transient"], ParamLevel("user")] = Field(
        default="transient",
        description=(
            "Global flow simulation regime used by solvers consuming [flow] "
            "(steady or transient)."
        ),
    )
    runtime_backend: Annotated[
        Literal["local", "scipy", "scipy_sparse"], ParamLevel("dev")
    ] = Field(
        default="local",
        description=(
            "Optional nonlinear runtime backend hint used by the Boussinesq "
            "solver implementation. Other flow solvers may ignore this field."
        ),
    )
    param_list: list[str] = Field(
        default_factory=list,
        description=(
            "Ordered list of flow-parameter identifiers used to build runtime "
            "parameters (for example ['K', 'Ss', 'Sy'])."
        ),
    )
    param: dict[str, dict[str, object]] = Field(
        default_factory=dict,
        description=(
            "Mapping of flow-parameter identifiers to resolved FieldParamConfig "
            "payloads."
        ),
    )
    bc: dict[str, object] = Field(
        default_factory=dict,
        description=(
            "Mapping of flow boundary-condition payloads parsed from [flow.bc]. "
            "Supported sections are: "
            "[flow.bc.dirichlet.<id>] with <id> in ocean, stream, north_side, "
            "south_side, east_side, west_side; "
            "[flow.bc.cauchy.drainage]; [flow.bc.robin.drainage]; "
            "and generic [flow.bc.<custom_id>] payloads. "
            "Common required key: value (numeric or '<value> <unit>'). "
            "Dirichlet keys may omit application_domain when <id> implies it "
            "(for example west_side -> 'west side'). "
            "Drainage (cauchy/robin) requires application_domain explicitly. "
            "Supported application_domain values are: top, north side, south side, "
            "east side, west side. "
            "Default units: m for dirichlet, m2/s for cauchy/robin."
        ),
    )
    ic: FlowInitialConditions = Field(
        default_factory=FlowInitialConditions,
        description=(
            "Validated flow initial-condition structure parsed from [flow.ic]. "
            "Stored as FlowInitialConditions(h=FlowInitialCondition)."
        ),
    )
    sinks_sources: FlowSinksSourcesConfig = Field(
        default_factory=FlowSinksSourcesConfig,
        description="Typed sinks/sources payload (for example pumping wells).",
    )
    active_sinks_sources: list[str] = Field(
        default_factory=list,
        description=(
            "Explicitly activated sink/source names for this flow run. "
            "Allowed values: 'recharge', 'wells'. "
            "An empty list means no sink/source package is assembled by the solver."
        ),
    )
    active_bc: list[str] = Field(
        default_factory=list,
        description=(
            "Explicitly activated boundary-condition ids for this flow run. "
            "Allowed values: 'ocean', 'stream', 'north_side', 'south_side', "
            "'east_side', 'west_side', 'drainage'. "
            "An empty list means no boundary-condition package is assembled by the solver."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_param_payload_shapes(cls, value):
        """
        Normalize accepted parameter declaration styles before validation.

        Supports canonical shape only, then rewrites to:
        - `param_list`
        - `param`
        """
        if value is None or not isinstance(value, Mapping):
            return value
        payload = dict(value)
        raw_param_list = payload.get("param_list")
        raw_param = payload.get("param")
        if isinstance(raw_param, Mapping):
            if raw_param_list is None:
                payload["param_list"] = list(raw_param.keys())
        elif raw_param is not None:
            raise ValueError("flow.param must be a mapping payload when provided")

        if payload.get("param_values") is not None:
            raise ValueError("flow.param_values is no longer supported. Use flow.param.")
        return payload

    @field_validator("param_list", mode="before")
    @classmethod
    def _validate_param_list(cls, value):
        """Validate and normalize `flow.param_list` as a unique ordered list."""
        if value is None:
            return []
        if isinstance(value, Mapping):
            value = list(value.keys())
        if not isinstance(value, (list, tuple)):
            raise ValueError("flow.param_list must be a list of parameter ids")

        out: list[str] = []
        for raw_param_id in value:
            param_id = str(raw_param_id).strip()
            if param_id == "":
                raise ValueError("flow.param_list cannot contain empty parameter ids")
            out.append(param_id)
        if len(set(out)) != len(out):
            raise ValueError("flow.param_list cannot contain duplicate parameter ids")
        return out

    @field_validator("param", mode="before")
    @classmethod
    def _validate_param_payloads(cls, value):
        """Normalize `flow.param` payloads into resolved FieldParamConfig mappings."""
        return normalize_flow_param_payloads(value, location_prefix="flow.param")

    @model_validator(mode="after")
    def _validate_param_consistency(self):
        """Enforce one-to-one consistency between `param_list` and `param` keys."""
        missing = [param_id for param_id in self.param_list if param_id not in self.param]
        if missing:
            missing_text = ", ".join(missing)
            raise ValueError(
                f"flow.param_list declares ids without payload in flow.param: {missing_text}"
            )
        extra = [param_id for param_id in self.param if param_id not in self.param_list]
        if extra:
            extra_text = ", ".join(extra)
            raise ValueError(
                f"flow.param contains ids not declared in flow.param_list: {extra_text}"
            )
        return self

    @field_validator("flow_regime", mode="before")
    @classmethod
    def _validate_flow_regime(cls, value):
        """Validate flow regime enumeration."""
        text = str(value).strip().lower()
        if text not in {"steady", "transient"}:
            raise ValueError("flow.flow_regime must be 'steady' or 'transient'")
        return text

    @field_validator("runtime_backend", mode="before")
    @classmethod
    def _validate_runtime_backend(cls, value):
        """Normalize the optional Boussinesq runtime backend selector."""
        text = str(value or "local").strip().lower()
        if text not in {"local", "scipy", "scipy_sparse"}:
            raise ValueError(
                "flow.runtime_backend must be 'local', 'scipy', or 'scipy_sparse'"
            )
        return text

    @field_validator("bc", mode="before")
    @classmethod
    def _validate_bc(cls, value):
        """Normalize boundary-condition payloads from `[flow.bc]`."""
        return normalize_flow_boundary_conditions(value, location_prefix="flow.bc")

    @field_validator("ic", mode="before")
    @classmethod
    def _validate_ic(cls, value):
        """Normalize initial-condition payload from `[flow.ic]`."""
        if value is None:
            return FlowInitialConditions()
        result = normalize_flow_initial_conditions(value, location_prefix="flow.ic")
        if result is None:
            return FlowInitialConditions()
        return result

    @field_validator("sinks_sources", mode="before")
    @classmethod
    def _validate_sinks_sources(cls, value):
        """Normalize sinks/sources payload from `[flow.sinks_sources]`."""
        return normalize_flow_sinks_sources(value, location_prefix="flow.sinks_sources")

    @field_validator("active_sinks_sources", mode="before")
    @classmethod
    def _validate_active_sinks_sources(cls, value):
        """
        Validate that ``active_sinks_sources`` only contains allowed values.

        For ``Flow``, the only permitted sink/source identifiers are
        ``'recharge'`` and ``'wells'``.  Any other value is an error.
        Duplicates are rejected to keep the list unambiguous.
        """
        _ALLOWED = {"recharge", "wells"}
        if value is None:
            return []
        if not isinstance(value, (list, tuple)):
            raise ValueError("flow.active_sinks_sources must be a list")
        out: list[str] = []
        seen: set[str] = set()
        for raw in value:
            name = str(raw).strip()
            if name not in _ALLOWED:
                allowed_text = ", ".join(sorted(_ALLOWED))
                raise ValueError(
                    f"flow.active_sinks_sources: '{name}' is not a valid sink/source "
                    f"for Flow. Allowed values: {allowed_text}."
                )
            if name in seen:
                raise ValueError(
                    f"flow.active_sinks_sources cannot contain duplicates: '{name}'"
                )
            seen.add(name)
            out.append(name)
        return out

    @field_validator("active_bc", mode="before")
    @classmethod
    def _validate_active_bc(cls, value):
        """
        Validate that ``active_bc`` only contains allowed boundary-condition ids.

        For ``Flow``, permitted ids are those declared in
        ``DIRICHLET_BC_CANONICAL_DOMAINS`` (ocean, stream, north_side,
        south_side, east_side, west_side) plus ``'drainage'``.
        Duplicates are rejected to keep the list unambiguous.
        """
        _ALLOWED = set(DIRICHLET_BC_CANONICAL_DOMAINS.keys()) | {"drainage"}
        if value is None:
            return []
        if not isinstance(value, (list, tuple)):
            raise ValueError("flow.active_bc must be a list")
        out: list[str] = []
        seen: set[str] = set()
        for raw in value:
            name = str(raw).strip()
            if name not in _ALLOWED:
                allowed_text = ", ".join(sorted(_ALLOWED))
                raise ValueError(
                    f"flow.active_bc: '{name}' is not a valid boundary-condition id "
                    f"for Flow. Allowed values: {allowed_text}."
                )
            if name in seen:
                raise ValueError(
                    f"flow.active_bc cannot contain duplicates: '{name}'"
                )
            seen.add(name)
            out.append(name)
        return out

    @classmethod
    def from_toml_section(
        cls,
        flow_section: Mapping[str, object] | None,
        *,
        base_dir: Path,
    ) -> "FlowConfig":
        """
        Build a validated `FlowConfig` from the `[flow]` TOML section.

        Processing steps:
        1. Validate raw section shapes.
        2. Parse and resolve parameter sections (`flow.param.<id>`).
        3. Normalize IC/BC/sinks-sources sections.
        4. Validate the final typed model with Pydantic.
        """
        if flow_section is None:
            return cls()
        if not isinstance(flow_section, Mapping):
            raise ValueError("TOML section 'flow' must be a mapping when provided")

        raw_param_list = flow_section.get("param_list", [])
        if raw_param_list is None:
            raw_param_list = []
        if not isinstance(raw_param_list, (list, tuple)):
            raise ValueError(
                "TOML section 'flow.param_list' must be a list of ids when provided"
            )

        raw_param = flow_section.get("param", {})
        if raw_param is None:
            raw_param = {}
        if not isinstance(raw_param, Mapping):
            raise ValueError("TOML section 'flow.param' must be a mapping when provided")
        if flow_section.get("param_values") is not None:
            raise ValueError("TOML section 'flow.param_values' is no longer supported.")

        raw_bc = flow_section.get("bc", {})
        if raw_bc is None:
            raw_bc = {}
        if not isinstance(raw_bc, Mapping):
            raise ValueError("TOML section 'flow.bc' must be a mapping when provided")

        raw_ic = flow_section.get("ic", {})
        if raw_ic is None:
            raw_ic = {}
        if not isinstance(raw_ic, Mapping):
            raise ValueError("TOML section 'flow.ic' must be a mapping when provided")

        raw_sinks_sources = flow_section.get("sinks_sources", {})
        if raw_sinks_sources is None:
            raw_sinks_sources = {}
        if not isinstance(raw_sinks_sources, Mapping):
            raise ValueError(
                "TOML section 'flow.sinks_sources' must be a mapping when provided"
            )

        raw_active_sinks_sources = flow_section.get("active_sinks_sources", [])
        if raw_active_sinks_sources is None:
            raw_active_sinks_sources = []
        if not isinstance(raw_active_sinks_sources, (list, tuple)):
            raise ValueError(
                "TOML section 'flow.active_sinks_sources' must be a list when provided"
            )

        raw_active_bc = flow_section.get("active_bc", [])
        if raw_active_bc is None:
            raw_active_bc = []
        if not isinstance(raw_active_bc, (list, tuple)):
            raise ValueError(
                "TOML section 'flow.active_bc' must be a list when provided"
            )

        # Parameter payloads are resolved against field-param section grammar.
        parsed_param = parse_flow_param_sections(
            raw_param,
            base_dir=base_dir,
            section_prefix="flow.param",
        )
        declared_param = list(raw_param_list)
        if len(declared_param) == 0 and len(parsed_param) > 0:
            declared_param = list(parsed_param.keys())

        # Keep raw TOML payloads for IC/BC/sinks_sources here and let field
        # validators normalize exactly once.
        #
        # Rationale:
        # - `FlowConfig` already defines dedicated validators for `ic`, `bc`,
        #   and `sinks_sources`;
        # - pre-normalizing here and validating again may trigger false legacy
        #   detections (for example normalized key "drainage" seen as deprecated
        #   input on second pass).
        parsed_ic = raw_ic
        parsed_bc = _resolve_boundary_condition_forcing_paths(
            raw_bc,
            base_dir=base_dir,
        )
        parsed_sinks_sources = _resolve_well_forcing_paths(
            raw_sinks_sources,
            base_dir=base_dir,
        )
        raw_flow_regime = flow_section.get("flow_regime", "transient")
        raw_runtime_backend = flow_section.get("runtime_backend", "local")
        return cls(
            flow_regime=raw_flow_regime,
            runtime_backend=raw_runtime_backend,
            param_list=declared_param,
            param=parsed_param,
            ic=parsed_ic,
            bc=parsed_bc,
            sinks_sources=parsed_sinks_sources,
            active_sinks_sources=list(raw_active_sinks_sources),
            active_bc=list(raw_active_bc),
        )
def _parse_flow_ic_section(ic_cfg: Mapping[str, object]) -> FlowInitialConditions | None:
    """
    Parse and normalize one single `[flow.ic]` payload.

    Supported shapes:
    - Preferred: flat `[flow.ic]` with keys `type`, `value`, `unit|units`, `description`,
      where `value` can be numeric or `"<value> <unit>"`.
    """
    return normalize_flow_initial_conditions(ic_cfg, location_prefix="flow.ic")


def _resolve_well_forcing_paths(
    raw_sinks_sources: Mapping[str, object],
    *,
    base_dir: Path,
) -> dict[str, object]:
    """Resolve relative CSV paths declared under flow.sinks_sources.wells.*.forcing."""
    payload = dict(raw_sinks_sources)
    wells = payload.get("wells")
    if not isinstance(wells, Mapping):
        return payload

    resolved_wells: dict[str, object] = {}
    for well_id, raw_well in wells.items():
        if not isinstance(raw_well, Mapping):
            resolved_wells[str(well_id)] = raw_well
            continue
        well_payload = dict(raw_well)
        forcing = well_payload.get("forcing")
        if isinstance(forcing, Mapping):
            forcing_payload = dict(forcing)
            path_value = forcing_payload.get("path_file")
            if isinstance(path_value, str) and path_value.strip() != "":
                path = Path(path_value).expanduser()
                if not path.is_absolute():
                    path = (base_dir / path).resolve()
                forcing_payload["path_file"] = path
            well_payload["forcing"] = forcing_payload
        resolved_wells[str(well_id)] = well_payload
    payload["wells"] = resolved_wells
    return payload


def _resolve_boundary_condition_forcing_paths(
    raw_bc: Mapping[str, object],
    *,
    base_dir: Path,
) -> dict[str, object]:
    """Resolve relative CSV paths declared under flow.bc.*.forcing."""
    payload = dict(raw_bc)

    def _resolve_forcing_mapping(item: object) -> object:
        if not isinstance(item, Mapping):
            return item
        item_payload = dict(item)
        forcing = item_payload.get("forcing")
        if isinstance(forcing, Mapping):
            forcing_payload = dict(forcing)
            path_value = forcing_payload.get("path_file")
            if isinstance(path_value, str) and path_value.strip() != "":
                path = Path(path_value).expanduser()
                if not path.is_absolute():
                    path = (base_dir / path).resolve()
                forcing_payload["path_file"] = path
            item_payload["forcing"] = forcing_payload
        return item_payload

    dirichlet = payload.get("dirichlet")
    if isinstance(dirichlet, Mapping):
        resolved_dirichlet: dict[str, object] = {}
        for bc_id, raw_item in dirichlet.items():
            resolved_dirichlet[str(bc_id)] = _resolve_forcing_mapping(raw_item)
        payload["dirichlet"] = resolved_dirichlet

    for key, raw_item in list(payload.items()):
        if key in {"dirichlet", "cauchy", "robin"}:
            continue
        payload[key] = _resolve_forcing_mapping(raw_item)

    return payload


