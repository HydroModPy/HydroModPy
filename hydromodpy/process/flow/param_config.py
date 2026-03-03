# -*- coding: utf-8 -*-
"""
Flow Parameter Parsers
======================

Utilities that normalize and resolve `[flow.param]` payloads into the internal
FieldParamConfig-compatible dictionaries consumed by `FlowConfig`.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.field.core.field_param_config import (
    resolve_field_param_config_payload,
    validate_resolved_field_param_data,
)

__all__ = [
    "normalize_flow_param_payloads",
    "parse_flow_param_sections",
]


_FIELD_PARAM_SECTION_KEYS = (
    "field",
    "field_homogeneous",
    "field_heterogeneous",
    "field_vertical_profile",
)


def normalize_flow_param_payloads(
    value: Mapping[str, object] | None,
    *,
    location_prefix: str = "flow.param",
) -> dict[str, dict[str, object]]:
    """
    Normalize one `flow.param` mapping into resolved field-param payloads.

    Supports both:
    - explicit field-param section grammar (`field`, `field_homogeneous`, ...),
    - already-resolved compact mappings.
    """
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{location_prefix} must be a mapping of parameter id to payload")

    out: dict[str, dict[str, object]] = {}
    for raw_key, raw_payload in value.items():
        param_id = str(raw_key).strip()
        if param_id == "":
            raise ValueError(f"{location_prefix} cannot contain empty parameter ids")
        if not isinstance(raw_payload, Mapping):
            raise ValueError(f"{location_prefix}['{param_id}'] must be a mapping payload")

        payload = dict(raw_payload)
        # Sectioned grammar (`field_*` blocks) is resolved first.
        if any(key in payload for key in _FIELD_PARAM_SECTION_KEYS):
            out[param_id] = resolve_field_param_config_payload(
                payload,
                param_id=param_id,
                section_label=f"{location_prefix}.{param_id}",
            )
        else:
            # Compact payloads are validated as already-resolved dictionaries.
            payload.setdefault("id", param_id)
            out[param_id] = validate_resolved_field_param_data(payload)
    return out


def parse_flow_param_sections(
    param_cfg: Mapping[str, object],
    *,
    base_dir: Path,
    section_prefix: str = "flow.param",
) -> dict[str, dict[str, object]]:
    """Parse `flow.param` TOML payload using field-param section grammar."""
    parsed: dict[str, dict[str, object]] = {}
    for raw_id, raw_payload in param_cfg.items():
        param_id = str(raw_id).strip()
        if param_id == "":
            raise ValueError(f"{section_prefix} cannot contain empty parameter ids")
        if not isinstance(raw_payload, Mapping):
            raise ValueError(
                f"{section_prefix}.{param_id} must be a mapping with field_param-style sections"
            )
        parsed[param_id] = field_param_config_from_flow_payload(
            payload=raw_payload,
            param_id=param_id,
            base_dir=base_dir,
            section_prefix=section_prefix,
        )
    return parsed


def field_param_config_from_flow_payload(
    *,
    payload: Mapping[str, Any],
    param_id: str,
    base_dir: Path,
    section_prefix: str = "flow.param",
) -> dict[str, object]:
    """
    Build one resolved field-parameter mapping from one TOML payload.

    This is a thin wrapper around the shared field-param resolver, keeping a
    flow-specific section prefix for precise error messages.
    """
    return resolve_field_param_config_payload(
        payload,
        param_id=param_id,
        base_dir=base_dir,
        section_label=f"{section_prefix}.{param_id}",
    )
