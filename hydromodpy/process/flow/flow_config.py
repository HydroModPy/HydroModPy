"""Pydantic configuration model for flow-process definitions.

This module validates and normalizes `[flow]`, `[flow.param.<id>]`, `[flow.ic]`,
`[flow.bc]`, and `[flow.sinks_sources]` payloads from TOML into objects
consumable by `Flow`.
"""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Real
from pathlib import Path
from typing import Annotated, Literal, cast

from pydantic import BaseModel, Field, field_validator, model_validator

from hydromodpy.config.param_level import ParamLevel
from hydromodpy.field.core.field_param_config import (
    resolve_field_param_config_payload,
    validate_resolved_field_param_data,
)

_ALLOWED_BC_APPLICATION_DOMAINS = {"top", "north side", "west side", "east side", "south side"}


class FlowWellConfig(BaseModel):
    """Typed payload for one well source/sink definition."""

    cell: tuple[int, int, int] = Field(
        ...,
        description="Cell indices as [lay, row, col] (0-based).",
    )
    flux: float | list[float] = Field(
        ...,
        description=(
            "Well rate [L3/T]. Scalar for constant rate, or one value per stress period."
        ),
    )
    units: str = Field(default="m3/s", description="Units of flux values.")
    description: str = Field(default="", description="Optional well description.")

    @field_validator("cell", mode="before")
    @classmethod
    def _validate_cell(cls, value):
        if isinstance(value, Mapping):
            try:
                raw_seq = [value["lay"], value["row"], value["col"]]
            except KeyError as exc:
                raise ValueError("well.cell mapping must define lay, row, and col") from exc
        elif isinstance(value, (list, tuple)):
            raw_seq = list(value)
        else:
            raise TypeError("well.cell must be a mapping or a 3-item list [lay, row, col]")

        if len(raw_seq) != 3:
            raise ValueError("well.cell must contain exactly 3 values: [lay, row, col]")

        parsed: list[int] = []
        for axis, raw_item in zip(("lay", "row", "col"), raw_seq):
            if isinstance(raw_item, bool):
                raise TypeError(f"well.cell.{axis} must be an integer")
            if isinstance(raw_item, Real):
                numeric = float(raw_item)
                if not numeric.is_integer():
                    raise TypeError(f"well.cell.{axis} must be an integer")
                index_value = int(numeric)
            else:
                raise TypeError(f"well.cell.{axis} must be an integer")
            if index_value < 0:
                raise ValueError(f"well.cell.{axis} must be >= 0")
            parsed.append(index_value)
        return tuple(parsed)

    @field_validator("flux", mode="before")
    @classmethod
    def _validate_flux(cls, value):
        if isinstance(value, bool):
            raise TypeError("well.flux must be numeric or a list of numeric values")
        if isinstance(value, Real):
            return float(value)
        if isinstance(value, (list, tuple)):
            if len(value) == 0:
                raise ValueError("well.flux list cannot be empty")
            parsed: list[float] = []
            for idx, raw_item in enumerate(value):
                if isinstance(raw_item, bool) or not isinstance(raw_item, Real):
                    raise TypeError(f"well.flux[{idx}] must be numeric")
                parsed.append(float(raw_item))
            return parsed
        raise TypeError("well.flux must be numeric or a list of numeric values")


class FlowSinksSourcesConfig(BaseModel):
    """Typed container for sinks/sources handled by Flow."""

    wells: dict[str, FlowWellConfig] = Field(
        default_factory=dict,
        description="Mapping of well ids to typed well payloads.",
    )

    @field_validator("wells", mode="before")
    @classmethod
    def _validate_wells(cls, value):
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("flow.sinks_sources.wells must be a mapping payload")
        out: dict[str, object] = {}
        for raw_key, raw_payload in value.items():
            well_id = str(raw_key).strip()
            if well_id == "":
                raise ValueError("flow.sinks_sources.wells cannot contain empty well ids")
            out[well_id] = raw_payload
        return out


