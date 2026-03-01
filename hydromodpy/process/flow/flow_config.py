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
from hydromodpy.process.flow.boundary_conditions import FlowBoundaryConditionConfig
from hydromodpy.process.flow.boundary_conditions_config import (
    normalize_flow_boundary_conditions,
)
from hydromodpy.process.flow.initial_conditions import (
    FlowInitialConditions,
)
from hydromodpy.process.flow.initial_conditions_config import (
    normalize_flow_initial_conditions,
)
from hydromodpy.process.flow.sink_sources import (
    FlowSinksSourcesConfig,
    FlowWellConfig,
)
from hydromodpy.process.flow.sink_sources_config import (
    normalize_flow_sinks_sources,
)
from hydromodpy.process.prototype import ProcessSpatialConfig
from hydromodpy.field.core.field_param_config import (
    resolve_field_param_config_payload,
    validate_resolved_field_param_data,
)

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
            "south_side, east_side, west_side (legacy *_boundary aliases accepted); "
            "[flow.bc.cauchy.drainage]; [flow.bc.robin.drainage]; "
            "and generic [flow.bc.<custom_id>] payloads. "
            "Common required key: value. "
            "Dirichlet keys may omit application_domain when <id> implies it "
            "(for example west_side -> 'west side'). "
            "Drainage (cauchy/robin) requires application_domain explicitly. "
            "Supported application_domain values are: top, north side, south side, "
            "east side, west side. "
            "Default units: m for dirichlet, m2/s for cauchy/robin."
        ),
    )
    ic: FlowInitialConditions | None = Field(
        default=None,
        description=(
            "Validated flow initial-condition structure parsed from [flow.ic]. "
            "Stored as FlowInitialConditions(h=FlowInitialCondition)."
        ),
    )
    sinks_sources: FlowSinksSourcesConfig = Field(
        default_factory=FlowSinksSourcesConfig,
        description="Typed sinks/sources payload (for example pumping wells).",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_param_payload_shapes(cls, value):
        if value is None or not isinstance(value, Mapping):
            return value
        payload = dict(value)
        raw_param_list = payload.get("param_list")
        raw_param = payload.get("param")
        raw_param_values = payload.get("param_values")
        if isinstance(raw_param, Mapping):
            if raw_param_values is not None:
                raise ValueError(
                    "Use either flow.param mapping or legacy flow.param_values mapping, "
                    "but not both at once"
                )
            if raw_param_list is None:
                payload["param_list"] = list(raw_param.keys())
        elif isinstance(raw_param, (list, tuple)):
            # Transitional compatibility with old format:
            # flow.param = ["K", "Ss", "Sy"] + flow.param_values.<id>...
            if raw_param_list is not None:
                raise ValueError(
                    "Use either flow.param_list or legacy flow.param list, "
                    "but not both at once"
                )
            payload["param_list"] = list(raw_param)
            if isinstance(raw_param_values, Mapping):
                payload["param"] = dict(raw_param_values)
            else:
                payload["param"] = {}
        elif raw_param is None and isinstance(raw_param_values, Mapping):
            payload["param"] = dict(raw_param_values)
            if raw_param_list is None:
                payload["param_list"] = list(raw_param_values.keys())

        payload.pop("param_values", None)
        return payload

    @field_validator("param_list", mode="before")
    @classmethod
    def _validate_param_list(cls, value):
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
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("flow.param must be a mapping of parameter id to payload")

        out: dict[str, dict[str, object]] = {}
        for raw_key, raw_payload in value.items():
            param_id = str(raw_key).strip()
            if param_id == "":
                raise ValueError("flow.param cannot contain empty parameter ids")
            if not isinstance(raw_payload, Mapping):
                raise ValueError(
                    f"flow.param['{param_id}'] must be a mapping payload"
                )
            payload = dict(raw_payload)
            if any(
                key in payload
                for key in (
                    "field",
                    "field_homogeneous",
                    "field_heterogeneous",
                    "field_vertical_profile",
                )
            ):
                out[param_id] = resolve_field_param_config_payload(
                    payload,
                    param_id=param_id,
                    section_label=f"flow.param.{param_id}",
                )
            else:
                payload.setdefault("id", param_id)
                out[param_id] = validate_resolved_field_param_data(payload)
        return out

    @model_validator(mode="after")
    def _validate_param_consistency(self):
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
        text = str(value).strip().lower()
        if text not in {"steady", "transient"}:
            raise ValueError("flow.flow_regime must be 'steady' or 'transient'")
        return text

    @field_validator("bc", mode="before")
    @classmethod
    def _validate_bc(cls, value):
        return normalize_flow_boundary_conditions(value, location_prefix="flow.bc")

    @field_validator("ic", mode="before")
    @classmethod
    def _validate_ic(cls, value):
        if value is None:
            return None
        return normalize_flow_initial_conditions(value, location_prefix="flow.ic")

    @field_validator("sinks_sources", mode="before")
    @classmethod
    def _validate_sinks_sources(cls, value):
        return normalize_flow_sinks_sources(value, location_prefix="flow.sinks_sources")

    @classmethod
    def from_toml_section(
        cls,
        flow_section: Mapping[str, object] | None,
        *,
        base_dir: Path,
    ) -> "FlowConfig":
        """Build a validated FlowConfig from the `[flow]` TOML section."""
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
            if isinstance(raw_param, (list, tuple)):
                # Transitional compatibility with previous format:
                # flow.param = ["K", "Ss", "Sy"] + flow.param_values.<id>...
                raw_param_list = list(raw_param)
                raw_param = flow_section.get("param_values", {})
                if raw_param is None:
                    raw_param = {}
                if not isinstance(raw_param, Mapping):
                    raise ValueError(
                        "TOML section 'flow.param_values' must be a mapping when flow.param is a list"
                    )
            else:
                raise ValueError("TOML section 'flow.param' must be a mapping when provided")

        raw_param_values_alias = flow_section.get("param_values")
        if raw_param_values_alias is not None:
            if not isinstance(raw_param_values_alias, Mapping):
                raise ValueError("TOML section 'flow.param_values' must be a mapping when provided")
            if len(raw_param) > 0:
                raise ValueError(
                    "Do not use both flow.param and flow.param_values. "
                    "Use flow.param only."
                )
            raw_param = raw_param_values_alias

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

        parsed_param = _parse_flow_param_sections(
            raw_param,
            base_dir=base_dir,
            section_prefix="flow.param",
        )
        declared_param = list(raw_param_list)
        if len(declared_param) == 0 and len(parsed_param) > 0:
            declared_param = list(parsed_param.keys())

        parsed_ic = _parse_flow_ic_section(raw_ic)
        parsed_bc = normalize_flow_boundary_conditions(raw_bc, location_prefix="flow.bc")
        parsed_sinks_sources = normalize_flow_sinks_sources(
            raw_sinks_sources,
            location_prefix="flow.sinks_sources",
        )
        raw_flow_regime = flow_section.get("flow_regime", "transient")
        return cls(
            flow_regime=raw_flow_regime,
            param_list=declared_param,
            param=parsed_param,
            ic=parsed_ic,
            bc=parsed_bc,
            sinks_sources=parsed_sinks_sources,
        )


def _parse_flow_param_sections(
    param_cfg: Mapping[str, object],
    *,
    base_dir: Path,
    section_prefix: str = "flow.param",
) -> dict[str, dict[str, object]]:
    """Parse flow parameter entries using field_param grammar."""
    parsed: dict[str, dict[str, object]] = {}
    for raw_id, raw_payload in param_cfg.items():
        param_id = str(raw_id).strip()
        if param_id == "":
            raise ValueError(f"{section_prefix} cannot contain empty parameter ids")
        if not isinstance(raw_payload, Mapping):
            raise ValueError(
                f"{section_prefix}.{param_id} must be a mapping with field_param-style sections"
            )
        parsed[param_id] = _field_param_config_from_flow_payload(
            payload=raw_payload,
            param_id=param_id,
            base_dir=base_dir,
            section_prefix=section_prefix,
        )
    return parsed


def _field_param_config_from_flow_payload(
    *,
    payload: Mapping[str, object],
    param_id: str,
    base_dir: Path,
    section_prefix: str = "flow.param",
) -> dict[str, object]:
    """Build one resolved FieldParamConfig mapping from one TOML parameter payload."""
    return resolve_field_param_config_payload(
        payload,
        param_id=param_id,
        base_dir=base_dir,
        section_label=f"{section_prefix}.{param_id}",
    )


def _parse_flow_ic_section(ic_cfg: Mapping[str, object]) -> FlowInitialConditions | None:
    """Parse and normalize one single `[flow.ic]` payload.

    Supported shapes:
    - Preferred: flat `[flow.ic]` with keys `type`, `value`, `unit|units`, `description`.
    """
    return normalize_flow_initial_conditions(ic_cfg, location_prefix="flow.ic")


