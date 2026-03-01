# -*- coding: utf-8 -*-
"""Flow initial-condition payload normalizers."""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Real
from hydromodpy.process.flow.initial_conditions import (
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

    Accepted input shapes:
    - `None` or `{}` -> `None`
    - `FlowInitialConditions` -> passthrough
    - `FlowInitialCondition` -> wrapped as `{"h": ...}`
    - flat mapping with keys `type`, `value`, `unit|units`, `description`
    """
    if value is None:
        return None
    if isinstance(value, FlowInitialConditions):
        return value
    if isinstance(value, FlowInitialCondition):
        return FlowInitialConditions(h=value)
    if not isinstance(value, Mapping):
        raise TypeError(
            f"{location_prefix} must be a mapping, FlowInitialCondition, "
            "or FlowInitialConditions"
        )

    payload = dict(value)
    if len(payload) == 0:
        return None

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
    """Normalize one single flow initial-condition payload."""
    payload_dict = dict(payload)

    raw_type = payload_dict.get("type", "custom")
    ic_type = str(raw_type).strip().lower()
    if ic_type not in {"top", "bottom", "custom"}:
        raise ValueError(
            f"{location_prefix}.type must be one of: 'top', 'bottom', 'custom'"
        )

    if ic_type == "custom":
        if "value" not in payload_dict:
            raise ValueError(f"{location_prefix}.value is required when type='custom'")
        raw_value = payload_dict["value"]
        if isinstance(raw_value, bool) or not isinstance(raw_value, Real):
            raise TypeError(f"{location_prefix}.value must be a numeric value")
        payload_dict["value"] = float(raw_value)
    else:
        if "value" in payload_dict:
            raw_value = payload_dict["value"]
            if isinstance(raw_value, bool) or not isinstance(raw_value, Real):
                raise TypeError(f"{location_prefix}.value must be a numeric value when provided")
            payload_dict["value"] = float(raw_value)
        else:
            payload_dict.pop("value", None)

    if "units" not in payload_dict and "unit" in payload_dict:
        payload_dict["units"] = payload_dict["unit"]
    payload_dict.setdefault("id", "h")
    payload_dict.setdefault("units", "m")
    payload_dict.setdefault("description", "Initial condition 'h'")
    payload_dict["type"] = ic_type
    return payload_dict
