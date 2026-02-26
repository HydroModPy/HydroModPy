"""Pydantic configuration model for flow-process parameter definitions.

This module validates and normalizes the `[flow.param.<id>]` payloads from TOML
into resolved dictionaries consumable by `Flow`.
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

        parsed_param = _parse_flow_param_sections(raw_param, base_dir=base_dir)
        return cls(param=parsed_param)


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
