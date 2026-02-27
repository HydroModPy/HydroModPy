"""Pydantic configuration model for flow-process definitions.

This module validates and normalizes `[flow]`, `[flow.param.<id>]`, `[flow.ic]`,
`[flow.bc]`, and `[flow.sinks_sources]` payloads from TOML into objects
consumable by `Flow`.
"""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Real
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from hydromodpy.config.param_level import ParamLevel
from hydromodpy.field.core.field_param_config import (
    resolve_field_param_config_payload,
)


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

    Parameters are stored in `param` where keys are parameter ids (`K`, `S`,
    `Sy`, ...) and values are resolved FieldParamConfig payloads.
    """

    flow_regime: Annotated[Literal["steady", "transient"], ParamLevel("user")] = Field(
        default="transient",
        description=(
            "Global flow simulation regime used by solvers consuming [flow] "
            "(steady or transient)."
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

    @field_validator("param", mode="before")
    @classmethod
    def _validate_param(cls, value):
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
            out[param_id] = dict(raw_payload)
        return out

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
        return dict(value)

    @field_validator("ic", mode="before")
    @classmethod
    def _validate_ic(cls, value):
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("flow.ic must be a mapping payload")

        out: dict[str, dict[str, object]] = {}
        for raw_key, raw_payload in value.items():
            ic_id = str(raw_key).strip()
            if ic_id == "":
                raise ValueError("flow.ic cannot contain empty condition ids")
            if not isinstance(raw_payload, Mapping):
                raise ValueError(
                    f"flow.ic['{ic_id}'] must be a mapping payload"
                )
            out[ic_id] = dict(raw_payload)
        return out

    @field_validator("sinks_sources", mode="before")
    @classmethod
    def _validate_sinks_sources(cls, value):
        if value is None:
            return {}
        if isinstance(value, FlowSinksSourcesConfig):
            return value
        if not isinstance(value, Mapping):
            raise ValueError("flow.sinks_sources must be a mapping payload")
        return dict(value)

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

        raw_param = flow_section.get("param", {})
        if raw_param is None:
            raw_param = {}
        if not isinstance(raw_param, Mapping):
            raise ValueError("TOML section 'flow.param' must be a mapping when provided")

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

        parsed_param = _parse_flow_param_sections(raw_param, base_dir=base_dir)
        parsed_ic = _parse_flow_ic_sections(raw_ic)
        parsed_bc = _parse_flow_bc_sections(raw_bc)
        parsed_sinks_sources = _parse_flow_sinks_sources_sections(raw_sinks_sources)
        raw_flow_regime = flow_section.get("flow_regime", "transient")
        return cls(
            flow_regime=raw_flow_regime,
            param=parsed_param,
            ic=parsed_ic,
            bc=parsed_bc,
            sinks_sources=parsed_sinks_sources,
        )


def _parse_flow_param_sections(
    param_cfg: Mapping[str, object], *, base_dir: Path
) -> dict[str, dict[str, object]]:
    """Parse `[flow.param.<id>]` entries using field_param grammar."""
    parsed: dict[str, dict[str, object]] = {}
    for raw_id, raw_payload in param_cfg.items():
        param_id = str(raw_id).strip()
        if param_id == "":
            raise ValueError("flow.param cannot contain empty parameter ids")
        if not isinstance(raw_payload, Mapping):
            raise ValueError(
                f"flow.param.{param_id} must be a mapping with field_param-style sections"
            )
        parsed[param_id] = _field_param_config_from_flow_payload(
            payload=raw_payload,
            param_id=param_id,
            base_dir=base_dir,
        )
    return parsed


def _field_param_config_from_flow_payload(
    *, payload: Mapping[str, object], param_id: str, base_dir: Path
) -> dict[str, object]:
    """Build one resolved FieldParamConfig mapping from one TOML parameter payload."""
    return resolve_field_param_config_payload(
        payload,
        param_id=param_id,
        base_dir=base_dir,
        section_label=f"flow.param.{param_id}",
    )


def _parse_flow_bc_sections(bc_cfg: Mapping[str, object]) -> dict[str, object]:
    """Parse and normalize `[flow.bc]` entries.

    Normalized structure:
    - `bc["dirichlet"]`: mapping with optional payloads for
      `ocean`, `stream`, `north_boundary`, `south_boundary`,
      `east_boundary`, `west_boundary`
    - `bc["cauchy"]`: mapping with optional `drainage` payload
    - `bc["robin"]`: legacy alias accepted for `cauchy`
    """
    parsed: dict[str, object] = {}
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

        parsed_dirichlet: dict[str, dict[str, object]] = {}
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
            normalized_item = dict(item)
            if "units" not in normalized_item and "unit" in normalized_item:
                normalized_item["units"] = normalized_item["unit"]
            if "application_domain" not in normalized_item and key in dirichlet_domain_defaults:
                normalized_item["application_domain"] = dirichlet_domain_defaults[key]
            normalized_item.setdefault("data_value", False)
            normalized_item.setdefault("units", "m")
            parsed_dirichlet[key] = normalized_item

        if parsed_dirichlet:
            parsed["dirichlet"] = parsed_dirichlet

    cauchy_payload = bc_cfg.get("cauchy")
    if cauchy_payload is not None:
        if not isinstance(cauchy_payload, Mapping):
            raise ValueError("flow.bc.cauchy must be a mapping when provided")

        parsed_cauchy: dict[str, dict[str, object]] = {}
        drainage_item = cauchy_payload.get("drainage")
        if drainage_item is not None:
            if not isinstance(drainage_item, Mapping):
                raise ValueError("flow.bc.cauchy.drainage must be a mapping")
            normalized_drainage = dict(drainage_item)
            if "units" not in normalized_drainage and "unit" in normalized_drainage:
                normalized_drainage["units"] = normalized_drainage["unit"]
            normalized_drainage.setdefault("data_value", False)
            normalized_drainage.setdefault("units", "m2/s")
            normalized_drainage.setdefault("type", "cauchy")
            parsed_cauchy["drainage"] = normalized_drainage

        if parsed_cauchy:
            parsed["cauchy"] = parsed_cauchy

    robin_payload = bc_cfg.get("robin")
    if robin_payload is not None:
        if not isinstance(robin_payload, Mapping):
            raise ValueError("flow.bc.robin must be a mapping when provided")

        parsed_robin: dict[str, dict[str, object]] = {}
        drainage_item = robin_payload.get("drainage")
        if drainage_item is not None:
            if not isinstance(drainage_item, Mapping):
                raise ValueError("flow.bc.robin.drainage must be a mapping")
            normalized_drainage = dict(drainage_item)
            if "units" not in normalized_drainage and "unit" in normalized_drainage:
                normalized_drainage["units"] = normalized_drainage["unit"]
            normalized_drainage.setdefault("data_value", False)
            normalized_drainage.setdefault("units", "m2/s")
            normalized_drainage.setdefault("type", "robin")
            parsed_robin["drainage"] = normalized_drainage

        if parsed_robin and "cauchy" not in parsed:
            parsed["robin"] = parsed_robin

    legacy_drainage = bc_cfg.get("drainage")
    if "cauchy" not in parsed and "robin" not in parsed and isinstance(legacy_drainage, Mapping):
        normalized_legacy_drainage = dict(legacy_drainage)
        if "units" not in normalized_legacy_drainage and "unit" in normalized_legacy_drainage:
            normalized_legacy_drainage["units"] = normalized_legacy_drainage["unit"]
        normalized_legacy_drainage.setdefault("data_value", False)
        normalized_legacy_drainage.setdefault("units", "m2/s")
        normalized_legacy_drainage.setdefault("type", "cauchy")
        parsed["robin"] = {"drainage": normalized_legacy_drainage}

    for raw_key, raw_payload in bc_cfg.items():
        key = str(raw_key).strip()
        if key == "":
            raise ValueError("flow.bc cannot contain empty keys")
        if key in {"dirichlet", "cauchy", "robin", "drainage"}:
            continue
        if isinstance(raw_payload, Mapping):
            parsed[key] = dict(raw_payload)
        else:
            parsed[key] = raw_payload

    return parsed


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
            if not isinstance(payload_dict["value"], Real):
                raise TypeError(f"flow.ic.{ic_id}.value must be a numeric value")
            value = float(payload_dict["value"])
        else:
            raw_value = payload_dict.get("value", 0.0)
            if not isinstance(raw_value, Real):
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
