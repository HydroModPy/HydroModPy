"""
Flow Initial Condition Normalizers
=================================

Normalization helpers for `[flow.ic]` payloads.

This module accepts compact user payloads and returns the typed runtime/config
structure `FlowInitialConditions`.
"""

from __future__ import annotations

from collections.abc import Mapping

from hydromodpy.core.units import parse_to_canonical_magnitude
from hydromodpy.physics.flow.initial_conditions import (
    FlowInitialCondition,
    FlowInitialConditions,
)


def normalize_flow_initial_conditions(
    value: object | None,
    *,
    location_prefix: str = "flow.ic",
) -> FlowInitialConditions | None:
    """
    Normalize one flow initial-condition payload into `FlowInitialConditions`.

    Accepted input shapes
    ---------------------
    - `None` or `{}` -> `None`
    - `FlowInitialConditions` -> passthrough
    - `FlowInitialCondition` -> wrapped as `{"h": ...}`
    - flat mapping with keys `type`, `value`, `unit|units`, `description`
      where `value` can be numeric or a string like `"12.5 m"`
    """
    if value is None:
        return None
    if isinstance(value, FlowInitialConditions):
        return value
    if isinstance(value, FlowInitialCondition):
        return FlowInitialConditions(h=value)
    if not isinstance(value, Mapping):
        raise TypeError(
            f"{location_prefix} must be a mapping, FlowInitialCondition, or FlowInitialConditions"
        )

    payload = dict(value)
    if len(payload) == 0:
        return None

    # Flow IC is intentionally kept flat in TOML (`[flow.ic]`), hence only
    # direct keys are accepted here.
    direct_keys = {"type", "value", "unit", "units", "description"}
    unknown_keys = [str(key).strip() for key in payload if str(key).strip() not in direct_keys]
    if unknown_keys:
        unknown_text = ", ".join(unknown_keys)
        raise ValueError(
            f"{location_prefix} accepts only direct keys "
            f"[type, value, unit, units, description]. Unknown keys: {unknown_text}"
        )

    normalized = _normalize_single_ic_payload(payload, location_prefix=location_prefix)
    return FlowInitialConditions(h=FlowInitialCondition.model_validate(normalized))


def _normalize_single_ic_payload(
    payload: Mapping[str, object],
    *,
    location_prefix: str,
) -> dict[str, object]:
    """
    Normalize one single flow initial-condition payload.

    Output keys are aligned with `FlowInitialCondition`.
    """
    payload_dict = dict(payload)

    raw_type = payload_dict.get("type", "custom")
    ic_type = str(raw_type).strip().lower()
    if ic_type not in {"top", "bottom", "custom"}:
        raise ValueError(f"{location_prefix}.type must be one of: 'top', 'bottom', 'custom'")

    explicit_units = _extract_explicit_units(payload_dict)
    if ic_type == "custom":
        if "value" not in payload_dict:
            raise ValueError(f"{location_prefix}.value is required when type='custom'")
        payload_dict["value"] = parse_to_canonical_magnitude(
            payload_dict["value"],
            location=f"{location_prefix}.value",
            canonical_unit="m",
            explicit_unit=explicit_units,
            length_label="length",
        )
        payload_dict["units"] = "m"
    else:
        if "value" in payload_dict:
            payload_dict["value"] = parse_to_canonical_magnitude(
                payload_dict["value"],
                location=f"{location_prefix}.value",
                canonical_unit="m",
                explicit_unit=explicit_units,
                length_label="length",
            )
            payload_dict["units"] = "m"
        else:
            payload_dict.pop("value", None)

    # Normalize unit alias and apply process defaults.
    if "units" not in payload_dict and "unit" in payload_dict:
        payload_dict["units"] = payload_dict.pop("unit")
    else:
        payload_dict.pop("unit", None)
    payload_dict.setdefault("id", "h")
    payload_dict.setdefault("units", "m")
    payload_dict.setdefault("description", "Initial condition 'h'")
    payload_dict["type"] = ic_type
    return payload_dict


def _extract_explicit_units(payload: Mapping[str, object]) -> str | None:
    if "units" in payload:
        return str(payload["units"])
    if "unit" in payload:
        return str(payload["unit"])
    return None
