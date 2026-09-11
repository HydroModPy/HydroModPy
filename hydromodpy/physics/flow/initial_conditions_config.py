"""
Flow Initial Condition Normalizers
==================================

Normalization helpers for `[flow.ic]` payloads.

This module accepts compact user payloads and returns the typed runtime/config
structure `FlowInitialConditions`.
"""

from __future__ import annotations

from collections.abc import Mapping

from hydromodpy.core.units import parse_to_canonical_magnitude
from hydromodpy.physics.flow.initial_conditions import (
    _FLOW_IC_ADAPTER,
    FlowICBottom,
    FlowICCustom,
    FlowICSpinupCyclic,
    FlowICSteadyState,
    FlowICTop,
    FlowICTopOffset,
    FlowInitialConditions,
)

_FLOW_IC_VARIANT_TYPES = (
    FlowICTop,
    FlowICTopOffset,
    FlowICBottom,
    FlowICCustom,
    FlowICSpinupCyclic,
    FlowICSteadyState,
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
    - any concrete `FlowInitialCondition` variant -> wrapped as `{"h": ...}`
    - flat mapping with keys `type`, `value`, `unit|units`, `description`,
      `source`, `recharge_statistic`, `rate`, `boundary_condition_policy`;
      `type` is required for any non-empty mapping;
      `value` and `unit|units` are accepted only for `custom` and
      `top_offset`, and `value` can be numeric or a string like `"12.5 m"`
    """
    if value is None:
        return None
    if isinstance(value, FlowInitialConditions):
        return value
    if isinstance(value, _FLOW_IC_VARIANT_TYPES):
        return FlowInitialConditions(h=value)
    if not isinstance(value, Mapping):
        raise TypeError(
            f"{location_prefix} must be a mapping, FlowInitialCondition, or FlowInitialConditions"
        )

    payload = dict(value)
    if len(payload) == 0:
        return None
    if set(payload) == {"h"} and isinstance(payload["h"], Mapping):
        return FlowInitialConditions.model_validate(payload)

    # Flow IC is intentionally kept flat in TOML (`[flow.ic]`), hence only direct
    # keys are accepted here. The set is DERIVED from the variants of the union,
    # not retyped: a hand-written list is an assertion about the models rather
    # than a fact about them, and it silently refused a new variant's own fields
    # the first time one was added.
    direct_keys = _direct_ic_keys()
    unknown_keys = [str(key).strip() for key in payload if str(key).strip() not in direct_keys]
    if unknown_keys:
        unknown_text = ", ".join(unknown_keys)
        accepted = ", ".join(sorted(direct_keys))
        raise ValueError(
            f"{location_prefix} accepts only direct keys [{accepted}]. Unknown keys: {unknown_text}"
        )

    normalized = _normalize_single_ic_payload(payload, location_prefix=location_prefix)
    return FlowInitialConditions(h=_FLOW_IC_ADAPTER.validate_python(normalized))


_IC_VARIANTS = (
    FlowICTop,
    FlowICTopOffset,
    FlowICBottom,
    FlowICCustom,
    FlowICSteadyState,
    FlowICSpinupCyclic,
)
"""Every variant of the flow initial-condition union, in declaration order."""


def known_ic_types() -> frozenset[str]:
    """Return every ``type`` discriminator the union declares.

    Derived for the same reason the key set is: the hand-written list refused a
    variant that had just been added to the union, which is a contradiction a reader
    cannot see.
    """
    return frozenset(str(variant.model_fields["type"].default) for variant in _IC_VARIANTS)


def _direct_ic_keys() -> frozenset[str]:
    """Return every field any initial-condition variant declares."""
    keys: set[str] = set()
    for variant in _IC_VARIANTS:
        keys.update(variant.model_fields)
    # `unit` is the singular spelling the normaliser folds into `units`; it is not a
    # field on any variant, so deriving the set would silently stop accepting it.
    return frozenset(keys | {"unit"})


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

    if "type" not in payload_dict:
        raise ValueError(f"{location_prefix}.type is required when {location_prefix} is not empty")
    raw_type = payload_dict.get("type")
    ic_type = str(raw_type).strip().lower()
    if ic_type not in known_ic_types():
        raise ValueError(
            f"{location_prefix}.type must be one of: "
            + ", ".join(repr(name) for name in sorted(known_ic_types()))
        )

    explicit_units = _extract_explicit_units(payload_dict)
    if ic_type in {"custom", "top_offset"}:
        if "value" not in payload_dict:
            raise ValueError(f"{location_prefix}.value is required when type='{ic_type}'")
        payload_dict["value"] = parse_to_canonical_magnitude(
            payload_dict["value"],
            location=f"{location_prefix}.value",
            canonical_unit="m",
            explicit_unit=explicit_units,
            length_label="length",
        )
        payload_dict["units"] = "m"
    elif ic_type == "steady_state":
        if "value" in payload_dict:
            raise ValueError(f"{location_prefix}.value is not supported when type='steady_state'")
        if explicit_units is not None:
            raise ValueError(
                f"{location_prefix}.unit/units is not supported when type='steady_state'"
            )
        payload_dict.pop("unit", None)
        payload_dict.pop("units", None)
        payload_dict.setdefault("source", "mean_recharge")
        if str(payload_dict.get("source", "")).strip() != "prescribed":
            payload_dict.setdefault("recharge_statistic", "time_mean")
        payload_dict.setdefault("boundary_condition_policy", "first_period")
    else:
        if "value" in payload_dict:
            raise ValueError(
                f"{location_prefix}.value is only supported when type='custom' or type='top_offset'"
            )
        if explicit_units is not None:
            raise ValueError(
                f"{location_prefix}.unit/units is only supported when type='custom' "
                "or type='top_offset'"
            )
        payload_dict.pop("value", None)
        payload_dict.pop("unit", None)
        payload_dict.pop("units", None)
        for strategy_key in (
            "source",
            "recharge_statistic",
            "rate",
            "boundary_condition_policy",
        ):
            if strategy_key in payload_dict:
                raise ValueError(
                    f"{location_prefix}.{strategy_key} is only supported when type='steady_state'"
                )

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
