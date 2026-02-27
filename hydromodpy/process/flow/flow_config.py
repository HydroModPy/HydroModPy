"""Pydantic configuration model for flow-process parameter definitions.

This module validates and normalizes the `[flow.param.<id>]` and `[flow.bc]`
payloads from TOML into dictionaries consumable by `Flow`.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from hydromodpy.field.core.field_param_config import (
    resolve_field_param_config_payload,
)


class FlowConfig(BaseModel):
    """Flow-process configuration.

    Parameters are stored in `param` where keys are parameter ids (`K`, `S`,
    `Sy`, ...) and values are resolved FieldParamConfig payloads.
    """

    param: dict[str, dict[str, object]] = Field(
        default_factory=dict,
        description=(
            "Mapping of flow-parameter identifiers to resolved FieldParamConfig "
            "payloads."
        ),
    )
    bc: dict[str, object] = Field(
        default_factory=dict,
        description="Mapping of flow boundary-condition payloads.",
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

    @field_validator("bc", mode="before")
    @classmethod
    def _validate_bc(cls, value):
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("flow.bc must be a mapping payload")
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

        parsed_param = _parse_flow_param_sections(raw_param, base_dir=base_dir)
        parsed_bc = _parse_flow_bc_sections(raw_bc)
        return cls(param=parsed_param, bc=parsed_bc)


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
    - `bc["dirichlet"]`: mapping with optional `ocean` and `stream` payloads
    - `bc["cauchy"]`: mapping with optional `drainage` payload
    - `bc["robin"]`: legacy alias accepted for `cauchy`
    """
    parsed: dict[str, object] = {}

    dirichlet_payload = bc_cfg.get("dirichlet")
    if dirichlet_payload is not None:
        if not isinstance(dirichlet_payload, Mapping):
            raise ValueError("flow.bc.dirichlet must be a mapping when provided")

        parsed_dirichlet: dict[str, dict[str, object]] = {}
        for key in ("ocean", "stream"):
            item = dirichlet_payload.get(key)
            if item is None:
                continue
            if not isinstance(item, Mapping):
                raise ValueError(f"flow.bc.dirichlet.{key} must be a mapping")
            normalized_item = dict(item)
            if "units" not in normalized_item and "unit" in normalized_item:
                normalized_item["units"] = normalized_item["unit"]
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