class FlowConfig(BaseModel):
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
            "Mapping of flow boundary-condition payloads. "
            "Supported [flow.bc.dirichlet] keys are: ocean, stream, "
            "north_boundary, south_boundary, east_boundary, west_boundary "
            "(no top_boundary)."
        ),
    )
    ic: dict[str, dict[str, object]] = Field(
        default_factory=dict,
        description="Mapping of flow initial-condition payloads.",
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
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("flow.bc must be a mapping payload")
        return _parse_flow_bc_sections(dict(value))

    @field_validator("ic", mode="before")
    @classmethod
    def _validate_ic(cls, value):
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("flow.ic must be a mapping payload")
        return _parse_flow_ic_sections(dict(value))

    @field_validator("sinks_sources", mode="before")
    @classmethod
    def _validate_sinks_sources(cls, value):
        if value is None:
            return {}
        if isinstance(value, FlowSinksSourcesConfig):
            return value
        if not isinstance(value, Mapping):
            raise ValueError("flow.sinks_sources must be a mapping payload")
        return _parse_flow_sinks_sources_sections(dict(value))

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

        parsed_ic = _parse_flow_ic_sections(raw_ic)
        parsed_bc = _parse_flow_bc_sections(raw_bc)
        parsed_sinks_sources = _parse_flow_sinks_sources_sections(raw_sinks_sources)
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


def _coerce_numeric_boundary_value(*, value: object, location: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{location} must be a numeric value")
    return float(value)


def _normalize_boundary_units(
    payload: Mapping[str, object],
    *,
    default_units: str,
) -> str:
    if "units" in payload:
        return str(payload["units"])
    if "unit" in payload:
        return str(payload["unit"])
    return default_units


def _normalize_dirichlet_boundary_payload(
    *,
    bc_id: str,
    payload: Mapping[str, object],
    location_prefix: str,
    default_application_domain: str | None = None,
) -> dict[str, object]:
    if "value" not in payload:
        raise ValueError(f"{location_prefix}.value is required")

    value = _coerce_numeric_boundary_value(
        value=payload["value"],
        location=f"{location_prefix}.value",
    )

    raw_type = str(payload.get("type", "dirichlet")).strip().lower()
    if raw_type != "dirichlet":
        raise ValueError(f"{location_prefix}.type must be 'dirichlet'")

    raw_application_domain = payload.get("application_domain", default_application_domain)
    if not isinstance(raw_application_domain, str):
        raise TypeError(f"{location_prefix}.application_domain must be a string")
    application_domain = raw_application_domain.strip()
    if application_domain == "":
        raise ValueError(f"{location_prefix}.application_domain cannot be empty")
    if application_domain not in _ALLOWED_BC_APPLICATION_DOMAINS:
        raise ValueError(
            f"{location_prefix}.application_domain contains an invalid value: {application_domain}"
        )

    data_value = bool(payload.get("data_value", False))
    description = str(
        payload.get("description", f"Dirichlet boundary condition '{bc_id}' on {application_domain}")
    )
    if data_value and "(data_value=True)" not in description:
        description = f"{description} (data_value=True)"

    return {
        "id": bc_id,
        "value": value,
        "description": description,
        "units": _normalize_boundary_units(payload, default_units="m"),
        "type": "dirichlet",
        "data_value": data_value,
        "application_domain": application_domain,
    }


def _normalize_drainage_boundary_payload(
    *,
    payload: Mapping[str, object],
    location_prefix: str,
    expected_type: str,
) -> dict[str, object]:
    if "value" not in payload:
        raise ValueError(f"{location_prefix}.value is required")

    value = _coerce_numeric_boundary_value(
        value=payload["value"],
        location=f"{location_prefix}.value",
    )

    raw_type = str(payload.get("type", expected_type)).strip().lower()
    if raw_type not in {"cauchy", "robin"}:
        raise ValueError(f"{location_prefix}.type must be 'cauchy' or 'robin'")

    raw_application_domain = payload.get("application_domain")
    if not isinstance(raw_application_domain, str):
        raise TypeError(f"{location_prefix}.application_domain must be a string")
    application_domain = raw_application_domain.strip()
    if application_domain == "":
        raise ValueError(f"{location_prefix}.application_domain cannot be empty")
    if application_domain not in _ALLOWED_BC_APPLICATION_DOMAINS:
        raise ValueError(
            f"{location_prefix}.application_domain contains an invalid value: {application_domain}"
        )

    return {
        "id": "drainage",
        "value": value,
        "description": str(
            payload.get(
                "description",
                f"{raw_type.capitalize()} drainage boundary condition on {application_domain}",
            )
        ),
        "units": _normalize_boundary_units(payload, default_units="m2/s"),
        "type": raw_type,
        "data_value": bool(payload.get("data_value", False)),
        "application_domain": application_domain,
    }


def _normalize_generic_boundary_payload(
    *,
    bc_id: str,
    payload: Mapping[str, object],
    location_prefix: str,
) -> dict[str, object]:
    if "value" not in payload:
        raise ValueError(f"{location_prefix}.value is required")

    value = _coerce_numeric_boundary_value(
        value=payload["value"],
        location=f"{location_prefix}.value",
    )
    bc_type = str(payload.get("type", "dirichlet")).strip().lower() or "dirichlet"
    if bc_type not in {"dirichlet", "cauchy", "robin"}:
        raise ValueError(f"{location_prefix}.type must be one of: dirichlet, cauchy, robin")

    default_units = "m2/s" if bc_type in {"cauchy", "robin"} else "m"
    normalized: dict[str, object] = {
        "id": bc_id,
        "value": value,
        "description": str(payload.get("description", f"Boundary condition '{bc_id}'")),
        "units": _normalize_boundary_units(payload, default_units=default_units),
        "type": bc_type,
        "data_value": bool(payload.get("data_value", False)),
    }

    raw_application_domain = payload.get("application_domain")
    if raw_application_domain is not None:
        if not isinstance(raw_application_domain, str):
            raise TypeError(f"{location_prefix}.application_domain must be a string")
        application_domain = raw_application_domain.strip()
        if application_domain == "":
            raise ValueError(f"{location_prefix}.application_domain cannot be empty")
        if application_domain not in _ALLOWED_BC_APPLICATION_DOMAINS:
            raise ValueError(
                f"{location_prefix}.application_domain contains an invalid value: {application_domain}"
            )
        normalized["application_domain"] = application_domain

    return normalized


def _parse_flow_bc_sections(bc_cfg: Mapping[str, object]) -> dict[str, object]:
    """Parse and normalize `[flow.bc]` entries as a flat validated mapping."""
    parsed: dict[str, dict[str, object]] = {}
    dirichlet_domain_defaults = {
        "north_boundary": "north side",
        "south_boundary": "south side",
        "east_boundary": "east side",
        "west_boundary": "west side",
    }

    dirichlet_payload = bc_cfg.get("dirichlet")
    if dirichlet_payload is not None:
        if not isinstance(dirichlet_payload, Mapping):
            raise ValueError("flow.bc.dirichlet must be a mapping when provided")
        for key in (
            "ocean",
            "stream",
            "north_boundary",
            "south_boundary",
            "east_boundary",
            "west_boundary",
        ):
            item = dirichlet_payload.get(key)
            if item is None:
                continue
            if not isinstance(item, Mapping):
                raise ValueError(f"flow.bc.dirichlet.{key} must be a mapping")
            parsed[key] = _normalize_dirichlet_boundary_payload(
                bc_id=key,
                payload=item,
                location_prefix=f"flow.bc.dirichlet.{key}",
                default_application_domain=dirichlet_domain_defaults.get(key),
            )

    cauchy_payload = bc_cfg.get("cauchy")
    if cauchy_payload is not None:
        if not isinstance(cauchy_payload, Mapping):
            raise ValueError("flow.bc.cauchy must be a mapping when provided")
        drainage_item = cauchy_payload.get("drainage")
        if drainage_item is not None:
            if not isinstance(drainage_item, Mapping):
                raise ValueError("flow.bc.cauchy.drainage must be a mapping")
            parsed["drainage"] = _normalize_drainage_boundary_payload(
                payload=drainage_item,
                location_prefix="flow.bc.cauchy.drainage",
                expected_type="cauchy",
            )

    robin_payload = bc_cfg.get("robin")
    if robin_payload is not None and "drainage" not in parsed:
        if not isinstance(robin_payload, Mapping):
            raise ValueError("flow.bc.robin must be a mapping when provided")
        drainage_item = robin_payload.get("drainage")
        if drainage_item is not None:
            if not isinstance(drainage_item, Mapping):
                raise ValueError("flow.bc.robin.drainage must be a mapping")
            parsed["drainage"] = _normalize_drainage_boundary_payload(
                payload=drainage_item,
                location_prefix="flow.bc.robin.drainage",
                expected_type="robin",
            )

    legacy_drainage = bc_cfg.get("drainage")
    if "drainage" not in parsed and isinstance(legacy_drainage, Mapping):
        parsed["drainage"] = _normalize_drainage_boundary_payload(
            payload=legacy_drainage,
            location_prefix="flow.bc.drainage",
            expected_type="cauchy",
        )

    for raw_key, raw_payload in bc_cfg.items():
        key = str(raw_key).strip()
        if key == "":
            raise ValueError("flow.bc cannot contain empty keys")
        if key in {"dirichlet", "cauchy", "robin", "drainage"} or key in parsed:
            continue
        if not isinstance(raw_payload, Mapping):
            raise TypeError(f"flow.bc.{key} must be a mapping payload")

        if key in dirichlet_domain_defaults:
            parsed[key] = _normalize_dirichlet_boundary_payload(
                bc_id=key,
                payload=raw_payload,
                location_prefix=f"flow.bc.{key}",
                default_application_domain=dirichlet_domain_defaults[key],
            )
        elif key == "ocean" or key == "stream":
            parsed[key] = _normalize_dirichlet_boundary_payload(
                bc_id=key,
                payload=raw_payload,
                location_prefix=f"flow.bc.{key}",
                default_application_domain="top",
            )
        elif key == "drainage":
            parsed[key] = _normalize_drainage_boundary_payload(
                payload=raw_payload,
                location_prefix="flow.bc.drainage",
                expected_type="cauchy",
            )
        else:
            parsed[key] = _normalize_generic_boundary_payload(
                bc_id=key,
                payload=raw_payload,
                location_prefix=f"flow.bc.{key}",
            )

    return cast(dict[str, object], parsed)


def _parse_flow_ic_sections(ic_cfg: Mapping[str, object]) -> dict[str, dict[str, object]]:
    """Parse and normalize `[flow.ic.<id>]` entries.

    Expected shape:
    - `flow.ic.<id>.type` in {"top", "bot", "custom"} (default: "custom")
    - `flow.ic.<id>.value` (required only when type="custom")
    - optional `unit` or `units` (default: "m")
    - optional `description`
    """
    parsed: dict[str, dict[str, object]] = {}

    for raw_key, raw_payload in ic_cfg.items():
        ic_id = str(raw_key).strip()
        if ic_id == "":
            raise ValueError("flow.ic cannot contain empty condition ids")

        if isinstance(raw_payload, bool):
            raise TypeError(f"flow.ic.{ic_id} must be a mapping or numeric value")
        if isinstance(raw_payload, Real):
            payload_dict: dict[str, object] = {"type": "custom", "value": float(raw_payload)}
        elif isinstance(raw_payload, Mapping):
            payload_dict = dict(raw_payload)
        else:
            raise TypeError(
                f"flow.ic.{ic_id} must be a mapping or numeric value"
            )

        raw_type = payload_dict.get("type", "custom")
        ic_type = str(raw_type).strip().lower()
        if ic_type not in {"top", "bot", "custom"}:
            raise ValueError(
                f"flow.ic.{ic_id}.type must be one of: 'top', 'bot', 'custom'"
            )

        if ic_type == "custom":
            if "value" not in payload_dict:
                raise ValueError(f"flow.ic.{ic_id}.value is required when type='custom'")
            if isinstance(payload_dict["value"], bool) or not isinstance(payload_dict["value"], Real):
                raise TypeError(f"flow.ic.{ic_id}.value must be a numeric value")
            value = float(payload_dict["value"])
        else:
            raw_value = payload_dict.get("value", 0.0)
            if isinstance(raw_value, bool) or not isinstance(raw_value, Real):
                raise TypeError(f"flow.ic.{ic_id}.value must be a numeric value when provided")
            value = float(raw_value)

        if "units" not in payload_dict and "unit" in payload_dict:
            payload_dict["units"] = payload_dict["unit"]
        payload_dict.setdefault("units", "m")
        payload_dict.setdefault(
            "description",
            f"Initial condition '{ic_id}'",
        )
        payload_dict["type"] = ic_type
        payload_dict["value"] = value
        parsed[ic_id] = payload_dict

    return parsed


def _parse_flow_sinks_sources_sections(
    sinks_sources_cfg: Mapping[str, object],
) -> dict[str, object]:
    """Parse and normalize `[flow.sinks_sources]` entries."""
    parsed: dict[str, object] = {}

    raw_wells = sinks_sources_cfg.get("wells", {})
    if raw_wells is None:
        raw_wells = {}
    if not isinstance(raw_wells, Mapping):
        raise ValueError("flow.sinks_sources.wells must be a mapping when provided")

    parsed_wells: dict[str, dict[str, object]] = {}
    for raw_key, raw_payload in raw_wells.items():
        well_id = str(raw_key).strip()
        if well_id == "":
            raise ValueError("flow.sinks_sources.wells cannot contain empty well ids")
        if not isinstance(raw_payload, Mapping):
            raise ValueError(
                f"flow.sinks_sources.wells.{well_id} must be a mapping payload"
            )
        parsed_wells[well_id] = dict(raw_payload)

    parsed["wells"] = parsed_wells
    return parsed
