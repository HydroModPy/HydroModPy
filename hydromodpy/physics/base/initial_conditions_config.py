"""
Base Module: Initial-Condition Normalization Helpers
====================================================

Provides utility functions to convert raw configuration payloads into validated
`InitialCondition` instances.
"""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Real

from hydromodpy.physics.base.initial_conditions import InitialCondition


def normalize_initial_condition_payload(
    value: object,
    *,
    default_id: str = "initial_condition",
    location_prefix: str = "process.ic",
) -> InitialCondition:
    """Normalize one generic initial-condition payload into `InitialCondition`."""
    if isinstance(value, InitialCondition):
        return value
    if isinstance(value, bool):
        raise TypeError(f"{location_prefix} must be a mapping or numeric value")
    if isinstance(value, Real):
        return InitialCondition(
            id=default_id,
            value=float(value),
        )
    if not isinstance(value, Mapping):
        raise TypeError(f"{location_prefix} must be a mapping payload")

    payload = dict(value)
    payload.setdefault("id", default_id)
    if "units" not in payload and "unit" in payload:
        payload["units"] = payload["unit"]
    return InitialCondition.model_validate(payload)
